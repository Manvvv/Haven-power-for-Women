package com.haven.android.repository

import android.content.Context
import android.content.SharedPreferences
import com.haven.android.BuildConfig
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * ServerConfigRepository
 *
 * Persists and provides the HAVEN backend base URL.
 * Defaults to BuildConfig.HAVEN_BASE_URL_HTTPS (or local development address).
 * Allows dynamic configuration via the UI so that devices on different Wi-Fi networks,
 * emulators, or reverse-tethered setups can point to the correct backend host.
 */
class ServerConfigRepository(private val context: Context) {

    companion object {
        private const val PREF_FILE = "haven_server_config"
        private const val KEY_SERVER_URL = "server_base_url"

        val DEFAULT_URL: String = BuildConfig.HAVEN_BASE_URL_HTTPS
    }

    private val prefs: SharedPreferences by lazy {
        context.getSharedPreferences(PREF_FILE, Context.MODE_PRIVATE)
    }

    private val _serverUrl = MutableStateFlow(getServerUrl())
    val serverUrl: StateFlow<String> = _serverUrl.asStateFlow()

    fun getServerUrl(): String {
        val saved = prefs.getString(KEY_SERVER_URL, null)
        val raw = if (!saved.isNullOrBlank()) saved else DEFAULT_URL
        return raw.trim().trimEnd('/') + "/"
    }

    fun setServerUrl(newUrl: String) {
        val clean = newUrl.trim().trimEnd('/') + "/"
        prefs.edit().putString(KEY_SERVER_URL, clean).apply()
        _serverUrl.value = clean
    }
}
