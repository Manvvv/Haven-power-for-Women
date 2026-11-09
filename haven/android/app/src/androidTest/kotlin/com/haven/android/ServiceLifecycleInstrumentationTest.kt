package com.haven.android

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.Assert.*

/**
 * ServiceLifecycleInstrumentationTest
 *
 * Android instrumentation tests for ShakeDetectionService lifecycle.
 * These run on a real device or emulator (androidTest).
 *
 * Verifiable states:
 *   A. Service starts and MonitoringStatusRepository reflects serviceRunning=true
 *   B. Service stop sets serviceRunning=false
 *   C. Encrypted token storage works on-device
 *   D. PendingIncidentQueue survives process restart (encrypted prefs persisted)
 *
 * States NOT verifiable in instrumentation (require physical acceptance testing):
 *   - Shake detection with screen locked (sensor fires on hardware)
 *   - OEM battery-saver killing the service (OEM-specific behaviour)
 *   - Force-stop recovery (impossible to automate: force-stop kills the test runner)
 */
@RunWith(AndroidJUnit4::class)
class ServiceLifecycleInstrumentationTest {

    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun `application context is correct`() {
        assertEquals("com.haven.android.debug", context.packageName)
    }

    @Test
    fun `EncryptedSharedPreferences can be created on device`() {
        val tokenRepo = com.haven.android.repository.SecureTokenRepository(context)
        // Should not throw
        assertNull("Fresh install should have no token", tokenRepo.getAccessToken())
    }

    @Test
    fun `PendingIncidentQueue enqueue and remove works on device`() {
        val queue = com.haven.android.repository.PendingIncidentQueue
        val record = com.haven.android.data.PendingIncidentRecord(
            triggerId = "TEST-INSTR-001",
            requestJson = """{"idempotency_key":"TEST-INSTR-001","trigger_type":"SHAKE_SOS_TEST"}""",
            enqueuedAtMs = System.currentTimeMillis(),
            attemptCount = 0
        )

        // Enqueue
        queue.enqueue(context, record)
        val pending = queue.getAll(context)
        assertTrue("Record should be in queue", pending.any { it.triggerId == "TEST-INSTR-001" })

        // Remove
        queue.remove(context, "TEST-INSTR-001")
        val afterRemove = queue.getAll(context)
        assertFalse("Record should be removed", afterRemove.any { it.triggerId == "TEST-INSTR-001" })
    }

    @Test
    fun `duplicate enqueue is idempotent`() {
        val queue = com.haven.android.repository.PendingIncidentQueue
        val record = com.haven.android.data.PendingIncidentRecord(
            triggerId = "TEST-INSTR-DUP",
            requestJson = "{}",
            enqueuedAtMs = System.currentTimeMillis()
        )

        queue.enqueue(context, record)
        queue.enqueue(context, record)  // second enqueue of same triggerId

        val all = queue.getAll(context).filter { it.triggerId == "TEST-INSTR-DUP" }
        assertEquals("Duplicate enqueue should not add twice", 1, all.size)

        // Cleanup
        queue.remove(context, "TEST-INSTR-DUP")
    }

    @Test
    fun `MonitoringStatusRepository datastore writes and reads correctly`() {
        val repo = com.haven.android.repository.MonitoringStatusRepository(context)
        kotlinx.coroutines.runBlocking {
            repo.setUserEnabled(true)
            repo.setServiceRunning(true)
            repo.updateHeartbeat()

            // Read back via flow (take first emission)
            val status = repo.statusFlow.first()
            assertTrue("userEnabled should be true", status.userEnabled)
            // serviceRunning may be false immediately due to heartbeat-stale logic
            // — the heartbeat was just written so it should be fresh
            assertTrue("serviceRunning should be true after fresh heartbeat", status.serviceRunning)

            // Cleanup
            repo.setUserEnabled(false)
            repo.setServiceRunning(false)
        }
    }
}
