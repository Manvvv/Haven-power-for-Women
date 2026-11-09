package com.haven.android.service

import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.util.Log
import kotlin.math.sqrt

/**
 * ShakeDetector
 *
 * Detects a deliberate three-shake gesture using the Android SensorManager
 * accelerometer API.
 *
 * Algorithm:
 * 1. Remove gravity from each accelerometer axis using a simple high-pass filter
 *    (EMA α=0.8). This isolates the linear acceleration component and handles
 *    any phone orientation automatically (no axis mapping needed).
 * 2. Compute the magnitude of the linear acceleration vector: √(ax²+ay²+az²).
 * 3. If magnitude ≥ SHAKE_THRESHOLD, record a shake event — provided the
 *    minimum interval SHAKE_MIN_INTERVAL_MS has elapsed since the last shake
 *    (debounce). This prevents a single continued shake from registering multiple
 *    shake events.
 * 4. Three shake events within SHAKE_WINDOW_MS count as a confirmed gesture.
 * 5. After a confirmed gesture, a COOLDOWN_MS window blocks further triggers.
 *    This prevents a single long shake from creating multiple SOS incidents.
 *
 * Why three shakes:
 *   Two is too easily triggered by everyday drops or vigorous walking.
 *   Three consecutive deliberate movements are unlikely in normal phone use.
 *
 * Sensor sampling rate:
 *   SENSOR_DELAY_GAME (20ms ~ 50Hz). Faster than NORMAL (200ms) but slower
 *   than FASTEST. At 50Hz we detect sudden movements without excessive battery
 *   drain (the accelerometer is a hardware interrupt; CPU is not woken at 50Hz).
 *
 * Battery note:
 *   The accelerometer is a low-power hardware sensor; continuous registration at
 *   GAME rate has minimal impact on modern chipsets. The sensor listener is
 *   unregistered in onDestroy to prevent leaks.
 *
 * Thread safety:
 *   onSensorChanged is called on a dedicated SensorThread, not the main thread.
 *   All state mutations use @Volatile or are accessed only from this callback.
 */
class ShakeDetector(
    private val sensorManager: SensorManager,
    private val onShakeGestureDetected: () -> Unit,
    private val onShakeCountChanged: (Int) -> Unit = {}
) : SensorEventListener {

    companion object {
        private const val TAG = "ShakeDetector"

        /**
         * Acceleration threshold in m/s² above which a reading counts as a shake.
         * Gravity is 9.8 m/s²; typical deliberate shake is 15–30 m/s².
         * 12.0 rejects walking bounces (~2–4 m/s²) and drops/bumps while
         * requiring a genuine flicking motion.
         *
         * Configurable via setThreshold() for the settings screen test mode.
         */
        const val DEFAULT_SHAKE_THRESHOLD = 12.0f

        /** Minimum ms between two shake events within a window (debounce). */
        const val SHAKE_MIN_INTERVAL_MS = 250L

        /** Time window within which three shakes must occur. */
        const val SHAKE_WINDOW_MS = 2500L

        /** Cooldown after a successful three-shake gesture. */
        const val COOLDOWN_MS = 10_000L

        /** Required number of shakes. */
        const val SHAKES_REQUIRED = 3

        /** High-pass filter alpha — fraction of gravity retained per sample.
         *  0.8 means we keep 80% of the previous gravity estimate + 20% of new reading.
         *  Higher values → slower gravity tracking (more latency but smoother). */
        private const val FILTER_ALPHA = 0.8f
    }

    @Volatile var shakeThreshold: Float = DEFAULT_SHAKE_THRESHOLD

    // Gravity components for high-pass filter (updated per sample)
    private var gravityX = 0f
    private var gravityY = 0f
    private var gravityZ = 0f

    // Timestamps of the last SHAKES_REQUIRED shake events
    private val shakeTimestamps = ArrayDeque<Long>(SHAKES_REQUIRED)

    @Volatile private var lastShakeMs = 0L
    @Volatile private var cooldownUntilMs = 0L
    @Volatile private var isRegistered = false

    /** Register the sensor listener. Must be called to begin monitoring. */
    fun start() {
        val accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        if (accelerometer == null) {
            Log.w(TAG, "No accelerometer sensor available on this device")
            return
        }
        val ok = sensorManager.registerListener(
            this,
            accelerometer,
            SensorManager.SENSOR_DELAY_GAME   // ~50 Hz
        )
        isRegistered = ok
        Log.d(TAG, "Accelerometer listener registered: $ok maxRange=${accelerometer.maximumRange}")
    }

    /** Unregister the listener. Call from service onDestroy to prevent leaks. */
    fun stop() {
        if (isRegistered) {
            sensorManager.unregisterListener(this)
            isRegistered = false
            Log.d(TAG, "Accelerometer listener unregistered")
        }
    }

    override fun onSensorChanged(event: SensorEvent) {
        if (event.sensor.type != Sensor.TYPE_ACCELEROMETER) return

        // ── Step 1: High-pass filter to isolate linear acceleration ──────────
        // gravity estimate updated via EMA (exponential moving average)
        gravityX = FILTER_ALPHA * gravityX + (1 - FILTER_ALPHA) * event.values[0]
        gravityY = FILTER_ALPHA * gravityY + (1 - FILTER_ALPHA) * event.values[1]
        gravityZ = FILTER_ALPHA * gravityZ + (1 - FILTER_ALPHA) * event.values[2]

        val linX = event.values[0] - gravityX
        val linY = event.values[1] - gravityY
        val linZ = event.values[2] - gravityZ

        // ── Step 2: Linear acceleration magnitude ────────────────────────────
        val magnitude = sqrt((linX * linX + linY * linY + linZ * linZ).toDouble()).toFloat()

        // ── Step 3: Threshold + debounce ─────────────────────────────────────
        val nowMs = System.currentTimeMillis()

        if (magnitude < shakeThreshold) return        // below threshold — ignore
        if (nowMs < cooldownUntilMs) return            // in post-gesture cooldown
        if (nowMs - lastShakeMs < SHAKE_MIN_INTERVAL_MS) return  // debounce

        // Valid shake event
        lastShakeMs = nowMs
        shakeTimestamps.addLast(nowMs)

        // Remove events outside the detection window
        while (shakeTimestamps.isNotEmpty() && nowMs - shakeTimestamps.first() > SHAKE_WINDOW_MS) {
            shakeTimestamps.removeFirst()
        }

        val currentCount = shakeTimestamps.size
        Log.v(TAG, "Shake $currentCount/$SHAKES_REQUIRED — magnitude=%.1f threshold=%.1f".format(magnitude, shakeThreshold))
        onShakeCountChanged(currentCount)

        // ── Step 4: Gesture confirmed ────────────────────────────────────────
        if (currentCount >= SHAKES_REQUIRED) {
            cooldownUntilMs = nowMs + COOLDOWN_MS
            shakeTimestamps.clear()
            onShakeCountChanged(0)   // reset display count
            Log.i(TAG, "Three-shake gesture confirmed — triggering SOS callback")
            onShakeGestureDetected()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // Accelerometer accuracy changes are not relevant for shake detection
    }

    /** Reset all state — used after a test or after a cooldown expires. */
    fun reset() {
        shakeTimestamps.clear()
        lastShakeMs = 0L
        cooldownUntilMs = 0L
    }

    fun isInCooldown(): Boolean = System.currentTimeMillis() < cooldownUntilMs
}
