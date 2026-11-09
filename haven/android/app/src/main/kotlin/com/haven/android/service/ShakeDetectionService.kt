package com.haven.android.service

import android.app.Notification
import android.app.PendingIntent
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.SensorManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import com.haven.android.BuildConfig
import com.haven.android.HavenApplication
import com.haven.android.R
import com.haven.android.data.HavenApiClient
import com.haven.android.repository.*
import com.haven.android.twa.MonitorControlActivity
import kotlinx.coroutines.*

/**
 * ShakeDetectionService
 *
 * Native Android foreground service that:
 * 1. Registers an accelerometer listener via ShakeDetector.
 * 2. Keeps the CPU awake via a partial WakeLock while the screen is locked.
 * 3. Detects three-shake gestures and triggers the SOS workflow.
 * 4. Obtains GPS location, creates an SOS incident, and queues it if offline.
 * 5. Updates MonitoringStatusRepository with heartbeats so the UI can detect
 *    if the service has been terminated by the OS.
 *
 * Foreground service requirement:
 *   Android 8+ requires that a foreground service call startForeground() within
 *   5 seconds of startService(). We call it immediately in onStartCommand.
 *   The persistent notification is shown at IMPORTANCE_LOW so it is visible
 *   without making noise while the user goes about their day.
 *
 * WakeLock:
 *   A PARTIAL_WAKE_LOCK is acquired to keep the CPU running while the screen
 *   is off. The accelerometer itself wakes the CPU for its callback, but holding
 *   the lock explicitly prevents the CPU from suspending between callbacks on
 *   some devices. Released in onDestroy.
 *
 * Screen lock vs. service termination:
 *   Locking the screen does NOT stop a foreground service. The service continues
 *   running and the sensor listener fires normally. However:
 *   - Android may terminate the service under memory pressure (OOM killer).
 *   - Some OEM battery-saver regimes (MIUI, EMUI, OneUI, ColorOS) aggressively
 *     kill background processes after the user leaves. There is no reliable way
 *     for a normal app to prevent this without requesting device-admin or
 *     accessibility privileges, which HAVEN does not do.
 *   - Force-stopping the app via Settings → Apps terminates ALL processes
 *     immediately; there is NO recovery path until the user opens the app again.
 *
 * The service reports its running state honestly via MonitoringStatusRepository.
 * The UI must not claim monitoring is active after the service is killed.
 *
 * Test mode:
 *   When started with ACTION_START_TEST, the service triggers a test SOS (not a
 *   real emergency) and immediately stops. Test mode is driven from the UI
 *   settings screen and uses isTest=true in SosRepository.submitSosIncident.
 */
class ShakeDetectionService : LifecycleService() {

    companion object {
        private const val TAG = "ShakeDetectionService"

        const val ACTION_START_MONITORING = "com.haven.android.START_MONITORING"
        const val ACTION_STOP_MONITORING  = "com.haven.android.STOP_MONITORING"
        const val ACTION_START_TEST       = "com.haven.android.START_TEST"

        /** Heartbeat written to MonitoringStatusRepository every N ms. */
        private const val HEARTBEAT_INTERVAL_MS = 10_000L

        private const val WAKELOCK_TAG = "HAVEN:ShakeDetectionService"
    }

    // ─── Dependencies ─────────────────────────────────────────────────────────

    private val monitoringRepo by lazy { MonitoringStatusRepository(this) }
    private val locationRepo  by lazy { LocationRepository(this) }
    private val tokenRepo     by lazy { SecureTokenRepository(this) }
    private val sosRepo       by lazy {
        val serverUrl = ServerConfigRepository(this).getServerUrl()
        val apiService = HavenApiClient.build(
            serverUrl,
            isDebug = BuildConfig.DEBUG
        )
        SosRepository(this, apiService, tokenRepo)
    }

    private lateinit var shakeDetector: ShakeDetector
    private var wakeLock: PowerManager.WakeLock? = null
    private var heartbeatJob: Job? = null
    private var isTestMode = false

