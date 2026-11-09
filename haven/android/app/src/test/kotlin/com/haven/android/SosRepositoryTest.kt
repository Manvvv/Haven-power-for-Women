package com.haven.android

import com.haven.android.data.*
import com.haven.android.repository.*
import io.mockk.*
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.Assert.*
import retrofit2.Response

/**
 * SosRepositoryTest
 *
 * Comprehensive unit tests for write-ahead durable persistence, commit failures,
 * capacity boundaries, SOS submission, offline queuing, error state machine,
 * and 401 emergency fallback.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class SosRepositoryTest {

    private lateinit var mockApiService: HavenApiService
    private lateinit var mockTokenRepo: SecureTokenRepository

    @Before
    fun setup() {
        mockApiService = mockk()
        mockTokenRepo = mockk()

        every { mockTokenRepo.getBearerHeader() } returns "Bearer test_token_xyz"
        every { mockTokenRepo.getUserId() } returns "user_123"
        every { mockTokenRepo.isAuthenticated() } returns true

        // Mock PendingIncidentQueue for write-ahead durable queuing verification
        mockkObject(PendingIncidentQueue)
        every { PendingIncidentQueue.enqueue(any(), any()) } returns PendingIncidentQueue.EnqueueResult.Success
        every { PendingIncidentQueue.remove(any(), any()) } returns true
        every { PendingIncidentQueue.markNeedsAttention(any(), any(), any()) } returns true
    }

    @After
    fun teardown() {
        unmockkAll()
    }

    private fun createRepo(context: android.content.Context = mockk(relaxed = true)): SosRepository {
        return SosRepository(context, mockApiService, mockTokenRepo)
    }

    @Test
    fun `successful API call returns Success result and removes from queue`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)
        val expectedCaseId = "HAVEN-1234567890-abc123"

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.success(SosResponse(success = true, caseId = expectedCaseId))

        val locationResult = LocationResult(
            location = mockk {
                every { latitude } returns 12.9716
                every { longitude } returns 77.5946
                every { accuracy } returns 8f
                every { time } returns System.currentTimeMillis()
            },
            freshness = LocationFreshness.FRESH
        )

        val result = repo.submitSosIncident("trigger-001", locationResult, isTest = false)

        assertTrue("Result should be Success", result is SosRepository.SosResult.Success)
        val success = result as SosRepository.SosResult.Success
        assertEquals(expectedCaseId, success.caseId)
        assertFalse(success.localPersistenceFailed)
        // Verify write-ahead logging: enqueued before send, removed after confirmed success
        verify { PendingIncidentQueue.enqueue(any(), any()) }
        verify { PendingIncidentQueue.remove(any(), "trigger-001") }
    }

    @Test
    fun `server 500 error queues incident for retry when persisted`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(500, "Internal Server Error".toResponseBody("text/plain".toMediaType()))

        val result = repo.submitSosIncident("trigger-002", null, isTest = false)

        assertTrue("5xx should queue incident", result is SosRepository.SosResult.Queued)
        verify { PendingIncidentQueue.enqueue(any(), any()) }
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "trigger-002") }
    }

    @Test
    fun `network exception queues incident for retry when persisted`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } throws java.io.IOException("No network")

        val result = repo.submitSosIncident("trigger-003", null, isTest = false)

        assertTrue("Network failure should queue incident", result is SosRepository.SosResult.Queued)
        verify { PendingIncidentQueue.enqueue(any(), any()) }
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "trigger-003") }
    }

    @Test
    fun `socket timeout exception queues incident for retry when persisted`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } throws java.net.SocketTimeoutException("Read timed out")

        val result = repo.submitSosIncident("trigger-timeout", null, isTest = false)

        assertTrue("Socket timeout should queue incident", result is SosRepository.SosResult.Queued)
        verify { PendingIncidentQueue.enqueue(any(), any()) }
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "trigger-timeout") }
    }

    @Test
    fun `HTTP 408 Request Timeout retains incident in queue for retry`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(408, "Request Timeout".toResponseBody("text/plain".toMediaType()))

        val result = repo.submitSosIncident("trigger-408", null, isTest = false)

        assertTrue("408 should queue incident", result is SosRepository.SosResult.Queued)
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "trigger-408") }
    }

    @Test
    fun `HTTP 429 Rate Limit retains incident in queue for retry`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(429, "Too Many Requests".toResponseBody("text/plain".toMediaType()))

        val result = repo.submitSosIncident("trigger-429", null, isTest = false)

        assertTrue("429 should queue incident", result is SosRepository.SosResult.Queued)
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "trigger-429") }
    }

    @Test
    fun `write-ahead persistence failure still proceeds with network transit and flags localPersistenceFailed`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        every { PendingIncidentQueue.enqueue(any(), any()) } returns PendingIncidentQueue.EnqueueResult.StorageFailure("Disk full")
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.success(SosResponse(success = true, caseId = "case-pwf"))

        val result = repo.submitSosIncident("trigger-pwf", null, isTest = false)

        assertTrue("Even if persistence fails, network transit success returns Success", result is SosRepository.SosResult.Success)
        val success = result as SosRepository.SosResult.Success
        assertEquals("case-pwf", success.caseId)
        assertTrue("localPersistenceFailed must be true", success.localPersistenceFailed)
        coVerify(exactly = 1) { mockApiService.triggerShakeSos(any(), any()) }
    }

    @Test
    fun `CRITICAL INVARIANT network failure after persistence failure returns UnpersistedEmergencyFailure NOT Queued`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        every { PendingIncidentQueue.enqueue(any(), any()) } returns PendingIncidentQueue.EnqueueResult.StorageFailure("Flash storage I/O commit failed")
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } throws java.io.IOException("Airplane mode active")

        val result = repo.submitSosIncident("trigger-unpersisted-network-fail", null, isTest = false)

        // INVARIANT VERIFICATION:
        // Must NOT return SosResult.Queued (which would falsely imply safe offline storage)!
        assertFalse("Must NOT claim Queued when persistence failed", result is SosRepository.SosResult.Queued)
        assertTrue("Must return UnpersistedEmergencyFailure", result is SosRepository.SosResult.UnpersistedEmergencyFailure)

        val unpersisted = result as SosRepository.SosResult.UnpersistedEmergencyFailure
        assertEquals("trigger-unpersisted-network-fail", unpersisted.triggerId)
        assertTrue("Must identify storage reason", unpersisted.storageReason.contains("Flash storage I/O commit failed"))
        assertTrue("Must identify network error", unpersisted.networkError.contains("Airplane mode active"))
    }

    @Test
    fun `queue capacity reached attempts immediate delivery and reports localPersistenceFailed if success`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        every { PendingIncidentQueue.enqueue(any(), any()) } returns PendingIncidentQueue.EnqueueResult.CapacityExceeded(100, 100)
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.success(SosResponse(success = true, caseId = "case-cap-ok"))

        val result = repo.submitSosIncident("trigger-cap-ok", null, isTest = false)

        assertTrue(result is SosRepository.SosResult.Success)
        val success = result as SosRepository.SosResult.Success
        assertTrue("localPersistenceFailed must be true when capacity was exceeded", success.localPersistenceFailed)
    }

    @Test
    fun `HTTP 409 confirmed duplicate removes from queue and returns duplicate Success`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val duplicateBody = """{"detail": "Incident already recorded for trigger-409", "duplicate": true}"""
        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(409, duplicateBody.toResponseBody("application/json".toMediaType()))

        val result = repo.submitSosIncident("trigger-409", null, isTest = false)

        assertTrue("Confirmed 409 should be treated as duplicate Success", result is SosRepository.SosResult.Success)
        assertTrue("Duplicate flag should be set", (result as SosRepository.SosResult.Success).isDuplicate)
        verify { PendingIncidentQueue.remove(any(), "trigger-409") }
    }

    @Test
    fun `HTTP 409 unconfirmed conflict does not remove from queue and marks NEEDS_ATTENTION`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val unconfirmedConflict = """{"detail": "State conflict on resource 88"}"""
        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(409, unconfirmedConflict.toResponseBody("application/json".toMediaType()))

        val result = repo.submitSosIncident("trigger-409-unconf", null, isTest = false)

        assertTrue("Unconfirmed 409 should return Failure", result is SosRepository.SosResult.Failure)
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "trigger-409-unconf") }
        verify { PendingIncidentQueue.markNeedsAttention(any(), "trigger-409-unconf", any()) }
    }

    @Test
    fun `HTTP 401 attempts emergency unauthenticated fallback and succeeds on confirmed case_id`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(401, "Unauthorized".toResponseBody("text/plain".toMediaType()))

        coEvery {
            mockApiService.createSosIncident(null, any())
        } returns Response.success(SosResponse(success = true, caseId = "fallback-case-99"))

        val result = repo.submitSosIncident("trigger-401-success", null, isTest = false)

        assertTrue("Fallback should succeed", result is SosRepository.SosResult.Success)
        assertEquals("fallback-case-99", (result as SosRepository.SosResult.Success).caseId)
        coVerify(exactly = 1) { mockApiService.createSosIncident(null, any()) }
        verify { PendingIncidentQueue.remove(any(), "trigger-401-success") }
    }

    @Test
    fun `HTTP 401 unauthenticated fallback without valid case_id does NOT report success`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(401, "Unauthorized".toResponseBody("text/plain".toMediaType()))

        coEvery {
            mockApiService.createSosIncident(null, any())
        } returns Response.success(SosResponse(success = false, caseId = null))

        val result = repo.submitSosIncident("trigger-401-no-case", null, isTest = false)

        assertTrue("Fallback without caseId must return Failure", result is SosRepository.SosResult.Failure)
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "trigger-401-no-case") }
    }

    @Test
    fun `HTTP 401 with transient fallback failure retains incident in queue for retry when persisted`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(401, "Unauthorized".toResponseBody("text/plain".toMediaType()))

        coEvery {
            mockApiService.createSosIncident(null, any())
        } returns Response.error(503, "Service Unavailable".toResponseBody("text/plain".toMediaType()))

        val result = repo.submitSosIncident("trigger-401-transient", null, isTest = false)

        assertTrue("Transient fallback error should keep incident queued", result is SosRepository.SosResult.Queued)
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "trigger-401-transient") }
    }

    @Test
    fun `HTTP 422 permanent error marks NEEDS_ATTENTION and never silently erases incident`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val valError = """{"detail": "Missing required field 'summary'"}"""
        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(422, valError.toResponseBody("application/json".toMediaType()))

        val result = repo.submitSosIncident("PERM-422", null, isTest = false)

        assertTrue("422 should return Failure", result is SosRepository.SosResult.Failure)
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "PERM-422") }
        verify { PendingIncidentQueue.markNeedsAttention(any(), "PERM-422", any()) }
    }

    @Test
    fun `HTTP 403 authorization error marks NEEDS_ATTENTION and never silently erases incident`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val authError = """{"detail": "Client certificate or IP forbidden"}"""
        coEvery {
            mockApiService.triggerShakeSos(any(), any())
        } returns Response.error(403, authError.toResponseBody("application/json".toMediaType()))

        val result = repo.submitSosIncident("PERM-403", null, isTest = false)

        assertTrue("403 should return Failure", result is SosRepository.SosResult.Failure)
        verify(exactly = 0) { PendingIncidentQueue.remove(any(), "PERM-403") }
        verify { PendingIncidentQueue.markNeedsAttention(any(), "PERM-403", any()) }
    }

    @Test
    fun `UNAVAILABLE location is excluded from request coordinates`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val capturedRequest = slot<ShakeSosRequest>()
        coEvery {
            mockApiService.triggerShakeSos(any(), capture(capturedRequest))
        } returns Response.success(SosResponse(success = true, caseId = "test-case"))

        val locationResult = LocationResult(null, LocationFreshness.UNAVAILABLE, "No GPS")

        repo.submitSosIncident("trigger-004", locationResult, isTest = false)

        assertNull("Unavailable location should have null latitude", capturedRequest.captured.latitude)
        assertNull("Unavailable location should have null longitude", capturedRequest.captured.longitude)
        assertEquals("Freshness should be LOCATION_UNAVAILABLE",
                     LocationFreshness.UNAVAILABLE.apiValue,
                     capturedRequest.captured.locationFreshness)
    }

    @Test
    fun `STALE location is labelled correctly in request`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val capturedRequest = slot<ShakeSosRequest>()
        coEvery {
            mockApiService.triggerShakeSos(any(), capture(capturedRequest))
        } returns Response.success(SosResponse(success = true, caseId = "stale-case"))

        val staleLocation = LocationResult(
            location = mockk {
                every { latitude } returns 28.6139
                every { longitude } returns 77.2090
                every { accuracy } returns 50f
                every { time } returns System.currentTimeMillis() - 120_000L  // 2 min old
            },
            freshness = LocationFreshness.STALE
        )

        repo.submitSosIncident("trigger-005", staleLocation, isTest = false)

        assertEquals("Stale location must be labelled STALE",
                     LocationFreshness.STALE.apiValue,
                     capturedRequest.captured.locationFreshness)
        assertNotNull("Stale location should still include coordinates",
                      capturedRequest.captured.latitude)
    }

    @Test
    fun `idempotency key is always included in request`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val capturedRequest = slot<ShakeSosRequest>()
        coEvery {
            mockApiService.triggerShakeSos(any(), capture(capturedRequest))
        } returns Response.success(SosResponse(success = true, caseId = "idem-case"))

        val triggerId = "SHAKE-1234567890-abcdefgh"
        repo.submitSosIncident(triggerId, null, isTest = false)

        assertEquals("Idempotency key must match triggerId",
                     triggerId,
                     capturedRequest.captured.idempotencyKey)
    }

    @Test
    fun `test mode uses test severity and does not mark immediate danger`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val capturedRequest = slot<ShakeSosRequest>()
        coEvery {
            mockApiService.triggerShakeSos(any(), capture(capturedRequest))
        } returns Response.success(SosResponse(success = true, caseId = "test-case"))

        repo.submitSosIncident("TEST-001", null, isTest = true)

        assertEquals("Test severity should be 'test'", "test", capturedRequest.captured.severity)
        assertFalse("Test should not mark immediate danger", capturedRequest.captured.immediateDanger)
        assertTrue("Test trigger type should contain TEST",
                   capturedRequest.captured.triggerType.contains("TEST"))
    }

    @Test
    fun `real SOS uses critical severity and immediate danger`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val capturedRequest = slot<ShakeSosRequest>()
        coEvery {
            mockApiService.triggerShakeSos(any(), capture(capturedRequest))
        } returns Response.success(SosResponse(success = true, caseId = "real-case"))

        repo.submitSosIncident("SHAKE-001", null, isTest = false)

        assertEquals("Real SOS severity should be 'critical'", "critical", capturedRequest.captured.severity)
        assertTrue("Real SOS should mark immediate danger", capturedRequest.captured.immediateDanger)
    }

    @Test
    fun `auth header is included when token available`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        val repo = createRepo(mockContext)

        val capturedHeader = slot<String>()
        coEvery {
            mockApiService.triggerShakeSos(capture(capturedHeader), any())
        } returns Response.success(SosResponse(success = true, caseId = "auth-case"))

        repo.submitSosIncident("AUTH-001", null, isTest = false)

        assertEquals("Bearer token should be in auth header",
                     "Bearer test_token_xyz",
                     capturedHeader.captured)
    }

    @Test
    fun `unauthenticated submission falls back to createSosIncident`() = runTest {
        val mockContext = mockk<android.content.Context>(relaxed = true)
        every { mockTokenRepo.getBearerHeader() } returns null
        val repo = createRepo(mockContext)

        coEvery {
            mockApiService.createSosIncident(null, any())
        } returns Response.success(SosResponse(success = true, caseId = "unauth-case"))

        val result = repo.submitSosIncident("UNAUTH-001", null, isTest = false)

        assertTrue("Unauthenticated submission should succeed via fallback", result is SosRepository.SosResult.Success)
        coVerify(exactly = 1) { mockApiService.createSosIncident(null, any()) }
    }
}
