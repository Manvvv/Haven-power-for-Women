package com.haven.android.repository

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import com.haven.android.data.MonitoringStatus
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * MonitoringStatusRepository
 *
 * Persists monitoring state using Jetpack DataStore (Preferences).
 * DataStore is used instead of SharedPreferences because it is coroutine-safe
 * and avoids disk I/O on the main thread.
 *
 * Key distinction — this repository tracks TWO separate boolean flags:
 *
 *   userEnabled:     The user has explicitly enabled Shake-to-SOS monitoring.
 *                    Survives app restart (persisted). The UI uses this to show
 *                    the current intent.
 *
 *   serviceRunning:  The ShakeDetectionService is confirmed to be actively
 *                    processing sensor events. Updated by the service's own
 *                    lifecycle callbacks (onStartCommand → true; onDestroy → false).
 *                    Also inferred to be false if the lastHeartbeatMs is stale.
 *
 * The UI MUST clearly distinguish these. It is correct to show:
 *   "Monitoring enabled but service has stopped — tap to restart"
 * rather than falsely claiming monitoring is active.
 *
 * lastHeartbeatMs: Written by the service every HEARTBEAT_INTERVAL_MS. If the
 * current time exceeds lastHeartbeatMs + HEARTBEAT_STALE_MS, the service is
 * presumed dead regardless of the serviceRunning flag.
 */
val Context.monitoringDataStore: DataStore<Preferences> by preferencesDataStore(
    name = "haven_monitoring_prefs"
)

class MonitoringStatusRepository(private val context: Context) {

    companion object {
        private val KEY_USER_ENABLED = booleanPreferencesKey("user_enabled")
        private val KEY_SERVICE_RUNNING = booleanPreferencesKey("service_running")
        private val KEY_LAST_HEARTBEAT_MS = longPreferencesKey("last_heartbeat_ms")
        private val KEY_LAST_SENSOR_EVENT_MS = longPreferencesKey("last_sensor_event_ms")
        private val KEY_LOCATION_PERM = booleanPreferencesKey("location_perm_granted")
        private val KEY_NOTIF_PERM = booleanPreferencesKey("notif_perm_granted")
        private val KEY_SHAKE_COUNT = intPreferencesKey("shake_count")

        /** If heartbeat is older than this, treat service as dead. */
        const val HEARTBEAT_STALE_MS = 30_000L
    }

    val statusFlow: Flow<MonitoringStatus> = context.monitoringDataStore.data.map { prefs ->
        val lastHeartbeat = prefs[KEY_LAST_HEARTBEAT_MS] ?: 0L
        val heartbeatStale = (System.currentTimeMillis() - lastHeartbeat) > HEARTBEAT_STALE_MS
        val serviceRunning = (prefs[KEY_SERVICE_RUNNING] ?: false) && !heartbeatStale

        MonitoringStatus(
            userEnabled = prefs[KEY_USER_ENABLED] ?: false,
            serviceRunning = serviceRunning,
            locationPermissionGranted = prefs[KEY_LOCATION_PERM] ?: false,
            notificationPermissionGranted = prefs[KEY_NOTIF_PERM] ?: false,
            lastHeartbeatMs = lastHeartbeat,
            lastSensorEventMs = prefs[KEY_LAST_SENSOR_EVENT_MS] ?: 0L,
            shakeCount = prefs[KEY_SHAKE_COUNT] ?: 0
        )
    }

    suspend fun setUserEnabled(enabled: Boolean) {
        context.monitoringDataStore.edit { prefs ->
            prefs[KEY_USER_ENABLED] = enabled
            if (!enabled) {
                // Explicitly disabled by the user — clear running state.
                prefs[KEY_SERVICE_RUNNING] = false
                prefs[KEY_SHAKE_COUNT] = 0
            }
        }
    }

    suspend fun setServiceRunning(running: Boolean) {
        context.monitoringDataStore.edit { prefs ->
            prefs[KEY_SERVICE_RUNNING] = running
            if (running) {
                prefs[KEY_LAST_HEARTBEAT_MS] = System.currentTimeMillis()
            }
        }
    }

    suspend fun updateHeartbeat() {
        context.monitoringDataStore.edit { prefs ->
            prefs[KEY_LAST_HEARTBEAT_MS] = System.currentTimeMillis()
        }
    }

    suspend fun updateLastSensorEvent() {
        context.monitoringDataStore.edit { prefs ->
            prefs[KEY_LAST_SENSOR_EVENT_MS] = System.currentTimeMillis()
        }
    }

    suspend fun updatePermissions(locationGranted: Boolean, notifGranted: Boolean) {
        context.monitoringDataStore.edit { prefs ->
            prefs[KEY_LOCATION_PERM] = locationGranted
            prefs[KEY_NOTIF_PERM] = notifGranted
        }
    }

    suspend fun incrementShakeCount() {
        context.monitoringDataStore.edit { prefs ->
            prefs[KEY_SHAKE_COUNT] = (prefs[KEY_SHAKE_COUNT] ?: 0) + 1
        }
    }

    suspend fun resetShakeCount() {
        context.monitoringDataStore.edit { prefs ->
            prefs[KEY_SHAKE_COUNT] = 0
        }
    }
}