    // Managed service coroutine scope tied to service lifecycle
    private val serviceJob = SupervisorJob()
    private val serviceScope = CoroutineScope(Dispatchers.Main.immediate + serviceJob)

    // ─── Service Lifecycle ────────────────────────────────────────────────────

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "ShakeDetectionService onCreate")

        val sensorManager = getSystemService(SENSOR_SERVICE) as SensorManager

        shakeDetector = ShakeDetector(
            sensorManager = sensorManager,
            onShakeGestureDetected = { onShakeGestureDetected() },
            onShakeCountChanged = { count ->
                Log.v(TAG, "Shake progress: $count/${ShakeDetector.SHAKES_REQUIRED}")
                serviceScope.launch { monitoringRepo.incrementShakeCount() }
            }
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)

        when (intent?.action) {
            ACTION_STOP_MONITORING -> {
                Log.d(TAG, "Received STOP_MONITORING")
                stopMonitoring()
                return START_NOT_STICKY
            }
            ACTION_START_TEST -> {
                isTestMode = true
                Log.d(TAG, "Starting test mode")
            }
            else -> {
                isTestMode = false
                Log.d(TAG, "Starting real monitoring mode")
            }
        }

        // Must call startForeground immediately — Android 12+ enforces this.
        // On Android 14+ (API 34/35/36), explicitly declare FOREGROUND_SERVICE_TYPE_LOCATION
        // and catch SecurityException if permissions were revoked while inactive.
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ServiceCompat.startForeground(
                    this,
                    HavenApplication.NOTIFICATION_ID_MONITORING,
                    buildMonitoringNotification(),
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
                )
            } else {
                startForeground(
                    HavenApplication.NOTIFICATION_ID_MONITORING,
                    buildMonitoringNotification()
                )
            }
        } catch (e: SecurityException) {
            Log.e(TAG, "Failed to start foreground service: missing required permission", e)
            stopSelf()
            return START_NOT_STICKY
        }

        acquireWakeLock()
        shakeDetector.start()

        serviceScope.launch {
            monitoringRepo.setServiceRunning(true)
        }

        startHeartbeat()
        Log.d(TAG, "ShakeDetectionService started (test=$isTestMode)")

        // START_STICKY: if the system kills the service, it will restart it
        // without an intent (i.e. with null intent → treated as real monitoring).
        // We update serviceRunning=false in onDestroy so the UI detects the gap.
        return START_STICKY
    }

    override fun onDestroy() {
        Log.d(TAG, "ShakeDetectionService onDestroy")
        shakeDetector.stop()
        heartbeatJob?.cancel()
        releaseWakeLock()

        // Update persisted state: service is no longer running.
        // NonCancellable ensures state persistence finishes before job cancellation.
        serviceScope.launch {
            try {
                withContext(NonCancellable + Dispatchers.IO) {
                    monitoringRepo.setServiceRunning(false)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Failed to update serviceRunning state in onDestroy: ${e.message}")
            } finally {
                serviceJob.cancel()
            }
        }

        super.onDestroy()
    }

    override fun onBind(intent: Intent): IBinder? {
        super.onBind(intent)
        return null   // Not a bound service
    }

    // ─── Shake Gesture Handling ───────────────────────────────────────────────

    private fun onShakeGestureDetected() {
        if (isTestMode) {
            Log.i(TAG, "Test shake gesture detected — submitting TEST SOS")
            triggerSos(isTest = true)
        } else {
            Log.i(TAG, "Real shake gesture detected — submitting REAL SOS")
            triggerSos(isTest = false)
        }
    }

    private fun triggerSos(isTest: Boolean) {
        val triggerId = generateTriggerId(isTest)
        Log.i(TAG, "SOS trigger started: triggerId=$triggerId isTest=$isTest")

        serviceScope.launch {
            // Emergency SOS pipeline must run with NonCancellable to guarantee delivery
            // or offline enqueueing even if the service transitions during execution.
            withContext(NonCancellable) {
                try {
                    // 1. Show immediate SOS triggered notification
                    showSosNotification(triggerId, isTest, pending = true)

                    // 2. Obtain location (with timeout built into LocationRepository)
                    val locationResult = locationRepo.getBestAvailableLocation()
                    Log.d(TAG, "Location result: freshness=${locationResult.freshness} accuracy=${locationResult.location?.accuracy}")

                    // 3. Submit to backend (handles null location gracefully; never drops SOS)
                    val result = sosRepo.submitSosIncident(triggerId, locationResult, isTest)

                    when (result) {
                        is SosRepository.SosResult.Success -> {
                            Log.i(TAG, "SOS submitted: caseId=${result.caseId} localPersistenceFailed=${result.localPersistenceFailed}")
                            showSosNotification(triggerId, isTest, pending = false, caseId = result.caseId)

                            // 4. If we have a fresh location, schedule a follow-up update
                            //    (fresh location may arrive after initial submission)
                            if (locationResult.location != null) {
                                delay(5000L)
                                val refreshed = locationRepo.getBestAvailableLocation()
                                if (refreshed.location != null &&
                                    (refreshed.location.time > (locationResult.location?.time ?: 0L))) {
                                    sosRepo.updateLocationIfFresher(result.caseId, refreshed)
                                }
                            }
                        }
                        is SosRepository.SosResult.Queued -> {
                            Log.w(TAG, "SOS queued (offline): triggerId=${result.triggerId}")
                            showSosPendingNotification()
                        }
                        is SosRepository.SosResult.UnpersistedEmergencyFailure -> {
                            Log.e(TAG, "CRITICAL: SOS delivery and local storage both failed for triggerId=${result.triggerId}")
                            showSosCriticalFailureNotification(result.storageReason, result.networkError)
                        }
                        is SosRepository.SosResult.Failure -> {
                            Log.e(TAG, "SOS failed: ${result.message}")
                            // Still show a notification — the user needs to know
                            showSosErrorNotification(result.message)
                        }
                    }

                    // 5. If test mode, stop the service after one trigger
                    if (isTest) {
                        delay(2000L)
                        stopMonitoring()
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Exception in triggerSos: ${e.message}", e)
                }
            }
        }

        // Vibrate for haptic confirmation (works even with silent ringer)
        vibrateConfirmation()
    }

    // ─── Notifications ────────────────────────────────────────────────────────

    private fun buildMonitoringNotification(): Notification {
        val openIntent = Intent(this, MonitorControlActivity::class.java).apply {
            action = "com.haven.android.ACTION_OPEN_SOS_STATUS"
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        val pendingIntent = PendingIntent.getActivity(
            this, 0, openIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        return NotificationCompat.Builder(this, HavenApplication.CHANNEL_MONITORING)
            .setContentTitle(getString(R.string.monitoring_notification_title))
            .setContentText(getString(R.string.monitoring_notification_text))
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setOngoing(true)
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()
    }

    private fun showSosNotification(triggerId: String, isTest: Boolean, pending: Boolean, caseId: String? = null) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as android.app.NotificationManager
        val prefix = if (isTest) "TEST " else ""
        val title = if (pending) "${prefix}SOS Triggered — Transmitting…" else "${prefix}SOS Transmitted"
        val text = if (pending)
            "Emergency request is being sent. ID: $triggerId"
        else
            "Received by HAVEN${caseId?.let { " (Case: $it)" } ?: ""}. Authorities notified."

        val notification = NotificationCompat.Builder(this, HavenApplication.CHANNEL_SOS)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(true)
            .build()

        nm.notify(HavenApplication.NOTIFICATION_ID_SOS, notification)
    }

    private fun showSosPendingNotification() {
        val nm = getSystemService(NOTIFICATION_SERVICE) as android.app.NotificationManager
        val notification = NotificationCompat.Builder(this, HavenApplication.CHANNEL_SOS)
            .setContentTitle(getString(R.string.sos_pending_title))
            .setContentText(getString(R.string.sos_pending_text))
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(false)  // Keep visible until delivered
            .build()

        nm.notify(HavenApplication.NOTIFICATION_ID_SOS, notification)
    }

    private fun showSosCriticalFailureNotification(storageReason: String, networkError: String) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as android.app.NotificationManager
        val notification = NotificationCompat.Builder(this, HavenApplication.CHANNEL_SOS)
            .setContentTitle("🚨 CRITICAL: SOS Delivery & Storage Failed")
            .setContentText("Emergency alert could not be sent or saved offline! CALL EMERGENCY SERVICES NOW.")
            .setStyle(
                NotificationCompat.BigTextStyle().bigText(
                    "CRITICAL: Emergency alert delivery failed ($networkError) and offline local storage failed ($storageReason).\n\nPlease contact emergency services or trusted contacts directly immediately."
                )
            )
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setAutoCancel(false)
            .build()

        nm.notify(HavenApplication.NOTIFICATION_ID_SOS, notification)
    }

    private fun showSosErrorNotification(message: String) {
        val nm = getSystemService(NOTIFICATION_SERVICE) as android.app.NotificationManager
        val notification = NotificationCompat.Builder(this, HavenApplication.CHANNEL_SOS)
            .setContentTitle("⚠️ SOS Transmission Error")
            .setContentText("Could not deliver SOS: $message. Open HAVEN to retry.")
            .setSmallIcon(android.R.drawable.ic_dialog_alert)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .build()

        nm.notify(HavenApplication.NOTIFICATION_ID_SOS, notification)
    }

    // ─── Heartbeat ────────────────────────────────────────────────────────────

    private fun startHeartbeat() {
        heartbeatJob = serviceScope.launch {
            while (isActive) {
                delay(HEARTBEAT_INTERVAL_MS)
                try {
                    monitoringRepo.updateHeartbeat()
                    monitoringRepo.updateLastSensorEvent()
                    Log.v(TAG, "Heartbeat written")
                } catch (e: Exception) {
                    Log.w(TAG, "Heartbeat failed: ${e.message}")
                }
            }
        }
    }

    // ─── WakeLock ─────────────────────────────────────────────────────────────

    private fun acquireWakeLock() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, WAKELOCK_TAG).apply {
            // Timeout: automatically release after 12 hours to prevent runaway battery drain
            // if the service fails to release it normally.
            acquire(12 * 60 * 60 * 1000L)
        }
        Log.d(TAG, "WakeLock acquired")
    }

    private fun releaseWakeLock() {
        wakeLock?.let {
            if (it.isHeld) {
                it.release()
                Log.d(TAG, "WakeLock released")
            }
        }
        wakeLock = null
    }

    // ─── Helpers ──────────────────────────────────────────────────────────────

    private fun stopMonitoring() {
        serviceScope.launch {
            monitoringRepo.setUserEnabled(false)
            monitoringRepo.setServiceRunning(false)
        }
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun generateTriggerId(isTest: Boolean): String {
        val prefix = if (isTest) "TEST" else "SHAKE"
        val ts = System.currentTimeMillis()
        val rand = java.util.UUID.randomUUID().toString().substring(0, 8)
        return "$prefix-$ts-$rand"
    }

    private fun vibrateConfirmation() {
        try {
            val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vm = getSystemService(android.os.VibratorManager::class.java)
                vm.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                getSystemService(VIBRATOR_SERVICE) as android.os.Vibrator
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(
                    android.os.VibrationEffect.createWaveform(
                        longArrayOf(0, 100, 50, 100, 50, 300),
                        -1  // don't repeat
                    )
                )
            } else {
                @Suppress("DEPRECATION")
                vibrator.vibrate(longArrayOf(0, 100, 50, 100, 50, 300), -1)
            }
        } catch (e: Exception) {
            Log.w(TAG, "Vibration failed: ${e.message}")
        }
    }
}
