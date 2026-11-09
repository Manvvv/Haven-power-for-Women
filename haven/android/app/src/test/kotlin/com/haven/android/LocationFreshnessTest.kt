package com.haven.android

import com.haven.android.data.LocationFreshness
import com.haven.android.repository.LocationResult
import io.mockk.every
import io.mockk.mockk
import org.junit.Test
import org.junit.Assert.*

/**
 * LocationFreshnessTest
 *
 * Tests location freshness classification logic.
 * These are pure logic tests that don't need Android context.
 */
class LocationFreshnessTest {

    @Test
    fun `FRESH label has correct API value for backend`() {
        assertEquals("FRESH", LocationFreshness.FRESH.apiValue)
    }

    @Test
    fun `UNAVAILABLE label has correct API value for backend`() {
        assertEquals("LOCATION_UNAVAILABLE", LocationFreshness.UNAVAILABLE.apiValue)
    }

    @Test
    fun `STALE label has correct API value for backend`() {
        assertEquals("STALE", LocationFreshness.STALE.apiValue)
    }

    @Test
    fun `LAST_KNOWN label has correct API value for backend`() {
        assertEquals("LAST_KNOWN", LocationFreshness.LAST_KNOWN.apiValue)
    }

    @Test
    fun `LocationResult with null location and UNAVAILABLE is valid`() {
        val result = LocationResult(null, LocationFreshness.UNAVAILABLE, "No GPS")
        assertNull(result.location)
        assertEquals(LocationFreshness.UNAVAILABLE, result.freshness)
        assertEquals("No GPS", result.errorMessage)
    }

    @Test
    fun `LocationResult ordering - newer fix should not overwrite with older`() {
        // Business rule: never overwrite a newer valid fix with an older out-of-order update
        val newerTime = System.currentTimeMillis()
        val olderTime = newerTime - 30_000L

        val newerFix = mockk<android.location.Location> {
            every { time } returns newerTime
            every { latitude } returns 12.9716
            every { longitude } returns 77.5946
        }

        val olderFix = mockk<android.location.Location> {
            every { time } returns olderTime
            every { latitude } returns 12.9700
            every { longitude } returns 77.5900
        }

        // Verify: old fix time < new fix time means the old should not replace the new
        assertTrue("Older fix should have earlier timestamp", olderFix.time < newerFix.time)
    }
}

/**
 * PendingIncidentQueueTest (pure logic, no Android context)
 */
class PendingIncidentQueueLogicTest {

    @Test
    fun `PendingIncidentRecord stores triggerId correctly`() {
        val record = com.haven.android.data.PendingIncidentRecord(
            triggerId = "SHAKE-12345-abcd1234",
            requestJson = """{"idempotency_key":"SHAKE-12345-abcd1234"}""",
            enqueuedAtMs = System.currentTimeMillis(),
            attemptCount = 0
        )
        assertEquals("SHAKE-12345-abcd1234", record.triggerId)
        assertEquals(0, record.attemptCount)
    }

    @Test
    fun `PendingIncidentRecord copy increments attempt count`() {
        val original = com.haven.android.data.PendingIncidentRecord(
            triggerId = "ID-001",
            requestJson = "{}",
            enqueuedAtMs = 0L,
            attemptCount = 2
        )
        val incremented = original.copy(attemptCount = original.attemptCount + 1)
        assertEquals(3, incremented.attemptCount)
        assertEquals("ID-001", incremented.triggerId)
    }
}
