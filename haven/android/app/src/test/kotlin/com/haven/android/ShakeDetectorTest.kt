package com.haven.android

import com.haven.android.service.ShakeDetector
import io.mockk.*
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.Assert.*
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager

/**
 * ShakeDetectorTest
 *
 * Unit tests for the shake detection algorithm.
 *
 * Tests:
 * - Three distinct shakes within window → gesture confirmed
 * - Normal walking movement (low magnitude) → no trigger
 * - Repeated events faster than debounce interval → counts as one shake
 * - Orientation variation → all axes contribute
 * - False positives from single large event → not triggered
 * - Cooldown after confirmed gesture → no second trigger
 * - Duplicate trigger prevention
 *
 * Note: SensorEvent is a system class with package-private fields. We simulate
 * sensor data by exercising the ShakeDetector's internal algorithm directly
 * using reflection, consistent with Android unit-testing conventions.
 */
class ShakeDetectorTest {

    private lateinit var gestureCallback: () -> Unit
    private lateinit var countCallback: (Int) -> Unit
    private var gestureFiredCount = 0
    private var lastCountUpdate = 0
    private lateinit var mockSensorManager: SensorManager
    private lateinit var mockSensor: Sensor

    @Before
    fun setup() {
        gestureFiredCount = 0
        mockSensorManager = mockk(relaxed = true)
        mockSensor = mockk(relaxed = true)

        every { mockSensor.type } returns Sensor.TYPE_ACCELEROMETER
        every { mockSensor.maximumRange } returns 50f
        every { mockSensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER) } returns mockSensor
        every { mockSensorManager.registerListener(any<SensorEventListener>(), any<Sensor>(), any<Int>()) } returns true

