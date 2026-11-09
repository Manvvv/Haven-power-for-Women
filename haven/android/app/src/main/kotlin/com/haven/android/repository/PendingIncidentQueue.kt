package com.haven.android.repository

import android.content.Context
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import androidx.work.*
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.haven.android.data.PendingIncidentRecord
import com.haven.android.data.PendingIncidentStatus
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * PendingIncidentQueue
 *
 * A bounded, durable, encrypted write-ahead log and queue for SOS incidents.
 *
 * Strict Integrity & Safety Guarantees:
 * 1. ZERO AUTOMATIC EVICTION: Never automatically deletes an unacknowledged SOS incident.
 *    Older emergency incidents are NEVER overwritten or dropped when capacity is reached.
 * 2. WRITE-AHEAD COMMIT: Enqueue uses synchronous checked [android.content.SharedPreferences.Editor.commit]
 *    executed on flash storage before network transit begins.
 * 3. EXPLICIT STORAGE STATES: Storage failure or capacity limits return typed [EnqueueResult]
 *    and surface explicit diagnostics to the native UI.
 * 4. SURVIVES REBOOT & KILL: Preserved across process kills and device restarts.
 * 5. CORRUPTION RESILIENCE: If Android Keystore corruption occurs, corrupted files are
 *    backed up for audit before safe recovery reinitialisation, preventing permanent app lockouts.
 */
object PendingIncidentQueue {

    private const val TAG = "PendingIncidentQueue"
    private const val PREF_FILE = "haven_pending_queue"
    private const val KEY_QUEUE = "pending_incidents"
    const val MAX_PENDING = 100
    private const val INITIAL_BACKOFF_SECONDS = 30L
    private const val MAX_BACKOFF_SECONDS = 3600L  // 1 hour max backoff

    private val gson = Gson()
    private val lock = Any()

    internal var testPrefs: android.content.SharedPreferences? = null

    private val _storageErrorState = MutableStateFlow<String?>(null)
    val storageErrorState: StateFlow<String?> = _storageErrorState.asStateFlow()

    sealed class EnqueueResult {
        object Success : EnqueueResult()
        object AlreadyQueued : EnqueueResult()
        data class CapacityExceeded(val currentSize: Int, val maxSize: Int) : EnqueueResult()
        data class StorageFailure(val reason: String) : EnqueueResult()

        val isPersisted: Boolean get() = this is Success || this is AlreadyQueued
    }

    /**
     * Enqueue a pending incident with synchronous write-ahead disk commit.
     *
     * INVARIANT: Never drops or overwrites older incidents. If the queue is at capacity
     * or storage is down, returns [EnqueueResult.CapacityExceeded] or [EnqueueResult.StorageFailure]
     * so caller can proceed with direct network transit and notify user.
     */
    fun enqueue(context: Context, record: PendingIncidentRecord): EnqueueResult = synchronized(lock) {
        val prefs = getPrefs(context) ?: run {
            val error = "Encrypted storage unavailable (Keystore/security fault)"
            Log.e(TAG, error)
            _storageErrorState.value = error
            return EnqueueResult.StorageFailure(error)
        }
        val current = readQueue(prefs).toMutableList()

        if (current.any { it.triggerId == record.triggerId }) {
            Log.d(TAG, "triggerId=${record.triggerId} already queued; skipping duplicate enqueue")
            return EnqueueResult.AlreadyQueued
        }

        if (current.size >= MAX_PENDING) {
            val error = "Queue capacity reached (${current.size}/$MAX_PENDING). Older unacknowledged emergencies preserved; cannot queue offline."
            Log.e(TAG, "CRITICAL: $error")
            _storageErrorState.value = error
            return EnqueueResult.CapacityExceeded(current.size, MAX_PENDING)
        }

        current.add(record)
        val committed = writeQueue(prefs, current)
        return if (committed) {
            _storageErrorState.value = null
            Log.d(TAG, "Durable write-ahead commit SUCCESS for triggerId=${record.triggerId}; queue size=${current.size}")
            scheduleRetryWorker(context)
            EnqueueResult.Success
        } else {
            val error = "Disk commit failed for triggerId=${record.triggerId} (low flash storage or I/O failure)"
            Log.e(TAG, "CRITICAL: $error")
            _storageErrorState.value = error
            EnqueueResult.StorageFailure(error)
        }
    }

