package com.haven.android.ui

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.net.http.SslError
import android.os.Build
import android.util.Log
import android.webkit.*
import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.WifiOff
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import com.haven.android.service.ShakeDetectionService

/**
 * HavenWebViewScreen — full-screen WebView embedding the HAVEN website.
 *
 * Security rules:
 * - Only HAVEN origin hosts (from the configured server URL) are allowed
 *   to call the JavaScript bridge. External URLs are opened in Chrome Custom Tabs.
 * - Clerk OAuth pages (sign-in, sign-up) are intercepted and opened in
 *   Chrome Custom Tabs, as Google's OAuth policy forbids embedded WebView sign-in.
 * - SSL errors are NOT bypassed; the app shows an error rather than proceeding.
 * - DOM storage and JavaScript are enabled only for the HAVEN site.
 * - No arbitrary JS execution is allowed from bridge methods.
 *
 * @param frontendUrl  The local Next.js URL, e.g. "http://192.168.1.8:3000"
 * @param viewModel    Provides monitoring status to the bridge.
 * @param onRequestPermissions  Callback to trigger Android permission dialogs.
 * @param onStartService        Callback to start ShakeDetectionService.
 * @param onStopService         Callback to stop ShakeDetectionService.
 * @param fileChooserLauncher   Callback to launch file picker; returns WebView value callback.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun HavenWebViewScreen(
    frontendUrl: String,
    viewModel: MainViewModel,
    onRequestPermissions: () -> Unit,
    onStartService: () -> Unit,
    onStopService: () -> Unit,
    fileChooserCallback: MutableState<ValueCallback<Array<Uri>>?>,
) {
    val context = LocalContext.current
    var loadingProgress by remember { mutableStateOf(0) }
    var isOffline by remember { mutableStateOf(false) }
    var webViewRef by remember { mutableStateOf<WebView?>(null) }
    var pageTitle by remember { mutableStateOf("HAVEN") }

    // Allowed HAVEN origin hosts derived from frontendUrl
    val allowedHosts = remember(frontendUrl) {
        buildSet {
            try {
                Uri.parse(frontendUrl).host?.let { add(it) }
            } catch (_: Exception) {}
            // In debug mode, optionally allow local loopback origins
            if (com.haven.android.BuildConfig.DEBUG) {
                add("localhost")
                add("10.0.2.2")
                add("127.0.0.1")
            }
        }
    }

    // Clerk OAuth routes that must NOT run in an embedded WebView
    val clerkRoutes = setOf("/sign-in", "/sign-up")

    fun isHavenHost(url: String?): Boolean {
        url ?: return false
        return try {
            val host = Uri.parse(url).host ?: return false
            allowedHosts.any { allowed -> host == allowed || host.endsWith(".$allowed") }
        } catch (_: Exception) { false }
    }

    fun isClerkOAuthRoute(url: String?): Boolean {
        url ?: return false
        return try {
            val path = Uri.parse(url).path ?: return false
            clerkRoutes.any { path.startsWith(it) } ||
                url.contains("clerk.accounts.dev") ||
                url.contains("accounts.google.com") ||
                url.contains("oauth") && !isHavenHost(url)
        } catch (_: Exception) { false }
    }

    fun openInCustomTabs(context: Context, url: String) {
        try {
            val builder = CustomTabsIntent.Builder()
                .setShowTitle(true)
                .build()
            builder.launchUrl(context, Uri.parse(url))
        } catch (e: Exception) {
            Log.e("HavenWebView", "Chrome Custom Tabs failed, opening in browser: $url", e)
            try {
                context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).apply {
                    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                })
            } catch (e2: Exception) {
                Log.e("HavenWebView", "Could not open URL externally: $url", e2)
            }
        }
    }

    // Handle back navigation in WebView
    BackHandler {
        webViewRef?.let { wv ->
            if (wv.canGoBack()) wv.goBack()
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        if (isOffline) {
            // ── Offline / Error State ──────────────────────────────────────────
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(32.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Icon(
                    imageVector = Icons.Default.WifiOff,
                    contentDescription = null,
                    modifier = Modifier.size(64.dp),
                    tint = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(modifier = Modifier.height(16.dp))
                Text(
                    text = "Cannot reach HAVEN website",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Make sure the HAVEN frontend is running at:\n$frontendUrl\n\n" +
                        "Start it with: npm run dev\n" +
                        "in the haven/frontend/ folder.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(24.dp))
                Button(onClick = {
                    isOffline = false
                    webViewRef?.reload()
                }) {
                    Icon(Icons.Default.Refresh, contentDescription = null)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Retry")
                }
            }
        } else {
            // ── WebView ───────────────────────────────────────────────────────
            AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { ctx ->
                    WebView(ctx).apply {
                        webViewRef = this
                        settings.apply {
                            javaScriptEnabled = true
                            domStorageEnabled = true
                            setSupportMultipleWindows(false)
                            allowFileAccess = false         // Restrict to web content only
                            allowContentAccess = true
                            useWideViewPort = true
                            loadWithOverviewMode = true
                            builtInZoomControls = false
                            displayZoomControls = false
                            setSupportZoom(false)
                            // Enable media autoplay for voice-sos
                            mediaPlaybackRequiresUserGesture = false
                        }
                        // Cookie policy — allow same-site cookies for session auth (called on WebView)
                        CookieManager.getInstance().setAcceptThirdPartyCookies(this, false)

                        // ── JavaScript Bridge ─────────────────────────────────
                        val bridge = HavenBridge(
                            viewModel = viewModel,
                            permissionCallback = onRequestPermissions,
                            serviceCallback = { action ->
                                when (action) {
                                    ShakeDetectionService.ACTION_START_MONITORING -> onStartService()
                                    ShakeDetectionService.ACTION_STOP_MONITORING -> onStopService()
                                }
                            }
                        )
                        addJavascriptInterface(bridge, HavenBridge.JS_OBJECT_NAME)

                        // ── WebChromeClient ───────────────────────────────────
                        webChromeClient = object : WebChromeClient() {
                            override fun onProgressChanged(view: WebView?, newProgress: Int) {
                                loadingProgress = newProgress
                            }

                            override fun onReceivedTitle(view: WebView?, title: String?) {
                                pageTitle = title ?: "HAVEN"
                            }

                            // Geolocation permission — only for HAVEN origin
                            override fun onGeolocationPermissionsShowPrompt(
                                origin: String?,
                                callback: GeolocationPermissions.Callback?
                            ) {
                                val allow = origin != null && isHavenHost(origin)
                                Log.d("HavenWebView", "Geolocation request from $origin → allow=$allow")
                                callback?.invoke(origin, allow, false)
                            }

                            // File chooser (for profile photo, evidence uploads, etc.)
                            override fun onShowFileChooser(
                                webView: WebView?,
                                valueCallback: ValueCallback<Array<Uri>>?,
                                fileChooserParams: FileChooserParams?
                            ): Boolean {
                                fileChooserCallback.value?.onReceiveValue(null)
                                fileChooserCallback.value = valueCallback
                                return true  // MainActivity handles launching the file picker
                            }
                        }

                        // ── WebViewClient ─────────────────────────────────────
                        webViewClient = object : WebViewClient() {
                            override fun shouldOverrideUrlLoading(
                                view: WebView?,
                                request: WebResourceRequest?
                            ): Boolean {
                                val url = request?.url?.toString() ?: return false

                                // Open Clerk OAuth / external URLs in Chrome Custom Tabs
                                if (isClerkOAuthRoute(url) || !isHavenHost(url)) {
                                    Log.i("HavenWebView", "Opening externally: $url")
                                    openInCustomTabs(ctx, url)
                                    return true
                                }

                                // Allow HAVEN site navigation within WebView
                                return false
                            }

                            override fun onPageStarted(
                                view: WebView?,
                                url: String?,
                                favicon: Bitmap?
                            ) {
                                isOffline = false
                                loadingProgress = 0
                            }

                            override fun onPageFinished(view: WebView?, url: String?) {
                                loadingProgress = 100
                                // Inject bridge status when page finishes loading on HAVEN origin
                                if (isHavenHost(url)) {
                                    view?.evaluateJavascript(
                                        """(function(){
                                            if(window.__havenBridgeReady === undefined){
                                                window.__havenBridgeReady = true;
                                                var evt = new CustomEvent('havenBridgeReady', {detail: {platform:'android'}});
                                                window.dispatchEvent(evt);
                                            }
                                        })();""",
                                        null
                                    )
                                }
                            }

                            override fun onReceivedError(
                                view: WebView?,
                                request: WebResourceRequest?,
                                error: WebResourceError?
                            ) {
                                // Only treat errors on the main frame as "offline"
                                if (request?.isForMainFrame == true) {
                                    val errorCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                                        error?.errorCode ?: -1
                                    } else -1
                                    Log.w("HavenWebView", "Main frame error: code=$errorCode url=${request.url}")
                                    isOffline = true
                                }
                            }

                            @SuppressLint("WebViewClientOnReceivedSslError")
                            override fun onReceivedSslError(
                                view: WebView?,
                                handler: SslErrorHandler?,
                                error: SslError?
                            ) {
                                // Do NOT proceed through SSL errors — show offline page
                                handler?.cancel()
                                Log.e("HavenWebView", "SSL error: ${error?.primaryError}")
                                isOffline = true
                            }
                        }

                        loadUrl(frontendUrl)
                    }
                },
                update = { wv ->
                    webViewRef = wv
                }
            )

            // ── Loading Progress Bar ───────────────────────────────────────────
            if (loadingProgress in 1..99) {
                LinearProgressIndicator(
                    progress = { loadingProgress / 100f },
                    modifier = Modifier
                        .fillMaxWidth()
                        .align(Alignment.TopCenter)
                )
            }
        }
    }
}
