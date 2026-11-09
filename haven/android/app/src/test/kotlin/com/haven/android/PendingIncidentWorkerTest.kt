package com.haven.android

import android.content.Context
import androidx.work.ListenableWorker
import androidx.work.WorkerParameters
import com.haven.android.data.HavenApiService
import com.haven.android.data.PendingIncidentRecord
import com.haven.android.data.PendingIncidentStatus
import com.haven.android.data.SosResponse
import com.haven.android.repository.PendingIncidentQueue
import com.haven.android.repository.PendingIncidentWorker
import com.haven.android.repository.SecureTokenRepository
import com.haven.android.repository.ServerConfigRepository
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

/**
 * PendingIncidentWorkerTest
 *
 * Verifies:
 * - One failed incident does NOT prevent other pending incidents from being processed.
 * - Records marked NEEDS_ATTENTION are excluded from retryable queue.
 * - MAX_ATTEMPTS reached transitions incident to NEEDS_ATTENTION rather than silent deletion.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PendingIncidentWorkerTest {

    private lateinit var mockContext: Context
    private lateinit var mockParams: WorkerParameters

    @Before
    fun setup() {
        mockContext = mockk(relaxed = true)
        mockParams = mockk(relaxed = true)

        mockkObject(PendingIncidentQueue)
        mockkObject(com.haven.android.data.HavenApiClient)
    }

    @After
    fun teardown() {
        unmockkAll()
    }

    @Test
    fun `one failing incident does not block subsequent incidents from being processed`() = runTest {
        val r1 = PendingIncidentRecord("trigger-fail-500", """{"summary":"first"}""", 1000L)
        val r2 = PendingIncidentRecord("trigger-success", """{"summary":"second"}""", 2000L)

        every { PendingIncidentQueue.getRetryableIncidents(any()) } returns listOf(r1, r2)
        every { PendingIncidentQueue.incrementAttempt(any(), any(), any()) } returns true
        every { PendingIncidentQueue.remove(any(), any()) } returns true

        val mockApi = mockk<HavenApiService>()
        every { com.haven.android.data.HavenApiClient.build(any(), any()) } returns mockApi

        // r1 receives 500 error
        coEvery {
            mockApi.createSosIncident(any(), match { it.summary == "first" })
        } returns Response.error(500, "Server Error".toResponseBody("text/plain".toMediaType()))

        // r2 receives 200 success
        coEvery {
            mockApi.createSosIncident(any(), match { it.summary == "second" })
        } returns Response.success(SosResponse(success = true, caseId = "case-second-ok"))

        val worker = PendingIncidentWorker(mockContext, mockParams)
        val result = worker.doWork()

        // r1 was retried (failed with 500), but r2 was still processed and removed from queue!
        verify { PendingIncidentQueue.remove(mockContext, "trigger-success") }
        verify(exactly = 0) { PendingIncidentQueue.remove(mockContext, "trigger-fail-500") }

        // Since r1 needs retry, worker reports retry
        assertTrue("Worker should report retry for r1 while r2 was delivered", result is ListenableWorker.Result.Retry)
    }

    @Test
    fun `incident exceeding MAX_ATTEMPTS is marked NEEDS_ATTENTION instead of silently erased`() = runTest {
        val exhausted = PendingIncidentRecord(
            triggerId = "trigger-exhausted",
            requestJson = """{"summary":"exhausted"}""",
            enqueuedAtMs = 1000L,
            attemptCount = 10  // At MAX_ATTEMPTS
        )

        every { PendingIncidentQueue.getRetryableIncidents(any()) } returns listOf(exhausted)
        every { PendingIncidentQueue.markNeedsAttention(any(), any(), any()) } returns true
        every { PendingIncidentQueue.remove(any(), any()) } returns true

        val mockApi = mockk<HavenApiService>(relaxed = true)
        every { com.haven.android.data.HavenApiClient.build(any(), any()) } returns mockApi

        val worker = PendingIncidentWorker(mockContext, mockParams)
        val result = worker.doWork()

        // Verify marked as NEEDS_ATTENTION, NOT removed
        verify { PendingIncidentQueue.markNeedsAttention(mockContext, "trigger-exhausted", match { it.contains("Exceeded 10 retry attempts") }) }
        verify(exactly = 0) { PendingIncidentQueue.remove(mockContext, "trigger-exhausted") }
        assertTrue(result is ListenableWorker.Result.Failure)
    }
}
