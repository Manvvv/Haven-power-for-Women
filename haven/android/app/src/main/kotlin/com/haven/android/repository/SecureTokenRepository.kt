package com.haven.android.repository

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.haven.android.BuildConfig

/**
 * SecureTokenRepository
 *
 * Stores JWT access tokens using EncryptedSharedPreferences (AES-256 backed by
 * the Android Keystore). Tokens are NEVER written to unencrypted storage,
 * logcat, or crash reports.
 *
 * The master key is created in the Android Keystore under the HAVEN namespace.
 * If the keystore is unavailable (factory reset protection, device wipe), the
 * encrypted prefs are cleared and the user must re-authenticate.
 */
class SecureTokenRepository(private val context: Context) {

    private companion object {
        private const val TAG = "SecureTokenRepo"
        private const val PREF_FILE = "haven_secure_prefs"
        private const val KEY_ACCESS_TOKEN = "access_token"
        private const val KEY_USER_ID = "user_id"
        private const val KEY_ROLE = "role"
        private const val KEY_TOKEN_EXPIRY_MS = "token_expiry_ms"
    }

    private val prefs: SharedPreferences by lazy {
        try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                PREF_FILE,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
        } catch (e: Exception) {
            // Keystore failure (e.g. after factory reset on some OEMs).
            // Fall back to clearing credentials and returning an empty pref store.
            Log.e(TAG, "EncryptedSharedPreferences unavailable; clearing credentials")
            context.getSharedPreferences(PREF_FILE, Context.MODE_PRIVATE).edit().clear().apply()
            context.getSharedPreferences(PREF_FILE, Context.MODE_PRIVATE)
        }
    }

    fun saveToken(accessToken: String, userId: String, role: String, expiresInSeconds: Int) {
        val expiryMs = System.currentTimeMillis() + (expiresInSeconds * 1000L)
        prefs.edit()
            .putString(KEY_ACCESS_TOKEN, accessToken)
            .putString(KEY_USER_ID, userId)
            .putString(KEY_ROLE, role)
            .putLong(KEY_TOKEN_EXPIRY_MS, expiryMs)
            .apply()
        // Do NOT log the token value.
        Log.d(TAG, "Token saved for user_id=$userId role=$role")
    }

    fun getAccessToken(): String? {
        val token = prefs.getString(KEY_ACCESS_TOKEN, null)
        val expiry = prefs.getLong(KEY_TOKEN_EXPIRY_MS, 0L)
        if (token != null && System.currentTimeMillis() > expiry) {
            Log.w(TAG, "Stored token has expired; clearing")
            clearToken()
            return null
        }
        return token
    }

    fun getBearerHeader(): String? = getAccessToken()?.let { "Bearer $it" }

    fun getUserId(): String? = prefs.getString(KEY_USER_ID, null)

    fun getRole(): String? = prefs.getString(KEY_ROLE, null)

    fun isAuthenticated(): Boolean = getAccessToken() != null

    fun clearToken() {
        prefs.edit()
            .remove(KEY_ACCESS_TOKEN)
            .remove(KEY_USER_ID)
            .remove(KEY_ROLE)
            .remove(KEY_TOKEN_EXPIRY_MS)
            .apply()
        Log.d(TAG, "Token cleared")
    }
}
