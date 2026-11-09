package com.haven.android.ui

import android.content.Intent
import android.util.Log
import android.webkit.JavascriptInterface
import com.haven.android.service.ShakeDetectionService
import org.json.JSONObject

/**
 * HavenBridge — secure JavaScript interface between the HAVEN WebView and Kotlin native code.
 *
 * Security model:
 * - Origin is validated by [HavenWebViewScreen] before the bridge is added.
 * - Only the HAVEN local server origin (host-matched) may call these methods.
 * - Methods return JSON strings — no raw objects, no arbitrary JS execution.
 * - No secrets (JWT, API keys) are passed through or exposed by this bridge.
 * - Callers receive only structured status data, not raw Android API references.
 *
 * JavaScript usage (from web page):
 *   Android.startMonitoring()       → starts ShakeDetectionService
 *   Android.stopMonitoring()        → stops ShakeDetectionService
 *   Android.getMonitoringStatus()   → returns JSON: { "monitoring": bool, "userEnabled": bool, "locationGranted": bool, "notificationGranted": bool }
 *   Android.requestPermissions()    → signals native layer to request permissions (UI callback)
 *   Android.getAppVersion()         → returns JSON: { "version": "1.0.0", "platform": "android" }
 *   Android.getWsUrl()              → returns JSON: { "wsUrl": "ws://host:port" }
 */
class HavenBridge(
    private val viewModel: MainViewModel,
    private val permissionCallback: () -> Unit,
    private val serviceCallback: (String) -> Unit  // ACTION_START_MONITORING | ACTION_STOP_MONITORING
) {

    companion object {
        const val TAG = "HavenBridge"
        const val JS_OBJECT_NAME = "Android"
    }

    @JavascriptInterface
    fun startMonitoring(): String {
        Log.d(TAG, "JS called startMonitoring()")
        serviceCallback(ShakeDetectionService.ACTION_START_MONITORING)
        viewModel.setMonitoringEnabled(true)
        return buildStatusJson()
    }

    @JavascriptInterface
    fun stopMonitoring(): String {
        Log.d(TAG, "JS called stopMonitoring()")
        serviceCallback(ShakeDetectionService.ACTION_STOP_MONITORING)
        viewModel.setMonitoringEnabled(false)
        return buildStatusJson()
    }

    @JavascriptInterface
    fun getMonitoringStatus(): String {
        Log.d(TAG, "JS called getMonitoringStatus()")
        return buildStatusJson()
    }

    @JavascriptInterface
    fun requestPermissions(): String {
        Log.d(TAG, "JS called requestPermissions()")
        permissionCallback()
        return """{"requested":true}"""
    }

    @JavascriptInterface
    fun getAppVersion(): String {
        return """{"version":"1.0.0","platform":"android","bridge":"HavenBridge/1"}"""
    }

    @JavascriptInterface
    fun getWsUrl(): String {
        // Expose the configured WebSocket URL so the website can use it
        // for real-time notifications without needing to know the host separately.
        return try {
            val ws = viewModel.wsUrl.value.trimEnd('/')
            """{"wsUrl":"$ws"}"""
        } catch (e: Exception) {
            Log.e(TAG, "getWsUrl failed", e)
            """{"wsUrl":""}"""
        }
    }

    // ─── Internal ─────────────────────────────────────────────────────────────

    private fun buildStatusJson(): String {
        val status = viewModel.monitoringStatus.value
        return try {
            JSONObject().apply {
                put("monitoring", status.isActuallyMonitoring)
                put("userEnabled", status.userEnabled)
                put("serviceRunning", status.serviceRunning)
                put("locationGranted", status.locationPermissionGranted)
                put("notificationGranted", status.notificationPermissionGranted)
            }.toString()
        } catch (e: Exception) {
            Log.e(TAG, "Failed to build status JSON", e)
            """{"error":"status_unavailable"}"""
        }
    }
}
