package com.haven.android.data

import com.google.gson.annotations.SerializedName

// ─── Authentication ───────────────────────────────────────────────────────────

data class LoginRequest(
    val email: String,
    val password: String
)

data class TokenResponse(
    @SerializedName("access_token") val accessToken: String,
    @SerializedName("token_type") val tokenType: String = "bearer",
    @SerializedName("role") val role: String,
    @SerializedName("user_id") val userId: String,
    @SerializedName("expires_in") val expiresIn: Int
)

// ─── SOS Incident ─────────────────────────────────────────────────────────────

/**
 * Payload sent to POST /save-extracted-data to create an SOS incident.
 *
 * The backend accepts an optional idempotency_key to prevent duplicate incidents
 * from retried requests. trigger_type is set to SHAKE_SOS to distinguish this
 * channel from voice-SOS and steganography triggers.
 */
data class ShakeSosRequest(
    @SerializedName("decoded_text") val decodedText: String,
    @SerializedName("severity") val severity: String = "critical",
    @SerializedName("immediate_danger") val immediateDanger: Boolean = true,
    @SerializedName("location") val location: String,
    @SerializedName("summary") val summary: String,
    @SerializedName("needs") val needs: List<String>,
    @SerializedName("trigger_type") val triggerType: String = "SHAKE_SOS",
    @SerializedName("idempotency_key") val idempotencyKey: String,
    // Structured latitude/longitude for the authority dashboard map.
    // Only set when a real valid fix is available — never fabricated.
    @SerializedName("latitude") val latitude: Double?,
    @SerializedName("longitude") val longitude: Double?,
    @SerializedName("location_accuracy") val locationAccuracy: Float?,
    @SerializedName("location_freshness") val locationFreshness: String,
    @SerializedName("location_timestamp") val locationTimestamp: String?,
    // Android-specific fields consumed by the dedicated /shake-sos/trigger endpoint
    @SerializedName("cooldown_seconds") val cooldownSeconds: Int = 60,
    @SerializedName("device_model") val deviceModel: String? = android.os.Build.MODEL,
    @SerializedName("shake_threshold_used") val shakeThresholdUsed: Float? = null
)

data class SosResponse(
    @SerializedName("success") val success: Boolean,
    @SerializedName("case_id") val caseId: String?,
    @SerializedName("duplicate") val duplicate: Boolean = false
)

// ─── Location Update ──────────────────────────────────────────────────────────

/**
 * Sent to POST /sos/location-update after a fresh GPS fix arrives
 * (within the update window after initial SOS transmission).
 */
data class LocationUpdateRequest(
    @SerializedName("event_id") val eventId: String,
    @SerializedName("latitude") val latitude: Double,
    @SerializedName("longitude") val longitude: Double,
    @SerializedName("accuracy") val accuracy: Float?,
    @SerializedName("timestamp") val timestamp: String
)

// ─── Trusted Contacts ─────────────────────────────────────────────────────────

data class TrustedContact(
    @SerializedName("contact_id") val contactId: String = "",
    @SerializedName("name") val name: String,
    @SerializedName("phone") val phone: String,
    @SerializedName("email") val email: String = "",
    @SerializedName("priority") val priority: Int = 1
)

data class VoiceSosConfigResponse(
    @SerializedName("configured") val configured: Boolean,
    @SerializedName("enabled") val enabled: Boolean = false,
    @SerializedName("has_safe_word") val hasSafeWord: Boolean = false,
    @SerializedName("contacts") val contacts: List<TrustedContact> = emptyList()
)

// ─── Location Freshness ────────────────────────────────────────────────────────

/**
 * Distinguishes location quality for the authority dashboard.
 * The backend stores this field on the SOS case document.
 */
enum class LocationFreshness(val apiValue: String) {
    /** Obtained within the last 30 seconds via FusedLocationProvider. */
    FRESH("FRESH"),
    /** Last-known location from FusedLocationProvider; age > 30 s but < 10 min. */
    STALE("STALE"),
    /** Last-known location; age ≥ 10 minutes or provider accuracy unknown. */
    LAST_KNOWN("LAST_KNOWN"),
    /** No location was available from any provider. */
    UNAVAILABLE("LOCATION_UNAVAILABLE")
}

// ─── Monitoring Status ────────────────────────────────────────────────────────

/**
 * Describes the monitoring pipeline state.
 * ENABLED = the user switched monitoring on.
 * RUNNING = the foreground service is actually processing sensor events.
 * These are intentionally separate: a service may be enabled but not running
 * if Android terminated it, or if permissions were revoked.
 */
data class MonitoringStatus(
    val userEnabled: Boolean = false,
    val serviceRunning: Boolean = false,
    val locationPermissionGranted: Boolean = false,
    val notificationPermissionGranted: Boolean = false,
    val lastHeartbeatMs: Long = 0L,
    val lastSensorEventMs: Long = 0L,
    val shakeCount: Int = 0
) {
    /** True only when both the user enabled it AND the service is confirmed running. */
    val isActuallyMonitoring: Boolean get() = userEnabled && serviceRunning
}

// ─── Pending Incident Queue ───────────────────────────────────────────────────

enum class PendingIncidentStatus {
    PENDING,
    RETRYING,
    NEEDS_ATTENTION,
    DELIVERED
}

/**
 * A minimal serialisable record of an SOS request that could not be transmitted
 * immediately or failed with a retryable / attention-needed error. Stored in
 * EncryptedSharedPreferences and retried by PendingIncidentWorker.
 *
 * Only the fields needed for retry are persisted — NOT the full contact list or
 * GPS coordinates beyond what is needed to reconstruct the request.
 */
data class PendingIncidentRecord(
    val triggerId: String,
    val requestJson: String,        // Serialised ShakeSosRequest
    val enqueuedAtMs: Long,
    val attemptCount: Int = 0,
    val status: PendingIncidentStatus = PendingIncidentStatus.PENDING,
    val failureReason: String? = null
)
