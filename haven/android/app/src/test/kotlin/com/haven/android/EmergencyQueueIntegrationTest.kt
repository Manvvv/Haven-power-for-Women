package com.haven.android

import android.content.Context
import android.content.SharedPreferences
import com.haven.android.data.*
import com.haven.android.repository.*
import io.mockk.*
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import retrofit2.Response
import java.io.File
import java.io.IOException

/**
 * EmergencyQueueIntegrationTest
 *
 * High-assurance test suite for exact edge-case scenarios:
 *
 * TASK 1: QUEUE FULL + NETWORK FAILURE
 * 1. Insert 100 pending incidents.
 * 2. Confirm all 100 records are present.
 * 3. Trigger incident 101.
 * 4. Confirm CapacityExceeded is returned.
 * 5. Confirm the existing 100 incidents remain completely unchanged.
 * 6. Simulate successful network transmission for incident 101 -> acknowledged with localPersistenceFailed=true.
 * 7. Simulate failed network transmission for incident 101 -> explicit UnpersistedEmergencyFailure, NEVER Queued.
 *
 * TASK 2: STORAGE FAILURE SCENARIOS
 * 1. Disk full / commit() == false: network delivery still attempted immediately.
 * 2. Storage failure visible in storageErrorState (consumed by MonitorTab).
 * 3. Network failure during storage failure returns UnpersistedEmergencyFailure.
 * 4. Keystore/storage unavailable returns StorageFailure while network attempt proceeds.
 * 5. Corrupted encrypted storage recovery: backup preserved, error cleared.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class EmergencyQueueIntegrationTest {

    private lateinit var mockContext: Context
    private lateinit var mockPrefs: SharedPreferences
    private lateinit var mockEditor: SharedPreferences.Editor
    private lateinit var mockApiService: HavenApiService
    private lateinit var mockTokenRepo: SecureTokenRepository
    private val memoryStore = mutableMapOf<String, String>()

    @Before
    fun setup() {
        mockContext = mockk(relaxed = true)
        mockPrefs = mockk(relaxed = true)
        mockEditor = mockk(relaxed = true)
        mockApiService = mockk()
        mockTokenRepo = mockk()

        memoryStore.clear()

        every { mockTokenRepo.getBearerHeader() } returns "Bearer valid_jwt_token"
        every { mockTokenRepo.getUserId() } returns "user_safe_99"
        every { mockTokenRepo.isAuthenticated() } returns true

        every { mockPrefs.getString("pending_incidents", null) } answers {
            memoryStore["pending_incidents"]
        }
        every { mockEditor.putString("pending_incidents", any()) } answers {
            val value = secondArg<String>()
            memoryStore["pending_incidents"] = value
            mockEditor
        }
        every { mockEditor.remove(any()) } answers {
            val key = firstArg<String>()
            memoryStore.remove(key)
            mockEditor
        }
        every { mockEditor.commit() } returns true
        every { mockPrefs.edit() } returns mockEditor

        PendingIncidentQueue.testPrefs = mockPrefs
    }

    @After
    fun teardown() {
        PendingIncidentQueue.testPrefs = null
        unmockkAll()
    }

    private fun createRepo(): SosRepository {
        return SosRepository(mockContext, mockApiService, mockTokenRepo)
    }

    // ─────────────────────────────────────────────────────────────────────────
    // TASK 1: EXACT SCENARIO VERIFICATION
    // ─────────────────────────────────────────────────────────────────────────

    @Test
    fun `TASK 1 - Queue full followed by network SUCCESS for incident 101`() = runTest {
        val repo = createRepo()

        // 1. Insert 100 pending incidents
        for (i in 1..100) {
            val rec = PendingIncidentRecord("trigger-$i", """{"seq": $i}""", i * 1000L)
            val res = PendingIncidentQueue.enqueue(mockContext, rec)
            assertTrue("Item $i must be successfully enqueued", res is PendingIncidentQueue.EnqueueResult.Success)
        }

        // 2. Confirm all 100 records are present
        val all100 = PendingIncidentQueue.getAll(mockContext)
        assertEquals(100, all100.size)
        assertEquals("trigger-1", all100.first().triggerId)
        assertEquals("trigger-100", all100.last().triggerId)

        // 3 & 4. Trigger incident 101 -> direct queue call returns CapacityExceeded
        val dummy101 = PendingIncidentRecord("trigger-101", """{"seq": 101}""", 101000L)
        val capResult = PendingIncidentQueue.enqueue(mockContext, dummy101)
        assertTrue("Queue must return CapacityExceeded for 101st item", capResult is PendingIncidentQueue.EnqueueResult.CapacityExceeded)
        assertEquals(100, (capResult as PendingIncidentQueue.EnqueueResult.CapacityExceeded).currentSize)

        // 5. Confirm existing 100 incidents remain unchanged
        val afterCheck = PendingIncidentQueue.getAll(mockContext)
        assertEquals(100, afterCheck.size)
        assertEquals("trigger-1", afterCheck.first().triggerId)
        assertFalse("trigger-101 must not be inserted", afterCheck.any { it.triggerId == "trigger-101" })

        // 6. Simulate successful network transmission for incident 101
        coEvery {
            mockApiService.triggerShakeSos(any(), match { it.idempotencyKey == "trigger-101" })
        } returns Response.success(SosResponse(success = true, caseId = "HAVEN-CASE-101-DELIVERED"))

        val result101 = repo.submitSosIncident("trigger-101", null, isTest = false)

        // REQUIRED RESULT:
        // - Existing 100 incidents are NEVER deleted
        val afterSuccess = PendingIncidentQueue.getAll(mockContext)
        assertEquals("All 100 original incidents must remain intact in queue", 100, afterSuccess.size)
        assertEquals("trigger-1", afterSuccess.first().triggerId)
        // - Successfully delivered incident 101 is acknowledged
        assertTrue("Incident 101 must return Success", result101 is SosRepository.SosResult.Success)
        val success = result101 as SosRepository.SosResult.Success
        assertEquals("HAVEN-CASE-101-DELIVERED", success.caseId)
        assertTrue("Must flag localPersistenceFailed=true because queue was full", success.localPersistenceFailed)
    }

    @Test
    fun `TASK 1 - Queue full followed by network FAILURE for incident 101 produces UnpersistedEmergencyFailure`() = runTest {
        val repo = createRepo()

        // 1. Insert 100 pending incidents
        for (i in 1..100) {
            val rec = PendingIncidentRecord("trigger-$i", """{"seq": $i}""", i * 1000L)
            PendingIncidentQueue.enqueue(mockContext, rec)
        }

        // 2. Confirm all 100 records are present
        assertEquals(100, PendingIncidentQueue.getAll(mockContext).size)

        // 6 & 7. Simulate failed network transmission for incident 101 (e.g. timeout / no signal)
        coEvery {
            mockApiService.triggerShakeSos(any(), match { it.idempotencyKey == "trigger-101" })
        } throws IOException("Cellular connection timed out in basement")

        val result101 = repo.submitSosIncident("trigger-101", null, isTest = false)

        // REQUIRED RESULT:
        // - Existing 100 incidents are never deleted
        val remaining = PendingIncidentQueue.getAll(mockContext)
        assertEquals(100, remaining.size)
        assertEquals("trigger-1", remaining.first().triggerId)
        assertEquals("trigger-100", remaining.last().triggerId)

        // - Failed incident 101 is NEVER reported as successfully queued!
        assertFalse("CRITICAL SAFETY INVARIANT: Must NOT report Queued when persistence failed!",
            result101 is SosRepository.SosResult.Queued)
        assertFalse("Must NOT report Success when network failed",
            result101 is SosRepository.SosResult.Success)

        // - Failed incident 101 produces an explicit UnpersistedEmergencyFailure
        assertTrue("Must return explicit UnpersistedEmergencyFailure",
            result101 is SosRepository.SosResult.UnpersistedEmergencyFailure)

        val unpersisted = result101 as SosRepository.SosResult.UnpersistedEmergencyFailure
        assertEquals("trigger-101", unpersisted.triggerId)
        assertTrue("Storage reason must note capacity limit",
            unpersisted.storageReason.contains("Queue capacity reached (100/100)"))
        assertTrue("Network error must capture cellular failure",
            unpersisted.networkError.contains("Cellular connection timed out in basement"))

        // - Storage error state is surfaced
        assertNotNull("Storage error state must be visible in StateFlow",
            PendingIncidentQueue.storageErrorState.value)
    }

    // ─────────────────────────────────────────────────────────────────────────
    // TASK 2: STORAGE FAILURE SCENARIOS
    // ─────────────────────────────────────────────────────────────────────────

    @Test
    fun `TASK 2 - Disk full or commit returning false attempts immediate network delivery and reports Success`() = runTest {
        val repo = createRepo()

        // Simulate disk full / flash I/O failure
        every { mockEditor.commit() } returns false

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.success(SosResponse(success = true, caseId = "HAVEN-DISK-FULL-SAVED"))

        val result = repo.submitSosIncident("trigger-disk-full-network-ok", null, isTest = false)

        // Immediate network delivery succeeded despite disk commit returning false
        assertTrue(result is SosRepository.SosResult.Success)
        val success = result as SosRepository.SosResult.Success
        assertEquals("HAVEN-DISK-FULL-SAVED", success.caseId)
        assertTrue("localPersistenceFailed must be true when commit() fails", success.localPersistenceFailed)
        assertNotNull("Storage failure reason must be visible in storageErrorState",
            PendingIncidentQueue.storageErrorState.value)
        assertTrue(PendingIncidentQueue.storageErrorState.value!!.contains("Disk commit failed"))
    }

    @Test
    fun `TASK 2 - Disk full with network failure yields UnpersistedEmergencyFailure NOT Queued`() = runTest {
        val repo = createRepo()

        // Simulate disk full / flash I/O failure
        every { mockEditor.commit() } returns false

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } throws IOException("No route to host")

        val result = repo.submitSosIncident("trigger-double-fault", null, isTest = false)

        assertFalse("Must NEVER report Queued when disk write failed", result is SosRepository.SosResult.Queued)
        assertTrue("Must report UnpersistedEmergencyFailure", result is SosRepository.SosResult.UnpersistedEmergencyFailure)
        val fail = result as SosRepository.SosResult.UnpersistedEmergencyFailure
        assertEquals("trigger-double-fault", fail.triggerId)
        assertTrue(fail.storageReason.contains("Disk commit failed"))
        assertTrue(fail.networkError.contains("No route to host"))
    }

    @Test
    fun `TASK 2 - Keystore or storage unavailable attempts network delivery immediately`() = runTest {
        // Point testPrefs to null to simulate total Keystore / crypto subsystem failure
        PendingIncidentQueue.testPrefs = null
        val repo = createRepo()

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.success(SosResponse(success = true, caseId = "HAVEN-NO-KEYSTORE-OK"))

        val result = repo.submitSosIncident("trigger-keystore-down", null, isTest = false)

        assertTrue("Should still succeed over network if available", result is SosRepository.SosResult.Success)
        val success = result as SosRepository.SosResult.Success
        assertEquals("HAVEN-NO-KEYSTORE-OK", success.caseId)
        assertTrue(success.localPersistenceFailed)
    }

    @Test
    fun `TASK 2 - Corrupted storage reset creates backup file and clears error state`() {
        val tempDir = File(System.getProperty("java.io.tmpdir"), "haven_test_dir_${System.currentTimeMillis()}")
        tempDir.mkdirs()
        val filesDir = File(tempDir, "files").apply { mkdirs() }
        val sharedPrefsDir = File(tempDir, "shared_prefs").apply { mkdirs() }
        val corruptXml = File(sharedPrefsDir, "haven_pending_queue.xml").apply {
            writeText("CORRUPTED_NON_XML_BYTES_GARBAGE")
        }

        every { mockContext.filesDir } returns filesDir

        // Reset corrupted storage
        val resetResult = PendingIncidentQueue.resetCorruptedStorage(mockContext)

        // Corrupted file was deleted
        assertFalse("Original corrupt XML file must be deleted", corruptXml.exists())

        // Backup file was created in filesDir
        val backups = filesDir.listFiles { _, name -> name.startsWith("haven_pending_queue.corrupt.") }
        assertNotNull(backups)
        assertTrue("A backup file must be created with timestamp", backups!!.isNotEmpty())
        assertEquals("CORRUPTED_NON_XML_BYTES_GARBAGE", backups[0].readText())

        // Error state cleared
        assertNull("Storage error state must be cleared after reset",
            PendingIncidentQueue.storageErrorState.value)

        // Cleanup tempDir
        tempDir.deleteRecursively()
    }

    // ─────────────────────────────────────────────────────────────────────────
    // TASK 3: MULTI-RECORD INDEPENDENCE
    // ─────────────────────────────────────────────────────────────────────────

    @Test
    fun `TASK 3 - Multiple pending records handled independently without cascade failures`() {
        val r1 = PendingIncidentRecord("trigger-1", """{"summary":"one"}""", 1000L)
        val r2 = PendingIncidentRecord("trigger-2", """{"summary":"two"}""", 2000L)
        val r3 = PendingIncidentRecord("trigger-3", """{"summary":"three"}""", 3000L)

        PendingIncidentQueue.enqueue(mockContext, r1)
        PendingIncidentQueue.enqueue(mockContext, r2)
        PendingIncidentQueue.enqueue(mockContext, r3)

        assertEquals(3, PendingIncidentQueue.getAll(mockContext).size)

        // Mark trigger-2 as NEEDS_ATTENTION (e.g. HTTP 422 error)
        PendingIncidentQueue.markNeedsAttention(mockContext, "trigger-2", "HTTP 422: Invalid location coordinates")

        // Only trigger-1 and trigger-3 are retryable
        val retryable = PendingIncidentQueue.getRetryableIncidents(mockContext)
        assertEquals(2, retryable.size)
        assertEquals("trigger-1", retryable[0].triggerId)
        assertEquals("trigger-3", retryable[1].triggerId)

        // Remove trigger-1 upon delivery
        PendingIncidentQueue.remove(mockContext, "trigger-1")

        val remaining = PendingIncidentQueue.getAll(mockContext)
        assertEquals(2, remaining.size)
        // trigger-2 is preserved in NEEDS_ATTENTION
        assertEquals("trigger-2", remaining[0].triggerId)
        assertEquals(PendingIncidentStatus.NEEDS_ATTENTION, remaining[0].status)
        // trigger-3 is preserved in PENDING
        assertEquals("trigger-3", remaining[1].triggerId)
        assertEquals(PendingIncidentStatus.PENDING, remaining[1].status)
    }
}
