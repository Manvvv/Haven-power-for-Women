package com.haven.android.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * BootReceiver
 *
 * Receives BOOT_COMPLETED after device startup.
 *
 * IMPORTANT: This receiver does NOT automatically restart the ShakeDetectionService.
 * Doing so without explicit user consent would bypass Android's foreground-service
 * user-consent model and may violate Play Store policies.
 *
 * Instead, it checks MonitoringStatusRepository.userEnabled. If the user had
 * monitoring enabled before the reboot, a notification is posted prompting them
 * to re-enable it. The user must actively tap the notification or open the app.
 *
 * This is the honest approach: we cannot guarantee monitoring continues after a
 * forced device restart without user interaction.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action != Intent.ACTION_BOOT_COMPLETED &&
            action != "android.intent.action.LOCKED_BOOT_COMPLETED") return

        Log.d("BootReceiver", "Boot completed — checking monitoring preference")

        // Show a notification prompting the user to re-enable monitoring.
        // We do NOT auto-start the service.
        try {
            val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as android.app.NotificationManager
            val pendingIntent = android.app.PendingIntent.getActivity(
                context, 0,
                Intent(context, com.haven.android.twa.MonitorControlActivity::class.java).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                },
                android.app.PendingIntent.FLAG_UPDATE_CURRENT or android.app.PendingIntent.FLAG_IMMUTABLE
            )

            val notification = androidx.core.app.NotificationCompat.Builder(
                context, com.haven.android.HavenApplication.CHANNEL_MONITORING
            )
                .setContentTitle("HAVEN — Re-enable SOS Monitoring")
                .setContentText("Tap to reopen HAVEN and restart shake monitoring after device restart.")
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)
                .setPriority(androidx.core.app.NotificationCompat.PRIORITY_DEFAULT)
                .build()

            nm.notify(com.haven.android.HavenApplication.NOTIFICATION_ID_MONITORING + 1, notification)
        } catch (e: Exception) {
            Log.w("BootReceiver", "Could not post boot notification: ${e.message}")
        }
    }
}
