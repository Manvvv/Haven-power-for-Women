package com.haven.android.repository

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.util.Log
import androidx.core.content.ContextCompat
import com.google.android.gms.location.CurrentLocationRequest
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.haven.android.data.LocationFreshness
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import kotlin.coroutines.resume

/**
 * LocationResult
 *
 * Wraps a nullable Location along with a documented freshness label.
 * The authority dashboard uses freshness to distinguish how reliable the
 * coordinate is — never fabricate a FRESH label for a stale fix.
 */
data class LocationResult(
    val location: Location?,
    val freshness: LocationFreshness,
    val errorMessage: String? = null
)

/**
 * LocationRepository
 *
 * Obtains the best available device location when SOS is triggered.
 *
 * Design decisions:
 * - Uses FusedLocationProviderClient (Google Play Services) which selects the
 *   best provider (GPS, network, WiFi) and caches fixes more efficiently than
 *   raw LocationManager.
 * - getCurrentLocation() applies a short timeout (LOCATION_TIMEOUT_MS) so that
 *   a GPS fix delay does NOT indefinitely postpone the emergency request.
 * - If getCurrentLocation() times out or fails, getLastLocation() is used with
 *   explicit staleness labelling (STALE vs LAST_KNOWN).
 * - If no location is available at all, UNAVAILABLE is returned honestly.
 * - Coordinates are NEVER fabricated. The backend enforces coordinate validation.
 *
 * Staleness thresholds:
 *   < 30 s   → FRESH
 *   30 s – 10 min → STALE
 *   ≥ 10 min  → LAST_KNOWN
 */
class LocationRepository(private val context: Context) {

    companion object {
        private const val TAG = "LocationRepository"
        private const val LOCATION_TIMEOUT_MS = 8_000L    // 8 second timeout for fresh fix
        private const val STALE_THRESHOLD_MS  = 30_000L   // 30 seconds
        private const val LAST_KNOWN_THRESHOLD_MS = 600_000L  // 10 minutes
    }

    private val fusedClient: FusedLocationProviderClient by lazy {
        LocationServices.getFusedLocationProviderClient(context)
    }

    /**
     * Returns the best available location with honest freshness labelling.
     * Called from the ShakeDetectionService coroutine scope immediately after
     * a valid SOS gesture is confirmed.
     */
    suspend fun getBestAvailableLocation(): LocationResult {
        if (!hasLocationPermission()) {
            Log.w(TAG, "Location permission not granted")
            return LocationResult(null, LocationFreshness.UNAVAILABLE, "Location permission not granted")
        }

        // 1. Try to get a fresh current fix within the timeout.
        val freshResult = withTimeoutOrNull(LOCATION_TIMEOUT_MS) {
            getCurrentLocation()
        }
        if (freshResult != null) {
            Log.d(TAG, "Fresh location obtained: accuracy=${freshResult.location?.accuracy}")
            return freshResult
        }

        // 2. Timeout or GPS unavailable — fall back to last known.
        Log.w(TAG, "Fresh location timed out after ${LOCATION_TIMEOUT_MS}ms; trying last-known")
        return getLastKnownLocation()
    }

    @Suppress("MissingPermission")
    private suspend fun getCurrentLocation(): LocationResult? =
        suspendCancellableCoroutine { cont ->
            val request = CurrentLocationRequest.Builder()
                .setPriority(Priority.PRIORITY_HIGH_ACCURACY)
                .setDurationMillis(LOCATION_TIMEOUT_MS)
                .build()

            fusedClient.getCurrentLocation(request, null)
                .addOnSuccessListener { location ->
                    if (location != null) {
                        val ageMs = System.currentTimeMillis() - location.time
                        val freshness = when {
                            ageMs < STALE_THRESHOLD_MS -> LocationFreshness.FRESH
                            else -> LocationFreshness.STALE
                        }
                        cont.resume(LocationResult(location, freshness))
                    } else {
                        cont.resume(null)
                    }
                }
                .addOnFailureListener { e ->
                    Log.w(TAG, "getCurrentLocation failed: ${e.message}")
                    cont.resume(null)
                }
        }

    @Suppress("MissingPermission")
    private suspend fun getLastKnownLocation(): LocationResult =
        suspendCancellableCoroutine { cont ->
            fusedClient.lastLocation
                .addOnSuccessListener { location ->
                    if (location != null) {
                        val ageMs = System.currentTimeMillis() - location.time
                        val freshness = when {
                            ageMs < STALE_THRESHOLD_MS -> LocationFreshness.STALE
                            ageMs < LAST_KNOWN_THRESHOLD_MS -> LocationFreshness.STALE
                            else -> LocationFreshness.LAST_KNOWN
                        }
                        Log.d(TAG, "Last-known location: age=${ageMs}ms freshness=$freshness accuracy=${location.accuracy}")
                        cont.resume(LocationResult(location, freshness))
                    } else {
                        Log.w(TAG, "No last-known location available")
                        cont.resume(LocationResult(null, LocationFreshness.UNAVAILABLE, "No location available"))
                    }
                }
                .addOnFailureListener { e ->
                    Log.w(TAG, "getLastLocation failed: ${e.message}")
                    cont.resume(LocationResult(null, LocationFreshness.UNAVAILABLE, e.message))
                }
        }

    fun hasLocationPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED
}
