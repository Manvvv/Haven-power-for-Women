package com.haven.android.twa

import android.content.ComponentName
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.appcompat.app.AppCompatActivity
import androidx.browser.customtabs.CustomTabColorSchemeParams
import androidx.browser.customtabs.CustomTabsCallback
import androidx.browser.customtabs.CustomTabsClient
import androidx.browser.customtabs.CustomTabsIntent
import androidx.browser.customtabs.CustomTabsServiceConnection
import androidx.browser.customtabs.CustomTabsSession
import androidx.browser.trusted.TrustedWebActivityIntentBuilder
import com.haven.android.BuildConfig

/**
 * TwaLauncherActivity
 *
 * Launches the HAVEN website (https://haven-your-own-voice.vercel.app/) as a
 * Trusted Web Activity (TWA). The website renders in full-screen Chrome with no
 * browser toolbar, identical to what users see at the URL in a browser.
 *
 * Lifecycle:
 * 1. Attempts to bind to Chrome Custom Tabs service for warmup.
 * 2. On service connected, builds a TrustedWebActivityIntent and launches it.
 * 3. If service connection fails or times out, falls back to CustomTabsIntent.
 * 4. Finishes itself once launched so back navigation exits cleanly to Android launcher.
 */
class TwaLauncherActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "TwaLauncherActivity"
        val HAVEN_URL: String get() = BuildConfig.HAVEN_TWA_URL
        private const val CONNECTION_TIMEOUT_MS = 800L
        private const val THEME_COLOR_PINK = 0xFFBE185D.toInt()
        private const val NAV_COLOR_WHITE  = 0xFFFFFFFF.toInt()
    }

    private var customTabsClient: CustomTabsClient? = null
    private var customTabsSession: CustomTabsSession? = null
    private var isLaunched = false
    private val handler = Handler(Looper.getMainLooper())

    private val colorSchemeParams by lazy {
        CustomTabColorSchemeParams.Builder()
            .setToolbarColor(THEME_COLOR_PINK)
            .setNavigationBarColor(NAV_COLOR_WHITE)
            .build()
    }

    private val serviceConnection = object : CustomTabsServiceConnection() {
        override fun onCustomTabsServiceConnected(name: ComponentName, client: CustomTabsClient) {
            customTabsClient = client
            client.warmup(0L)
            val session = client.newSession(object : CustomTabsCallback() {})
            customTabsSession = session
            if (session != null) {
                launchWithSession(session)
            } else {
                launchFallback()
            }
        }

        override fun onServiceDisconnected(name: ComponentName) {
            customTabsClient = null
            customTabsSession = null
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Log.d(TAG, "onCreate — launching TWA for $HAVEN_URL")

        // Schedule timeout in case CustomTabsService takes too long or fails to connect
        handler.postDelayed({
            if (!isLaunched) {
                Log.w(TAG, "Service connection timed out, launching fallback")
                launchFallback()
            }
        }, CONNECTION_TIMEOUT_MS)

        val packageName = CustomTabsClient.getPackageName(this, null)
        if (packageName != null) {
            val bound = CustomTabsClient.bindCustomTabsService(this, packageName, serviceConnection)
            if (!bound) {
                Log.w(TAG, "bindCustomTabsService returned false, launching fallback")
                launchFallback()
            }
        } else {
            Log.w(TAG, "No Custom Tabs provider found, launching fallback")
            launchFallback()
        }
    }

    private fun getTargetUri(): Uri {
        val incoming = intent?.data?.toString()
        val url = if (incoming != null && incoming.startsWith("https://haven-your-own-voice.vercel.app")) {
            incoming
        } else {
            HAVEN_URL
        }
        return Uri.parse(url)
    }

    private fun launchWithSession(session: CustomTabsSession) {
        if (isLaunched) return
        isLaunched = true
        handler.removeCallbacksAndMessages(null)

        try {
            val uri = getTargetUri()
            Log.i(TAG, "Launching TrustedWebActivity for $uri")
            val twaIntent = TrustedWebActivityIntentBuilder(uri)
                .setDefaultColorSchemeParams(colorSchemeParams)
                .build(session)

            twaIntent.launchTrustedWebActivity(this)
        } catch (e: Exception) {
            Log.e(TAG, "TWA launch failed with session, falling back to CustomTab", e)
            try {
                val uri = getTargetUri()
                val customTabsIntent = CustomTabsIntent.Builder(session)
                    .setDefaultColorSchemeParams(colorSchemeParams)
                    .setShowTitle(false)
                    .build()
                customTabsIntent.launchUrl(this, uri)
            } catch (fallbackEx: Exception) {
                Log.e(TAG, "CustomTab fallback failed, launching ACTION_VIEW", fallbackEx)
                startActivity(Intent(Intent.ACTION_VIEW, getTargetUri()))
            }
        }
        finish()
    }

    private fun launchFallback() {
        if (isLaunched) return
        isLaunched = true
        handler.removeCallbacksAndMessages(null)

        try {
            val uri = getTargetUri()
            Log.i(TAG, "Launching CustomTab fallback for $uri")
            val customTabsIntent = CustomTabsIntent.Builder()
                .setDefaultColorSchemeParams(colorSchemeParams)
                .setShowTitle(false)
                .build()
            customTabsIntent.launchUrl(this, uri)
        } catch (e: Exception) {
            Log.e(TAG, "CustomTab launch failed, launching ACTION_VIEW", e)
            startActivity(Intent(Intent.ACTION_VIEW, getTargetUri()))
        }
        finish()
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacksAndMessages(null)
        try {
            unbindService(serviceConnection)
        } catch (_: Exception) {
            // Not bound or already unbound
        }
    }
}
