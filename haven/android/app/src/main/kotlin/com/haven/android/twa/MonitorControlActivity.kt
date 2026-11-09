package com.haven.android.twa

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.core.content.ContextCompat
import com.haven.android.repository.MonitoringStatusRepository
import com.haven.android.repository.SecureTokenRepository
import com.haven.android.repository.ServerConfigRepository
import com.haven.android.service.ShakeDetectionService
import com.haven.android.ui.MonitorTab
import com.haven.android.ui.MainViewModel
import com.haven.android.ui.MainViewModelFactory
import com.haven.android.ui.theme.HavenTheme

/**
 * MonitorControlActivity
 *
 * Standalone activity that shows the native Shake-to-SOS monitor controls.
 * Launched from:
 *   - The foreground service notification (tap → opens this activity).
 *   - The Android app drawer when TWA is the primary launcher entry.
 *
 * This activity does NOT host the website (that is TwaLauncherActivity).
 * It only shows the native monitoring panel (permissions, start/stop, diagnostics).
 *
 * Architecture note: In TWA mode, HavenBridge.kt is NOT used. The website
 * communicates with the backend directly over HTTPS. Native shake detection
 * posts SOS events directly via SosRepository → backend API, independent of
 * the web session.
 */
class MonitorControlActivity : ComponentActivity() {

    companion object {
        private const val TAG = "MonitorControlActivity"
    }

    private val tokenRepo by lazy { SecureTokenRepository(this) }
    private val monitoringRepo by lazy { MonitoringStatusRepository(this) }
    private val serverConfigRepo by lazy { ServerConfigRepository(this) }
    private val viewModel: MainViewModel by viewModels {
        MainViewModelFactory(application, tokenRepo, monitoringRepo, serverConfigRepo)
    }

    private var onPermissionResult: ((Boolean) -> Unit)? = null

    private val locationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val granted = permissions.any { it.value }
        Log.d(TAG, "Location permission: $granted")
        onPermissionResult?.invoke(granted)
        onPermissionResult = null
    }

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        Log.d(TAG, "Notification permission: $granted")
        onPermissionResult?.invoke(granted)
        onPermissionResult = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            HavenTheme {
                MonitorTab(
                    viewModel = viewModel,
                    onRequestLocationPermission = { cb -> requestLocationPermission(cb) },
                    onRequestNotificationPermission = { cb -> requestNotificationPermission(cb) },
                    onStartMonitoring = { startMonitoringService() },
                    onStopMonitoring = { stopMonitoringService() },
                    onStartTest = { startTestMode() },
                    onOpenWebsite = { openHavenWebsite() }
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        viewModel.refreshPermissions(
            hasLocation = hasLocationPermission(),
            hasNotification = hasNotificationPermission()
        )
    }

    private fun hasLocationPermission() =
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED ||
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED

    private fun hasNotificationPermission(): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU)
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) ==
                    PackageManager.PERMISSION_GRANTED
        else true

    private fun requestLocationPermission(callback: (Boolean) -> Unit) {
        if (hasLocationPermission()) { callback(true); return }
        onPermissionResult = callback
        locationPermissionLauncher.launch(
            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        )
    }

    private fun requestNotificationPermission(callback: (Boolean) -> Unit) {
        if (hasNotificationPermission()) { callback(true); return }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            onPermissionResult = callback
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else callback(true)
    }

    private fun startMonitoringService() {
        Log.d(TAG, "Starting ShakeDetectionService")
        val intent = Intent(this, ShakeDetectionService::class.java).apply {
            action = ShakeDetectionService.ACTION_START_MONITORING
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent)
        else startService(intent)
    }

    private fun stopMonitoringService() {
        Log.d(TAG, "Stopping ShakeDetectionService")
        val intent = Intent(this, ShakeDetectionService::class.java).apply {
            action = ShakeDetectionService.ACTION_STOP_MONITORING
        }
        startService(intent)
    }

    private fun startTestMode() {
        Toast.makeText(this, "Test mode — shake three times!", Toast.LENGTH_LONG).show()
        val intent = Intent(this, ShakeDetectionService::class.java).apply {
            action = ShakeDetectionService.ACTION_START_TEST
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) startForegroundService(intent)
        else startService(intent)
    }

    private fun openHavenWebsite() {
        startActivity(Intent(this, TwaLauncherActivity::class.java))
    }
}
