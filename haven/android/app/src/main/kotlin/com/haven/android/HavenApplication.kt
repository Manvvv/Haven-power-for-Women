package com.haven.android

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.util.Log
import androidx.work.Configuration
import androidx.work.WorkManager
import com.haven.android.repository.PendingIncidentQueue

/**
 * HAVEN Application
 *
 * Creates notification channels required by the foreground service and SOS alerts.
 * Channels must be created before any notification is posted (API 26+).
 * Also reconciles any unhandled pending SOS incidents from a prior process kill.
 */
class HavenApplication : Application(), Configuration.Provider {

    override fun onCreate() {
        super.onCreate()
        createNotificationChannels()
        reconcilePendingIncidents()
    }

    private fun reconcilePendingIncidents() {
        try {
            if (PendingIncidentQueue.hasPendingRecords(this)) {
                Log.i("HavenApplication", "Unhandled SOS records detected on cold start; scheduling retry worker")
                PendingIncidentQueue.scheduleRetryWorker(this)
            }
        } catch (e: Exception) {
            Log.e("HavenApplication", "Error during startup SOS reconciliation: ${e.message}")
        }
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val nm = getSystemService(NotificationManager::class.java)

            // Foreground-service monitoring channel — LOW importance so it does not
            // audibly intrude while the user goes about their day, but remains visible
            // in the status bar as required by the foreground-service contract.
            val monitoringChannel = NotificationChannel(
                CHANNEL_MONITORING,
                getString(R.string.channel_monitoring_name),
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = getString(R.string.channel_monitoring_desc)
                setShowBadge(false)
            }

            // SOS alert channel — HIGH importance so the SOS notification appears as
            // a heads-up banner and audibly alerts the user.
            val sosChannel = NotificationChannel(
                CHANNEL_SOS,
                getString(R.string.channel_sos_name),
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = getString(R.string.channel_sos_desc)
                enableVibration(true)
                setShowBadge(true)
            }

            nm.createNotificationChannel(monitoringChannel)
            nm.createNotificationChannel(sosChannel)
        }
    }

    // WorkManager custom configuration — no special tweaks needed but declaring
    // Configuration.Provider is the preferred pattern for AGP 8+.
    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setMinimumLoggingLevel(android.util.Log.INFO)
            .build()

    companion object {
        const val CHANNEL_MONITORING = "haven_monitoring"
        const val CHANNEL_SOS = "haven_sos"

        const val NOTIFICATION_ID_MONITORING = 1001
        const val NOTIFICATION_ID_SOS = 1002
    }
}