        gestureCallback = { gestureFiredCount++ }
        countCallback = { lastCountUpdate = it }
    }

    @After
    fun teardown() {
        unmockkAll()
    }

    // ── Helper: create a ShakeDetector with a mock SensorManager ─────────────

    private fun createDetector(threshold: Float = ShakeDetector.DEFAULT_SHAKE_THRESHOLD): ShakeDetector {
        return ShakeDetector(
            sensorManager = mockSensorManager,
            onShakeGestureDetected = gestureCallback,
            onShakeCountChanged = countCallback
        ).apply { shakeThreshold = threshold }
    }

    /**
     * Simulate a SensorEvent reading using reflection.
     * SensorEvent.values is a package-private float[] field.
     */
    private fun simulateSensorEvent(
        detector: ShakeDetector,
        x: Float, y: Float, z: Float,
        sensor: Sensor = mockSensor
    ) {
        val event = mockk<SensorEvent>(relaxed = true)

        // SensorEvent.sensor is a public field in Android SDK; inject via reflection
        val sensorField = SensorEvent::class.java.getDeclaredField("sensor")
        sensorField.isAccessible = true
        sensorField.set(event, sensor)

        // SensorEvent.values is a float array; inject via reflection
        val valuesField = SensorEvent::class.java.getDeclaredField("values")
        valuesField.isAccessible = true
        valuesField.set(event, floatArrayOf(x, y, z))

        detector.onSensorChanged(event)
    }

    // ── Tests ─────────────────────────────────────────────────────────────────

    @Test
    fun `three distinct shakes within window triggers gesture`() {
        val detector = createDetector()

        // Gravity-free shakes: magnitude ≈ 20 m/s² (well above 12.0 threshold)
        // Simulate by injecting large linear components (gravity converges to 0,0,9.8
        // over many readings, so initial readings have large raw values)
        // To make the test deterministic, reset gravity by sending many low readings
        // then send three high-acceleration readings.

        // Warm up the filter with stationary readings (gravity stabilises)
        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        // Three shake events separated by SHAKE_MIN_INTERVAL_MS + 1
        simulateSensorEvent(detector, 25f, 0f, 9.8f)          // Shake 1
        Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)

        simulateSensorEvent(detector, -25f, 0f, 9.8f)         // Shake 2
        Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)

        simulateSensorEvent(detector, 25f, 0f, 9.8f)          // Shake 3

        assertEquals("Gesture should have fired once", 1, gestureFiredCount)
    }

    @Test
    fun `normal walking movement does not trigger gesture`() {
        val detector = createDetector()

        // Walking generates ~2-4 m/s² linear acceleration — below 12.0 threshold
        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }
        repeat(20) {
            simulateSensorEvent(detector, 3f, 0f, 9.8f)
            Thread.sleep(100)
        }

        assertEquals("Walking should not trigger gesture", 0, gestureFiredCount)
    }

    @Test
    fun `rapid repeated events within debounce interval count as one shake`() {
        val detector = createDetector()

        // Warm up filter
        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        // Send 10 high-acceleration events faster than debounce (SHAKE_MIN_INTERVAL_MS=250ms)
        // All within a 50ms burst — should count as ONE shake event
        repeat(10) {
            simulateSensorEvent(detector, 25f, 0f, 9.8f)
            Thread.sleep(10)  // 10ms apart — much less than 250ms debounce
        }

        // Only 1 shake counted; need 3 for gesture — should not fire
        assertEquals("Debounced rapid events should count as one shake", 0, gestureFiredCount)
        assertTrue("Shake count should be at most 1", lastCountUpdate <= 1)
    }

    @Test
    fun `single continuous shake from one movement is limited by debounce`() {
        val detector = createDetector()

        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        // Continuous shake with no pause — debounce should prevent multiple counts
        repeat(100) {
            simulateSensorEvent(detector, 25f, 0f, 9.8f)
            Thread.sleep(5)   // 5ms apart
        }

        assertEquals("Continuous shake should not bypass debounce for unlimited triggers", 0, gestureFiredCount)
    }

    @Test
    fun `orientation variation detected on any axis`() {
        val detector = createDetector()

        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        // Shake on Y axis
        simulateSensorEvent(detector, 0f, 25f, 9.8f)
        Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)

        // Shake on X axis
        simulateSensorEvent(detector, 25f, 0f, 9.8f)
        Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)

        // Shake on Z axis (diagonal)
        simulateSensorEvent(detector, 0f, 0f, 25f)

        assertEquals("Shakes on different axes should be detected", 1, gestureFiredCount)
    }

    @Test
    fun `gesture not triggered from fewer than three shakes`() {
        val detector = createDetector()
        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        simulateSensorEvent(detector, 25f, 0f, 9.8f)
        Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)
        simulateSensorEvent(detector, -25f, 0f, 9.8f)
        // Only 2 shakes — should not fire
        Thread.sleep(ShakeDetector.SHAKE_WINDOW_MS + 100)  // Wait for window to expire

        assertEquals("Two shakes should not trigger gesture", 0, gestureFiredCount)
    }

    @Test
    fun `shakes outside window do not accumulate for new gesture`() {
        val detector = createDetector()
        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        // Two shakes, then wait for window to expire
        simulateSensorEvent(detector, 25f, 0f, 9.8f)
        Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)
        simulateSensorEvent(detector, -25f, 0f, 9.8f)
        Thread.sleep(ShakeDetector.SHAKE_WINDOW_MS + 200)  // Window expired

        // One more shake — shouldn't trigger with only 1 valid in-window shake
        simulateSensorEvent(detector, 25f, 0f, 9.8f)

        assertEquals("Expired window shakes should not accumulate", 0, gestureFiredCount)
    }

    @Test
    fun `cooldown prevents second gesture immediately after first`() {
        val detector = createDetector()
        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        // Complete first gesture
        repeat(3) {
            simulateSensorEvent(detector, 25f, 0f, 9.8f)
            Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)
        }
        assertEquals("First gesture should fire", 1, gestureFiredCount)

        // Immediately attempt second gesture (still in cooldown)
        repeat(5) {
            simulateSensorEvent(detector, 25f, 0f, 9.8f)
            Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)
        }
        assertEquals("Second gesture in cooldown should not fire", 1, gestureFiredCount)
    }

    @Test
    fun `isInCooldown returns true after gesture detected`() {
        val detector = createDetector()
        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        repeat(3) {
            simulateSensorEvent(detector, 25f, 0f, 9.8f)
            Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)
        }

        assertTrue("Should be in cooldown after gesture", detector.isInCooldown())
    }

    @Test
    fun `reset clears state after cooldown`() {
        val detector = createDetector()
        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        repeat(3) {
            simulateSensorEvent(detector, 25f, 0f, 9.8f)
            Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)
        }
        assertEquals(1, gestureFiredCount)

        detector.reset()
        assertFalse("After reset, should not be in cooldown", detector.isInCooldown())
    }

    @Test
    fun `threshold can be adjusted for sensitivity`() {
        val sensitiveDetector = createDetector(threshold = 5.0f)
        repeat(50) { simulateSensorEvent(sensitiveDetector, 0f, 0f, 9.8f) }

        // Send moderate shakes (8 m/s²) — below default 12.0 but above 5.0
        simulateSensorEvent(sensitiveDetector, 8f, 0f, 9.8f)
        Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)

        simulateSensorEvent(sensitiveDetector, -8f, 0f, 9.8f)
        Thread.sleep(ShakeDetector.SHAKE_MIN_INTERVAL_MS + 50)

        simulateSensorEvent(sensitiveDetector, 8f, 0f, 9.8f)

        assertEquals("Lower threshold should detect moderate shakes", 1, gestureFiredCount)
    }

    @Test
    fun `below threshold movement never counted`() {
        val detector = createDetector(threshold = 12.0f)
        repeat(50) { simulateSensorEvent(detector, 0f, 0f, 9.8f) }

        // Send accelerations of 5 m/s² — below 12.0 threshold
        repeat(100) {
            simulateSensorEvent(detector, 5f, 2f, 9.8f)
            Thread.sleep(50)
        }

        assertEquals("Sub-threshold accelerations should not trigger", 0, gestureFiredCount)
    }
}
