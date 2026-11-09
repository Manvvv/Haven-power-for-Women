package com.haven.android.repository

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.google.gson.Gson
import com.haven.android.data.PendingIncidentRecord
import com.haven.android.data.PendingIncidentStatus
import com.haven.android.data.HavenApiClient
import com.haven.android.data.ShakeSosRequest
import com.haven.android.data.SosResponse
import retrofit2.Response

/**
 * PendingIncidentWorker
 *
 * WorkManager CoroutineWorker that retries SOS incidents that could not be
 * transmitted due to network failure.
 *
 * Guarantees:
 * - Only processes retryable incidents (skips records marked NEEDS_ATTENTION).
 * - Idempotent: backend deduplicates on idempotency_key (triggerId).
 * - Removes a record from the queue ONLY after a confirmed HTTP 200..299 or confirmed 409 duplicate.
 * - HTTP 401: attempts unauthenticated emergency fallback via /save-extracted-data before giving up.
 * - HTTP 403, 422, or MAX_ATTEMPTS exceeded: marks record as NEEDS_ATTENTION rather than silently
 *   discarding an emergency.
 * - Reports Result.success() when all retryable items are resolved.
 * - Reports Result.retry() on transient failures (network, 5xx, 408, 429).
 */
class PendingIncidentWorker(
    private val context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    companion object {
        private const val TAG = "PendingIncidentWorker"
        private const val MAX_ATTEMPTS = 10
    }

    private val gson = Gson()
    private val tokenRepo = SecureTokenRepository(context)

    override suspend fun doWork(): Result {
        val retryable = PendingIncidentQueue.getRetryableIncidents(context)
        if (retryable.isEmpty()) {
            Log.d(TAG, "No retryable pending incidents; worker done")
            return Result.success()
        }

        val serverUrl = ServerConfigRepository(context).getServerUrl()
        val apiService = HavenApiClient.build(
            serverUrl,
            isDebug = false
        )

        var anyFailed = false
        var anyNeedsRetry = false

        for (record in retryable) {
            if (record.attemptCount >= MAX_ATTEMPTS) {
                Log.w(TAG, "triggerId=${record.triggerId} exceeded MAX_ATTEMPTS ($MAX_ATTEMPTS); marking NEEDS_ATTENTION")
                PendingIncidentQueue.markNeedsAttention(
                    context,
                    record.triggerId,
                    "Exceeded $MAX_ATTEMPTS retry attempts without server confirmation"
                )
                anyFailed = true
                continue
            }

            PendingIncidentQueue.incrementAttempt(context, record.triggerId, PendingIncidentStatus.RETRYING)

            try {
                val request = gson.fromJson(record.requestJson, ShakeSosRequest::class.java)
                val authHeader = tokenRepo.getBearerHeader()
                val response: Response<SosResponse> = if (authHeader != null) {
                    apiService.createSosIncident(authHeader, request)
                } else {
                    apiService.createSosIncident(null, request)
                }

                when {
                    response.isSuccessful -> {
                        val body = response.body()
                        if (body != null && body.success && !body.caseId.isNullOrBlank()) {
                            Log.d(TAG, "Pending incident delivered: triggerId=${record.triggerId} caseId=${body.caseId}")
                            PendingIncidentQueue.remove(context, record.triggerId)
                        } else {
                            Log.w(TAG, "Server returned 200 without caseId for triggerId=${record.triggerId}")
                            anyNeedsRetry = true
                        }
                    }
                    response.code() == 409 -> {
                        if (isConfirmedDuplicate(response, record.triggerId)) {
                            Log.d(TAG, "Duplicate accepted by server: triggerId=${record.triggerId}")
                            PendingIncidentQueue.remove(context, record.triggerId)
                        } else {
                            val detail = parseErrorDetail(response)
                            Log.w(TAG, "Unconfirmed 409 conflict during retry for triggerId=${record.triggerId}")
                            PendingIncidentQueue.markNeedsAttention(
                                context,
                                record.triggerId,
                                "HTTP 409 unconfirmed conflict: $detail"
                            )
                            anyFailed = true
                        }
                    }
                    response.code() == 401 -> {
                        Log.w(TAG, "HTTP 401 during retry for triggerId=${record.triggerId}; attempting emergency fallback")
                        val fallbackResponse = try {
                            apiService.createSosIncident(null, request)
                        } catch (e: Exception) {
                            null
                        }

                        if (fallbackResponse != null && fallbackResponse.isSuccessful) {
                            Log.i(TAG, "Fallback delivered during retry: triggerId=${record.triggerId}")
                            PendingIncidentQueue.remove(context, record.triggerId)
                        } else if (fallbackResponse?.code() == 409 && isConfirmedDuplicate(fallbackResponse, record.triggerId)) {
                            Log.i(TAG, "Fallback duplicate confirmed for triggerId=${record.triggerId}")
                            PendingIncidentQueue.remove(context, record.triggerId)
                        } else if (fallbackResponse == null || fallbackResponse.code() in listOf(408, 429) || fallbackResponse.code() in 500..599) {
                            anyNeedsRetry = true
                        } else {
                            val err = "HTTP 401; unauthenticated fallback rejected with ${fallbackResponse.code()}"
                            PendingIncidentQueue.markNeedsAttention(context, record.triggerId, err)
                            anyFailed = true
                        }
                    }
                    response.code() in listOf(408, 429) || response.code() in 500..599 || response.code() == 0 -> {
                        Log.w(TAG, "Transient failure HTTP ${response.code()} for triggerId=${record.triggerId}")
                        anyNeedsRetry = true
                    }
                    response.code() in listOf(403, 422) -> {
                        val detail = parseErrorDetail(response)
                        Log.e(TAG, "Permanent rejection HTTP ${response.code()} for triggerId=${record.triggerId}: $detail")
                        PendingIncidentQueue.markNeedsAttention(
                            context,
                            record.triggerId,
                            "HTTP ${response.code()}: $detail"
                        )
                        anyFailed = true
                    }
                    else -> {
                        val detail = parseErrorDetail(response)
                        Log.e(TAG, "Client error HTTP ${response.code()} for triggerId=${record.triggerId}: $detail")
                        PendingIncidentQueue.markNeedsAttention(
                            context,
                            record.triggerId,
                            "HTTP ${response.code()}: $detail"
                        )
                        anyFailed = true
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "Exception retrying triggerId=${record.triggerId}: ${e.message}")
                anyNeedsRetry = true
            }
        }

        return when {
            anyNeedsRetry -> Result.retry()
            anyFailed -> Result.failure()
            else -> Result.success()
        }
    }

    private fun isConfirmedDuplicate(response: Response<*>, triggerId: String): Boolean {
        val body = response.body()
        if (body is SosResponse && (body.duplicate || body.caseId != null)) return true
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
}