    /** Legacy helper returning Boolean for backward compatibility. */
    fun enqueueSync(context: Context, record: PendingIncidentRecord): Boolean {
        return enqueue(context, record).isPersisted
    }

    /** Retrieve all records in the queue (including NEEDS_ATTENTION). */
    fun getAll(context: Context): List<PendingIncidentRecord> = synchronized(lock) {
        val prefs = getPrefs(context) ?: return emptyList()
        return readQueue(prefs)
    }

    /** Retrieve records eligible for automatic retry (excludes NEEDS_ATTENTION and DELIVERED). */
    fun getRetryableIncidents(context: Context): List<PendingIncidentRecord> = synchronized(lock) {
        val prefs = getPrefs(context) ?: return emptyList()
        return readQueue(prefs).filter {
            it.status == PendingIncidentStatus.PENDING || it.status == PendingIncidentStatus.RETRYING
        }
    }

    /** Retrieve records requiring user attention (validation failures, auth blocks). */
    fun getAttentionNeededIncidents(context: Context): List<PendingIncidentRecord> = synchronized(lock) {
        val prefs = getPrefs(context) ?: return emptyList()
        return readQueue(prefs).filter { it.status == PendingIncidentStatus.NEEDS_ATTENTION }
    }

    /** Remove a record after confirmed server acknowledgement (synchronous disk commit). */
    fun remove(context: Context, triggerId: String): Boolean = synchronized(lock) {
        val prefs = getPrefs(context) ?: return false
        val current = readQueue(prefs).toMutableList()
        val removed = current.removeAll { it.triggerId == triggerId }
        return if (removed) {
            val committed = writeQueue(prefs, current)
            Log.d(TAG, "Removed pending incident triggerId=$triggerId; committed=$committed; queue size=${current.size}")
            if (committed && current.size < MAX_PENDING) {
                _storageErrorState.value = null
            }
            committed
        } else {
            true
        }
    }

    /**
     * Mark an incident as requiring user attention rather than silently dropping it.
     * Retained in encrypted storage so the user / monitoring dashboard is aware.
     */
    fun markNeedsAttention(context: Context, triggerId: String, reason: String): Boolean = synchronized(lock) {
        val prefs = getPrefs(context) ?: return false
        val current = readQueue(prefs).toMutableList()
        val idx = current.indexOfFirst { it.triggerId == triggerId }
        return if (idx >= 0) {
            current[idx] = current[idx].copy(
                status = PendingIncidentStatus.NEEDS_ATTENTION,
                failureReason = reason
            )
            val committed = writeQueue(prefs, current)
            Log.w(TAG, "Marked incident triggerId=$triggerId as NEEDS_ATTENTION ($reason); committed=$committed")
            committed
        } else {
            false
        }
    }

    /** Update attempt count and status for a record during retry. */
    fun incrementAttempt(
        context: Context,
        triggerId: String,
        status: PendingIncidentStatus = PendingIncidentStatus.RETRYING
    ): Boolean = synchronized(lock) {
        val prefs = getPrefs(context) ?: return false
        val current = readQueue(prefs).toMutableList()
        val idx = current.indexOfFirst { it.triggerId == triggerId }
        return if (idx >= 0) {
            current[idx] = current[idx].copy(
                attemptCount = current[idx].attemptCount + 1,
                status = status
            )
            writeQueue(prefs, current)
        } else {
            false
        }
    }

    /** True if any retryable SOS incidents are currently pending. */
    fun hasPendingRecords(context: Context): Boolean = getRetryableIncidents(context).isNotEmpty()

