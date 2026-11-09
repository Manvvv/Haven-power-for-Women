package com.haven.android.repository

import android.content.Context
import android.content.SharedPreferences
import android.net.Uri
import com.haven.android.BuildConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * HavenUrlConfig — immutable snapshot of all three configured URLs.
 *
 * @param backendUrl   FastAPI base URL (production: "https://haven-power-for-women.onrender.com/")
 * @param frontendUrl  Next.js base URL  (production: "https://haven-your-own-voice.vercel.app")
 * @param wsUrl        WebSocket base URL (production: "wss://haven-power-for-women.onrender.com")
 */
data class HavenUrlConfig(
    val backendUrl: String,
    val frontendUrl: String,
    val wsUrl: String,
) {
    companion object {

        /**
         * Derives a WebSocket URL from an HTTP/HTTPS backend URL.
         * https://host:port/ →  wss://host:port
         * http://host:port/  →  ws://host:port
         */
        fun wsFromHttp(httpUrl: String): String {
            return try {
                val uri = Uri.parse(httpUrl.trimEnd('/'))
                val scheme = when (uri.scheme?.lowercase()) {
                    "http" -> "ws"
                    else   -> "wss"
                }
                val host = uri.host ?: "haven-power-for-women.onrender.com"
                val port = uri.port.takeIf { it > 0 }
                if (port != null) "$scheme://$host:$port" else "$scheme://$host"
            } catch (_: Exception) {
                "wss://haven-power-for-women.onrender.com"
            }
        }

        /**
         * Returns the authoritative frontend URL for the backend.
         */
        fun frontendFromBackend(backendUrl: String): String {
            return "https://haven-your-own-voice.vercel.app"
        }
    }
}

/**
 * HavenUrlRepository
 *
 * Persists and provides the three HAVEN service URLs:
 *   1. Backend API URL  — FastAPI (production: https://haven-power-for-women.onrender.com)
 *   2. Frontend URL     — Next.js  (production: https://haven-your-own-voice.vercel.app)
 *   3. WebSocket URL    — WSS      (production: wss://haven-power-for-women.onrender.com)
 *
 * Enforces production-first URLs across the application.
 */
class HavenUrlRepository(private val context: Context) {

    companion object {
        private const val PREF_FILE  = "haven_url_config"
        private const val KEY_BACKEND  = "backend_url"
        private const val KEY_FRONTEND = "frontend_url"
        private const val KEY_WS       = "ws_url"
        private const val KEY_WS_OVERRIDE = "ws_url_override"

        // Authoritative production URLs
        const val DEFAULT_BACKEND_URL  = "https://haven-power-for-women.onrender.com"
        const val DEFAULT_FRONTEND_URL = "https://haven-your-own-voice.vercel.app"
        const val DEFAULT_WS_URL       = "wss://haven-power-for-women.onrender.com"
    }

    private val prefs: SharedPreferences by lazy {
        context.getSharedPreferences(PREF_FILE, Context.MODE_PRIVATE)
    }

    // ─── Backend URL ──────────────────────────────────────────────────────────

    private val _backendUrl = MutableStateFlow(getBackendUrl())
    val backendUrl: StateFlow<String> = _backendUrl.asStateFlow()

    fun getBackendUrl(): String {
        val saved = prefs.getString(KEY_BACKEND, null)
        val raw = if (!saved.isNullOrBlank()) saved else DEFAULT_BACKEND_URL
        return raw.trim().trimEnd('/') + "/"
    }

    fun setBackendUrl(newUrl: String) {
        val clean = newUrl.trim().trimEnd('/') + "/"
        prefs.edit().putString(KEY_BACKEND, clean).apply()
        _backendUrl.value = clean
        if (!prefs.getBoolean(KEY_WS_OVERRIDE, false)) {
            _wsUrl.value = HavenUrlConfig.wsFromHttp(clean)
        }
    }

    // ─── Frontend URL ─────────────────────────────────────────────────────────

    private val _frontendUrl = MutableStateFlow(getFrontendUrl())
    val frontendUrl: StateFlow<String> = _frontendUrl.asStateFlow()

    fun getFrontendUrl(): String {
        val saved = prefs.getString(KEY_FRONTEND, null)
        return if (!saved.isNullOrBlank()) {
            saved.trim().trimEnd('/')
        } else {
            DEFAULT_FRONTEND_URL
        }
    }

    fun setFrontendUrl(newUrl: String) {
        val clean = newUrl.trim().trimEnd('/')
        prefs.edit().putString(KEY_FRONTEND, clean).apply()
        _frontendUrl.value = clean
    }

    // ─── WebSocket URL ────────────────────────────────────────────────────────

    private val _wsUrl = MutableStateFlow(getWsUrl())
    val wsUrl: StateFlow<String> = _wsUrl.asStateFlow()

    fun getWsUrl(): String {
        val saved = prefs.getString(KEY_WS, null)
        return if (!saved.isNullOrBlank()) {
            saved.trim().trimEnd('/')
        } else {
            DEFAULT_WS_URL
        }
    }

    fun setWsUrl(newUrl: String) {
        val clean = newUrl.trim().trimEnd('/')
        prefs.edit()
            .putString(KEY_WS, clean)
            .putBoolean(KEY_WS_OVERRIDE, true)
            .apply()
        _wsUrl.value = clean
    }

    fun clearWsOverride() {
        prefs.edit()
            .remove(KEY_WS)
            .putBoolean(KEY_WS_OVERRIDE, false)
            .apply()
        _wsUrl.value = DEFAULT_WS_URL
    }

    // ─── Composite snapshot ───────────────────────────────────────────────────

    fun getConfig(): HavenUrlConfig = HavenUrlConfig(
        backendUrl  = getBackendUrl(),
        frontendUrl = getFrontendUrl(),
        wsUrl       = getWsUrl(),
    )

    // ─── Presets (production defaults) ────────────────────────────────────────

    fun applyLocalPreset() {
        setBackendUrl(DEFAULT_BACKEND_URL)
        setFrontendUrl(DEFAULT_FRONTEND_URL)
        clearWsOverride()
    }

    fun applyEmulatorPreset() {
        setBackendUrl(DEFAULT_BACKEND_URL)
        setFrontendUrl(DEFAULT_FRONTEND_URL)
        clearWsOverride()
    }
}
