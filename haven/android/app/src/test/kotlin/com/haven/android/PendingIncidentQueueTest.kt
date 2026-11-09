package com.haven.android

import android.content.Context
import android.content.SharedPreferences
import com.haven.android.data.PendingIncidentRecord
import com.haven.android.data.PendingIncidentStatus
import com.haven.android.repository.PendingIncidentQueue
import io.mockk.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/**
 * PendingIncidentQueueTest
 *
 * Verifies strict data integrity and queue behavior:
 * 1. Queue at maximum capacity
 * 2. Existing emergencies are never automatically removed
 * 3. New incident persistence at capacity returns CapacityExceeded
 * 4. Persistence commit failure returns StorageFailure
 * 5. Multiple pending incidents stored and tracked independently
 * 6. Deduplication on idempotency key (triggerId)
 * 7. Storage corruption and storage unavailable states
 * 8. Status transitions (PENDING, RETRYING, NEEDS_ATTENTION)
 */
class PendingIncidentQueueTest {

    private lateinit var mockContext: Context
    private lateinit var mockPrefs: SharedPreferences
    private lateinit var mockEditor: SharedPreferences.Editor
    private val memoryStore = mutableMapOf<String, String>()

    @Before
    fun setup() {
        mockContext = mockk(relaxed = true)
        mockPrefs = mockk(relaxed = true)
        mockEditor = mockk(relaxed = true)

        memoryStore.clear()

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

    @Test
    fun `1 & 2 & 3 Queue at maximum capacity NEVER deletes older emergencies and returns CapacityExceeded`() {
        // Fill queue to MAX_PENDING (100)
        for (i in 1..PendingIncidentQueue.MAX_PENDING) {
            val record = PendingIncidentRecord(
                triggerId = "trigger-$i",
                requestJson = """{"seq": $i}""",
                enqueuedAtMs = i * 1000L
            )
            val res = PendingIncidentQueue.enqueue(mockContext, record)
            assertTrue("Item $i should be persisted successfully", res is PendingIncidentQueue.EnqueueResult.Success)
        }

        val fullQueue = PendingIncidentQueue.getAll(mockContext)
        assertEquals("Queue should have exactly MAX_PENDING items", PendingIncidentQueue.MAX_PENDING, fullQueue.size)
        assertEquals("Oldest item trigger-1 must be at index 0", "trigger-1", fullQueue[0].triggerId)

        // Attempt to enqueue item 101 when at full capacity
        val overflowRecord = PendingIncidentRecord(
            triggerId = "trigger-101",
            requestJson = """{"seq": 101}""",
            enqueuedAtMs = 101000L
        )
        val overflowResult = PendingIncidentQueue.enqueue(mockContext, overflowRecord)

        // INVARIANT VERIFICATION:
        // Must return CapacityExceeded, NOT Success
        assertTrue("Must report CapacityExceeded when queue is full", overflowResult is PendingIncidentQueue.EnqueueResult.CapacityExceeded)
        val capResult = overflowResult as PendingIncidentQueue.EnqueueResult.CapacityExceeded
        assertEquals(PendingIncidentQueue.MAX_PENDING, capResult.currentSize)
        assertEquals(PendingIncidentQueue.MAX_PENDING, capResult.maxSize)

        // INVARIANT VERIFICATION:
        // Existing emergencies are NEVER automatically removed or overwritten!
        val afterAttempt = PendingIncidentQueue.getAll(mockContext)
        assertEquals("Queue size must remain exactly MAX_PENDING without dropping older entries", PendingIncidentQueue.MAX_PENDING, afterAttempt.size)
        assertEquals("CRITICAL: Oldest emergency 'trigger-1' was NOT deleted!", "trigger-1", afterAttempt[0].triggerId)
        assertFalse("New unpersisted emergency must NOT be in queue", afterAttempt.any { it.triggerId == "trigger-101" })
    }

    @Test
    fun `4 Persistence commit failure returns StorageFailure and does not claim success`() {
        every { mockEditor.commit() } returns false

        val record = PendingIncidentRecord(
            triggerId = "trigger-disk-fail",
            requestJson = "{}",
            enqueuedAtMs = 1000L
        )

        val result = PendingIncidentQueue.enqueue(mockContext, record)

        assertTrue("Must return StorageFailure when commit() returns false", result is PendingIncidentQueue.EnqueueResult.StorageFailure)
        assertFalse("Result must not claim to be persisted", result.isPersisted)
        assertNotNull("Storage error state must be updated", PendingIncidentQueue.storageErrorState.value)
    }

    @Test
    fun `5 Storage unavailable returns StorageFailure`() {
        // Point testPrefs to null to simulate total storage failure
        val brokenContext = mockk<Context>(relaxed = true)
        PendingIncidentQueue.testPrefs = null

        val record = PendingIncidentRecord(
            triggerId = "trigger-no-storage",
            requestJson = "{}",
            enqueuedAtMs = 1000L
        )

        val result = PendingIncidentQueue.enqueue(brokenContext, record)

        assertTrue("Must return StorageFailure when storage is unavailable", result is PendingIncidentQueue.EnqueueResult.StorageFailure)
        assertFalse("Result must not claim to be persisted", result.isPersisted)
    }

    @Test
    fun `6 Multiple pending incidents are tracked independently with FIFO order`() {
        val r1 = PendingIncidentRecord("trigger-A", "{}", 1000L)
        val r2 = PendingIncidentRecord("trigger-B", "{}", 2000L)
        val r3 = PendingIncidentRecord("trigger-C", "{}", 3000L)

        PendingIncidentQueue.enqueue(mockContext, r1)
        PendingIncidentQueue.enqueue(mockContext, r2)
        PendingIncidentQueue.enqueue(mockContext, r3)

        val all = PendingIncidentQueue.getAll(mockContext)
        assertEquals(3, all.size)
        assertEquals("trigger-A", all[0].triggerId)
        assertEquals("trigger-B", all[1].triggerId)
        assertEquals("trigger-C", all[2].triggerId)
    }

    @Test
    fun `7 Deduplication on idempotency key returns AlreadyQueued without duplicates`() {
        val r1 = PendingIncidentRecord("trigger-idem", "{}", 1000L)
        val firstResult = PendingIncidentQueue.enqueue(mockContext, r1)
        assertTrue("First enqueue should succeed", firstResult is PendingIncidentQueue.EnqueueResult.Success)

        val duplicate = PendingIncidentRecord("trigger-idem", "{}", 2000L)
        val secondResult = PendingIncidentQueue.enqueue(mockContext, duplicate)
        assertTrue("Second enqueue should be AlreadyQueued", secondResult is PendingIncidentQueue.EnqueueResult.AlreadyQueued)

        assertEquals("Queue should contain only 1 record", 1, PendingIncidentQueue.getAll(mockContext).size)
    }

    @Test
    fun `8 Independent removal only removes matching incident`() {
        val r1 = PendingIncidentRecord("trigger-X", "{}", 1000L)
        val r2 = PendingIncidentRecord("trigger-Y", "{}", 2000L)

        PendingIncidentQueue.enqueue(mockContext, r1)
        PendingIncidentQueue.enqueue(mockContext, r2)

        val removed = PendingIncidentQueue.remove(mockContext, "trigger-X")
        assertTrue("Remove should succeed", removed)

        val remaining = PendingIncidentQueue.getAll(mockContext)
        assertEquals(1, remaining.size)
        assertEquals("trigger-Y", remaining[0].triggerId)
    }

    @Test
    fun `9 markNeedsAttention preserves incident in storage with reason and excludes from retryable`() {
        val r = PendingIncidentRecord("trigger-val-fail", "{}", 1000L)
        PendingIncidentQueue.enqueue(mockContext, r)

        val marked = PendingIncidentQueue.markNeedsAttention(mockContext, "trigger-val-fail", "HTTP 422: Invalid location")
        assertTrue("markNeedsAttention should succeed", marked)

        val all = PendingIncidentQueue.getAll(mockContext)
        assertEquals(1, all.size)
        assertEquals(PendingIncidentStatus.NEEDS_ATTENTION, all[0].status)
        assertEquals("HTTP 422: Invalid location", all[0].failureReason)

        // Retryable incidents must exclude NEEDS_ATTENTION:
        val retryable = PendingIncidentQueue.getRetryableIncidents(mockContext)
        assertTrue("Retryable list must exclude incidents marked NEEDS_ATTENTION", retryable.isEmpty())

        // Attention-needed list must include it:
        val attentionList = PendingIncidentQueue.getAttentionNeededIncidents(mockContext)
        assertEquals(1, attentionList.size)
        assertEquals("trigger-val-fail", attentionList[0].triggerId)
    }

    @Test
    fun `10 Storage corruption in JSON returns empty list safely without crashing`() {
        memoryStore["pending_incidents"] = "MALFORMED_NON_JSON_CONTENT{{{"
        val records = PendingIncidentQueue.getAll(mockContext)
        assertTrue("Malformed JSON should be handled gracefully, returning empty list", records.isEmpty())
    }
}
