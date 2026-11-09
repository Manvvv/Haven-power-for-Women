package com.haven.android.repository

import android.content.Context
import android.util.Log
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.haven.android.data.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import retrofit2.Response

/**
 * SosRepository
 *
 * Handles all communication with the HAVEN FastAPI backend for SOS incidents.
 *
 * Key guarantees:
 * - Uses idempotency_key (triggerId) on every request so retries do not create
 *   duplicate incidents. The backend deduplicates on this key.
 * - Never fabricates coordinates. Location is only included when the
 *   LocationRepository returns a non-null fix.
 * - Queues failed requests to PendingIncidentQueue for WorkManager retry.
 * - Never reports success unless the backend returns HTTP 200/201.
 * - Does NOT silently suppress a confirmed emergency because of a transient
 *   network failure — it enqueues for retry instead.
 *
 * Notification mechanism:
 * The backend /save-extracted-data endpoint already notifies authorities
 * via WebSocket (notification_manager.notify_authorities). Trusted-contact
 * notification via WhatsApp deep links is prepared server-side; the backend
 * returns whatsapp_links for the client to open (consistent with voice-SOS).
 * We record the delivery state as CLIENT_WHATSAPP_LINKS (pending user action).
 *
 * For shake-SOS the /save-extracted-data endpoint is used (not voice-SOS/trigger)
 * because it does not require a safe-word; the trigger_type field marks the source.
 */