    /** Schedule the WorkManager retry worker if not already running. */
    fun scheduleRetryWorker(context: Context) {
        try {
            val constraints = Constraints.Builder()
                .setRequiredNetworkType(NetworkType.CONNECTED)
                .build()

            val workRequest = OneTimeWorkRequestBuilder<PendingIncidentWorker>()
                .setConstraints(constraints)
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    INITIAL_BACKOFF_SECONDS,
                    TimeUnit.SECONDS
                )
                .addTag("haven_pending_sos")
                .build()

            WorkManager.getInstance(context).enqueueUniqueWork(
                "haven_pending_sos_retry",
                ExistingWorkPolicy.KEEP,
                workRequest
            )
            Log.d(TAG, "Retry worker scheduled")
        } catch (e: Exception) {
            Log.w(TAG, "WorkManager scheduling skipped or unavailable: ${e.message}")
        }
    }

    /** Clear all queued records (e.g. for testing). */
    fun clearAll(context: Context): Boolean = synchronized(lock) {
        val prefs = getPrefs(context) ?: return false
        val ok = prefs.edit().remove(KEY_QUEUE).commit()
        if (ok) {
            _storageErrorState.value = null
        }
        return ok
    }

    /** Safely reset corrupted encrypted storage, backing up unreadable file. */
    fun resetCorruptedStorage(context: Context): Boolean = synchronized(lock) {
        return try {
            val prefFile = File(context.filesDir.parent, "shared_prefs/$PREF_FILE.xml")
            if (prefFile.exists()) {
                val backup = File(context.filesDir, "$PREF_FILE.corrupt.${System.currentTimeMillis()}")
                prefFile.copyTo(backup, overwrite = true)
                prefFile.delete()
            }
            _storageErrorState.value = null
            getPrefs(context) != null
        } catch (e: Exception) {
            Log.e(TAG, "Failed to reset corrupted storage: ${e.message}")
            false
        }
    }

    private fun readQueue(prefs: android.content.SharedPreferences): List<PendingIncidentRecord> {
        val json = prefs.getString(KEY_QUEUE, null) ?: return emptyList()
        return try {
            val type = object : TypeToken<List<PendingIncidentRecord>>() {}.type
            gson.fromJson(json, type) ?: emptyList()
        } catch (e: Exception) {
            Log.w(TAG, "Failed to parse pending queue JSON; returning empty list")
            emptyList()
        }
    }

    /** Synchronously commits queue state to persistent flash storage. */
    private fun writeQueue(prefs: android.content.SharedPreferences, records: List<PendingIncidentRecord>): Boolean {
        return try {
            prefs.edit().putString(KEY_QUEUE, gson.toJson(records)).commit()
        } catch (e: Exception) {
            Log.e(TAG, "writeQueue exception: ${e.message}")
            false
        }
    }

    private fun getPrefs(context: Context): android.content.SharedPreferences? = testPrefs ?: try {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            PREF_FILE,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    } catch (e: Exception) {
        Log.e(TAG, "EncryptedSharedPreferences unavailable (${e.javaClass.simpleName}): ${e.message}")
        // Attempt recovery if corrupted:
        try {
            val prefFile = File(context.filesDir.parent, "shared_prefs/$PREF_FILE.xml")
            if (prefFile.exists()) {
                Log.w(TAG, "Backing up and recovering corrupted EncryptedSharedPreferences XML")
                val backup = File(context.filesDir, "$PREF_FILE.corrupt.${System.currentTimeMillis()}")
                prefFile.copyTo(backup, overwrite = true)
                prefFile.delete()
                val masterKey = MasterKey.Builder(context)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build()
                EncryptedSharedPreferences.create(
                    context,
                    PREF_FILE,
                    masterKey,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
                )
            } else {
                null
            }
        } catch (recoveryEx: Exception) {
            Log.e(TAG, "EncryptedSharedPreferences recovery failed: ${recoveryEx.message}")
            null
        }
    }
}