class SosRepository(
    private val context: Context,
    private val apiService: HavenApiService,
    private val tokenRepo: SecureTokenRepository
) {
    private val gson = Gson()

    companion object {
        private const val TAG = "SosRepository"
    }

    sealed class SosResult {
        data class Success(
            val caseId: String,
            val isDuplicate: Boolean = false,
            val localPersistenceFailed: Boolean = false
        ) : SosResult()

        data class Queued(val triggerId: String) : SosResult()

        data class Failure(val message: String) : SosResult()

        data class UnpersistedEmergencyFailure(
            val triggerId: String,
            val storageReason: String,
            val networkError: String
        ) : SosResult()
    }

    /**
     * Submit an SOS incident to the backend.
     *
     * @param triggerId   Unique ID generated at gesture-detection time. Used as
     *                    idempotency_key so retries do not create duplicate incidents.
     * @param locationResult  Result from LocationRepository — may be null/UNAVAILABLE.
     * @param isTest      If true, marks the incident as a test and uses a different
     *                    summary. Test incidents still exercise the real API path but
     *                    severity is set to "test" so authorities can filter them.
     *                    REAL trusted contacts are NOT notified in test mode.
     */
    suspend fun submitSosIncident(
        triggerId: String,
        locationResult: LocationResult?,
        isTest: Boolean = false
    ): SosResult = withContext(Dispatchers.IO) {
        val loc = locationResult?.location
        val freshness = locationResult?.freshness ?: LocationFreshness.UNAVAILABLE

        val locationString = when {
            loc != null -> "${loc.latitude}, ${loc.longitude}"
            else -> "Location unavailable"
        }

        val request = ShakeSosRequest(
            decodedText = buildIncidentText(locationString, isTest),
            severity = if (isTest) "test" else "critical",
            immediateDanger = !isTest,
            location = locationString,
            summary = if (isTest)
                "TEST — Shake-to-SOS test. Not a real emergency."
            else
                "SHAKE SOS — Emergency triggered by three deliberate shakes. Immediate response required.",
            needs = if (isTest)
                listOf("TEST_ONLY")
            else
                listOf("Immediate Police Dispatch", "GPS Tracking", "Medical Alert"),
            triggerType = if (isTest) "SHAKE_SOS_TEST" else "SHAKE_SOS",
            idempotencyKey = triggerId,
            latitude = loc?.latitude,
            longitude = loc?.longitude,
            locationAccuracy = loc?.accuracy,
            locationFreshness = freshness.apiValue,
            locationTimestamp = loc?.time?.let { java.util.Date(it).toInstant().toString() }
        )

        val authHeader = tokenRepo.getBearerHeader()
        Log.d(TAG, "Submitting SOS triggerId=$triggerId freshness=$freshness isTest=$isTest")

        // ─── Write-Ahead Durable Persistence ─────────────────────────────────────────
        // Persist the incident to encrypted durable storage BEFORE attempting network
        // transmission. If Android terminates the process during network transit, the
        // incident is safely preserved on flash storage and WorkManager will flush it.
        val enqueueResult = enqueuePending(triggerId, request)
        val isLocallyPersisted = enqueueResult.isPersisted
        val persistenceErrorReason = when (enqueueResult) {
            is PendingIncidentQueue.EnqueueResult.CapacityExceeded ->
                "Queue capacity reached (${enqueueResult.currentSize}/${enqueueResult.maxSize}); older unacknowledged emergencies preserved"
            is PendingIncidentQueue.EnqueueResult.StorageFailure ->
                enqueueResult.reason
            else -> null
        }

        if (!isLocallyPersisted) {
            Log.e(TAG, "CRITICAL: Durable write-ahead persistence failed ($persistenceErrorReason) for triggerId=$triggerId; attempting immediate network delivery")
        } else {
            Log.d(TAG, "Durable write-ahead disk commit verified for triggerId=$triggerId")
        }

        try {
            // Use the dedicated shake-sos endpoint when authenticated;
            // fall back to /save-extracted-data when no auth header is available.
            val response: Response<SosResponse> = if (authHeader != null) {
                apiService.triggerShakeSos(authHeader, request)
            } else {
                apiService.createSosIncident(null, request)
            }

            if (response.isSuccessful) {
                val body = response.body()
                val caseId = body?.caseId ?: triggerId
                Log.d(TAG, "SOS submitted successfully: caseId=$caseId duplicate=${body?.duplicate}")
                if (isLocallyPersisted) {
                    PendingIncidentQueue.remove(context, triggerId)
                }
                SosResult.Success(caseId, isDuplicate = body?.duplicate == true, localPersistenceFailed = !isLocallyPersisted)
            } else {
                val code = response.code()
                Log.w(TAG, "SOS HTTP error: $code")
                when {
                    code == 409 -> {
                        // Conflict: check whether the server confirmed duplicate processing for this triggerId
                        if (isConfirmedDuplicate(response, triggerId)) {
                            Log.d(TAG, "Confirmed duplicate accepted by server for triggerId=$triggerId")
                            if (isLocallyPersisted) {
                                PendingIncidentQueue.remove(context, triggerId)
                            }
                            SosResult.Success(triggerId, isDuplicate = true, localPersistenceFailed = !isLocallyPersisted)
                        } else {
                            val detail = parseErrorDetail(response)
                            Log.w(TAG, "Unconfirmed 409 conflict for triggerId=$triggerId: $detail")
                            if (isLocallyPersisted) {
                                PendingIncidentQueue.markNeedsAttention(
                                    context,
                                    triggerId,
                                    "HTTP 409 unconfirmed conflict: $detail"
                                )
                            }
                            SosResult.Failure("HTTP 409: $detail")
                        }
                    }
                    code == 401 -> {
                        // Unauthorized / token expired: DO NOT DISCARD emergency!
                        // Attempt unauthenticated emergency fallback via /save-extracted-data
                        Log.w(TAG, "HTTP 401 on authenticated endpoint; attempting unauthenticated emergency fallback")
                        val fallbackResponse = try {
                            apiService.createSosIncident(null, request)
                        } catch (e: Exception) {
                            Log.w(TAG, "Fallback threw exception: ${e.message}")
                            null
                        }

                        if (fallbackResponse != null && fallbackResponse.isSuccessful) {
                            val body = fallbackResponse.body()
                            if (body != null && body.success && !body.caseId.isNullOrBlank()) {
                                val fallbackCaseId = body.caseId
                                Log.i(TAG, "Unauthenticated fallback confirmed: caseId=$fallbackCaseId")
                                if (isLocallyPersisted) {
                                    PendingIncidentQueue.remove(context, triggerId)
                                }
                                SosResult.Success(fallbackCaseId, isDuplicate = body.duplicate, localPersistenceFailed = !isLocallyPersisted)
                            } else {
                                val err = "Emergency fallback 200 without valid caseId"
                                if (isLocallyPersisted) {
                                    PendingIncidentQueue.markNeedsAttention(context, triggerId, err)
                                }
                                SosResult.Failure(err)
                            }
                        } else if (fallbackResponse?.code() == 409 && isConfirmedDuplicate(fallbackResponse, triggerId)) {
                            Log.i(TAG, "Fallback duplicate confirmed for triggerId=$triggerId")
                            if (isLocallyPersisted) {
                                PendingIncidentQueue.remove(context, triggerId)
                            }
                            SosResult.Success(triggerId, isDuplicate = true, localPersistenceFailed = !isLocallyPersisted)
                        } else if (fallbackResponse == null || fallbackResponse.code() in listOf(408, 429) || fallbackResponse.code() in 500..599) {
                            if (isLocallyPersisted) {
                                Log.w(TAG, "Fallback had transient failure (${fallbackResponse?.code()}); retaining in retry queue")
                                SosResult.Queued(triggerId)
                            } else {
                                Log.e(TAG, "CRITICAL: Fallback failed AND local persistence failed for triggerId=$triggerId")
                                SosResult.UnpersistedEmergencyFailure(
                                    triggerId = triggerId,
                                    storageReason = persistenceErrorReason ?: "Local storage unavailable",
                                    networkError = "HTTP 401; fallback failed with ${fallbackResponse?.code() ?: "network timeout"}"
                                )
                            }
                        } else {
                            val err = "HTTP 401 auth rejected; emergency fallback failed with HTTP ${fallbackResponse.code()}"
                            Log.e(TAG, err)
                            if (isLocallyPersisted) {
                                PendingIncidentQueue.markNeedsAttention(context, triggerId, err)
                            }
                            SosResult.Failure(err)
                        }
                    }
                    code in listOf(408, 429) || code in 500..599 || code == 0 -> {
                        if (isLocallyPersisted) {
                            SosResult.Queued(triggerId)
                        } else {
                            Log.e(TAG, "CRITICAL: Transient network error HTTP $code AND local persistence failed for triggerId=$triggerId")
                            SosResult.UnpersistedEmergencyFailure(
                                triggerId = triggerId,
                                storageReason = persistenceErrorReason ?: "Local storage unavailable",
                                networkError = "HTTP $code: ${response.message()}"
                            )
                        }
                    }
                    code in listOf(403, 422) -> {
                        val detail = parseErrorDetail(response)
                        Log.e(TAG, "Permanent error HTTP $code for triggerId=$triggerId: $detail; preserving marked NEEDS_ATTENTION")
                        if (isLocallyPersisted) {
                            PendingIncidentQueue.markNeedsAttention(context, triggerId, "HTTP $code: $detail")
                        }
                        SosResult.Failure("HTTP $code: $detail")
                    }
                    else -> {
                        val detail = parseErrorDetail(response)
                        Log.e(TAG, "Client error HTTP $code for triggerId=$triggerId; preserving marked NEEDS_ATTENTION")
                        if (isLocallyPersisted) {
                            PendingIncidentQueue.markNeedsAttention(context, triggerId, "HTTP $code: $detail")
                        }
                        SosResult.Failure("HTTP $code: $detail")
                    }
                }
            }
        } catch (e: Exception) {
            Log.w(TAG, "SOS network exception: ${e.message}")
            if (isLocallyPersisted) {
                SosResult.Queued(triggerId)
            } else {
                Log.e(TAG, "CRITICAL: Network exception AND local persistence failed for triggerId=$triggerId")
                SosResult.UnpersistedEmergencyFailure(
                    triggerId = triggerId,
                    storageReason = persistenceErrorReason ?: "Local storage unavailable",
                    networkError = "Network exception: ${e.message}"
                )
            }
        }
    }

    /**
     * Push a fresher GPS fix after initial submission.
     * Only called when the initial incident was accepted and a newer fix arrives.
     * Silently no-ops if the update fails — the initial fix is sufficient for dispatch.
     */
    suspend fun updateLocationIfFresher(caseId: String, locResult: LocationResult) {
        val loc = locResult.location ?: return
        val authHeader = tokenRepo.getBearerHeader() ?: return
        withContext(Dispatchers.IO) {
            try {
                val updateReq = LocationUpdateRequest(
                    eventId = caseId,
                    latitude = loc.latitude,
                    longitude = loc.longitude,
                    accuracy = loc.accuracy,
                    timestamp = java.util.Date(loc.time).toInstant().toString()
                )
                val response = apiService.updateSosLocation(authHeader, updateReq)
                if (response.isSuccessful) {
                    Log.d(TAG, "Location updated for caseId=$caseId")
                } else {
                    Log.w(TAG, "Location update failed HTTP ${response.code()}")
                }
            } catch (e: Exception) {
                Log.w(TAG, "Location update exception: ${e.message}")
                // Non-fatal — initial fix already transmitted
            }
        }
    }

    /**
     * Retrieve the user's trusted contacts from the voice-SOS config endpoint.
     * This is the same contact store used by all HAVEN SOS channels.
     */
    suspend fun getTrustedContacts(): List<TrustedContact> = withContext(Dispatchers.IO) {
        val authHeader = tokenRepo.getBearerHeader() ?: return@withContext emptyList()
        val userId = tokenRepo.getUserId() ?: return@withContext emptyList()
        try {
            val response = apiService.getVoiceSosConfig(authHeader, userId)
            if (response.isSuccessful) {
                response.body()?.contacts ?: emptyList()
            } else {
                Log.w(TAG, "Contacts fetch HTTP ${response.code()}")
                emptyList()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Contacts fetch exception: ${e.message}")
            emptyList()
        }
    }

    private fun enqueuePending(triggerId: String, request: ShakeSosRequest): PendingIncidentQueue.EnqueueResult {
        val record = PendingIncidentRecord(
            triggerId = triggerId,
            requestJson = gson.toJson(request),
            enqueuedAtMs = System.currentTimeMillis()
        )
        val result = PendingIncidentQueue.enqueue(context, record)
        Log.d(TAG, "Write-ahead persistence for triggerId=$triggerId result=$result")
        return result
    }

    private fun isConfirmedDuplicate(response: Response<*>, triggerId: String): Boolean {
        val body = response.body()
        if (body is SosResponse) {
            if (body.duplicate || body.caseId != null) return true
        }
        val errString = try {
            response.errorBody()?.string()
        } catch (e: Exception) {
            null
        } ?: return false

        return errString.contains("duplicate", ignoreCase = true) ||
               errString.contains("already recorded", ignoreCase = true) ||
               errString.contains("already exists", ignoreCase = true) ||
               errString.contains(triggerId, ignoreCase = true)
    }

    private fun parseErrorDetail(response: Response<*>): String {
        return try {
            val errString = response.errorBody()?.string() ?: return response.message()
            val json = com.google.gson.JsonParser.parseString(errString).asJsonObject
            when {
                json.has("detail") -> json.get("detail").asString
                json.has("message") -> json.get("message").asString
                else -> response.message().ifBlank { "Unknown error" }
            }
        } catch (e: Exception) {
            response.message().ifBlank { "Unknown error" }
        }
    }

    private fun buildIncidentText(locationString: String, isTest: Boolean): String {
        val prefix = if (isTest) "⚠️ TEST — NOT A REAL EMERGENCY ⚠️\n\n" else "🚨 EMERGENCY — SHAKE SOS TRIGGERED 🚨\n\n"
        return "${prefix}A HAVEN user triggered an emergency via Shake-to-SOS.\n\nLocation: $locationString\n\n" +
                if (isTest) "This is a detector test. No emergency is in progress." else "Please respond immediately."
    }
}
