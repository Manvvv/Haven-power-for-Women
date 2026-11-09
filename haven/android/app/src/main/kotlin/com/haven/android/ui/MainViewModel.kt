package com.haven.android.ui

import android.app.Application
import android.util.Log
import androidx.lifecycle.*
import com.haven.android.BuildConfig
import com.haven.android.data.*
import com.haven.android.repository.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.POST
import retrofit2.Response

/**
 * Direct login API — uses a HAVEN internal token (Clerk not required for the
 * Android app in the current backend implementation; the backend accepts
 * HS256 tokens from authenticated authority/user flows). The Android app
 * authenticates using the user's Clerk email+password via a thin proxy,
 * OR we use the authority/responder login endpoints that issue HS256 tokens.
 *
 * For the user login path (not authority), the backend's current architecture
 * uses Clerk as the identity provider. If Clerk is configured on the backend,
 * the Android app must redirect to Clerk's hosted sign-in flow or use Clerk's
 * mobile SDK. For the hackathon/demo scenario, we support the authority-login
 * path which issues an HS256 token directly.
 *
 * Users log in using their authority badge number + password (authority accounts)
 * OR a demo user path. The app is honest about which path is used.
 */
private interface LoginApiService {
    @POST("auth/authority-login")
    suspend fun authorityLogin(@Body body: Map<String, String>): Response<TokenResponse>

    @POST("auth/user-login")
    suspend fun userLogin(@Body body: Map<String, String>): Response<TokenResponse>

    @POST("auth/user-register")
    suspend fun userRegister(@Body body: Map<String, String>): Response<TokenResponse>
}

class MainViewModel(
    private val application: Application,
    private val tokenRepo: SecureTokenRepository,
    private val monitoringRepo: MonitoringStatusRepository,
    private val serverConfigRepo: ServerConfigRepository = ServerConfigRepository(application),
    private val urlRepo: HavenUrlRepository = HavenUrlRepository(application)
) : AndroidViewModel(application) {

    companion object {
        private const val TAG = "MainViewModel"
    }

    // ─── Server / URL State ───────────────────────────────────────────────────

    /** Legacy backend URL — kept for compatibility with ServerConfigRepository. */
    val serverUrl: StateFlow<String> = serverConfigRepo.serverUrl

    /** Backend API URL (FastAPI). Flows from HavenUrlRepository. */
    val backendUrl: StateFlow<String> = urlRepo.backendUrl

    /** Frontend URL (Next.js). Flows from HavenUrlRepository. */
    val frontendUrl: StateFlow<String> = urlRepo.frontendUrl

    /** WebSocket URL. Derived from backend by default; independently configurable. */
    val wsUrl: StateFlow<String> = urlRepo.wsUrl

    fun setServerUrl(url: String) {
        // Keep legacy repo in sync
        serverConfigRepo.setServerUrl(url)
        // Update tri-URL repo backend URL
        urlRepo.setBackendUrl(url)
    }

    fun setBackendUrl(url: String) {
        serverConfigRepo.setServerUrl(url)
        urlRepo.setBackendUrl(url)
    }

    fun setFrontendUrl(url: String) = urlRepo.setFrontendUrl(url)
    fun setWsUrl(url: String) = urlRepo.setWsUrl(url)
    fun clearWsOverride() = urlRepo.clearWsOverride()

    fun applyLocalPreset() {
        urlRepo.applyLocalPreset()
        serverConfigRepo.setServerUrl(urlRepo.getBackendUrl())
    }

    fun applyEmulatorPreset() {
        urlRepo.applyEmulatorPreset()
        serverConfigRepo.setServerUrl(urlRepo.getBackendUrl())
    }

    /**
     * Returns the current frontend URL for the WebView.
     * Uses HavenUrlRepository (independent of backend host) instead of
     * the old hostname-derivation hack.
     */
    fun getFrontendUrl(): String = urlRepo.getFrontendUrl()

    private fun getLoginApi(baseUrl: String): LoginApiService {
        val okHttpClient = okhttp3.OkHttpClient.Builder()
            .connectTimeout(10, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
            .writeTimeout(15, java.util.concurrent.TimeUnit.SECONDS)
            .build()

        return Retrofit.Builder()
            .baseUrl(baseUrl.trimEnd('/') + "/")
            .client(okHttpClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(LoginApiService::class.java)
    }

    private fun parseErrorDetail(response: Response<*>, defaultMsg: String): String {
        return try {
            val jsonStr = response.errorBody()?.string() ?: return defaultMsg
            val json = com.google.gson.JsonParser.parseString(jsonStr).asJsonObject
            when {
                json.has("detail") -> json.get("detail").asString
                json.has("message") -> json.get("message").asString
                else -> defaultMsg
            }
        } catch (e: Exception) {
            defaultMsg
        }
    }

    // ─── Auth State ────────────────────────────────────────────────────────────

    private val _isAuthenticated = MutableStateFlow(tokenRepo.isAuthenticated())
    val isAuthenticated: StateFlow<Boolean> = _isAuthenticated.asStateFlow()

    private val _loginState = MutableStateFlow<LoginState>(LoginState.Idle)
    val loginState: StateFlow<LoginState> = _loginState.asStateFlow()

    sealed class LoginState {
        object Idle : LoginState()
        object Loading : LoginState()
        data class Success(val userId: String) : LoginState()
        data class Error(val message: String) : LoginState()
    }

    // ─── Monitoring Status ─────────────────────────────────────────────────────

    val monitoringStatus: StateFlow<MonitoringStatus> = monitoringRepo.statusFlow
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), MonitoringStatus())

    // ─── Trusted Contacts ──────────────────────────────────────────────────────

    private val _trustedContacts = MutableStateFlow<List<TrustedContact>>(emptyList())
    val trustedContacts: StateFlow<List<TrustedContact>> = _trustedContacts.asStateFlow()

    private val _contactsLoading = MutableStateFlow(false)
    val contactsLoading: StateFlow<Boolean> = _contactsLoading.asStateFlow()

    // ─── Permission State ──────────────────────────────────────────────────────

    private val _hasLocationPerm = MutableStateFlow(false)
    val hasLocationPerm: StateFlow<Boolean> = _hasLocationPerm.asStateFlow()

    private val _hasNotificationPerm = MutableStateFlow(false)
    val hasNotificationPerm: StateFlow<Boolean> = _hasNotificationPerm.asStateFlow()

    init {
        refreshPendingIncidents()
    }

    // ─── Pending & Unresolved Incidents ─────────────────────────────────────────

    private val _unresolvedIncidents = MutableStateFlow<List<PendingIncidentRecord>>(emptyList())
    val unresolvedIncidents: StateFlow<List<PendingIncidentRecord>> = _unresolvedIncidents.asStateFlow()

    val hasPendingIncidents: StateFlow<Boolean> = _unresolvedIncidents
        .map { it.isNotEmpty() }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), false)

    fun refreshPendingIncidents() {
        viewModelScope.launch(Dispatchers.IO) {
            val list = PendingIncidentQueue.getAll(application)
            _unresolvedIncidents.value = list
        }
    }

    fun dismissIncident(triggerId: String) {
        viewModelScope.launch(Dispatchers.IO) {
            PendingIncidentQueue.remove(application, triggerId)
            refreshPendingIncidents()
        }
    }

    // ─── Storage Integrity ─────────────────────────────────────────────────────

    val storageError: StateFlow<String?> = PendingIncidentQueue.storageErrorState

    fun recoverStorage() {
        viewModelScope.launch(Dispatchers.IO) {
            PendingIncidentQueue.resetCorruptedStorage(application)
            refreshPendingIncidents()
        }
    }

    // ─── Login Type ───────────────────────────────────────────────────────────

    enum class LoginType { USER, AUTHORITY }

    private val _loginType = MutableStateFlow(LoginType.USER)
    val loginType: StateFlow<LoginType> = _loginType.asStateFlow()

    // ─── Login ────────────────────────────────────────────────────────────────

    /**
     * Login using badge_number + password (authority/responder path).
     * This issues an HS256 token directly from the HAVEN backend.
     *
     * For regular users (Clerk accounts), the architecture would need to
     * redirect through Clerk's PKCE OAuth flow. For the hackathon scenario,
     * authority and responder accounts are used directly.
     */
    fun loginAuthority(badgeNumber: String, password: String) {
        _loginType.value = LoginType.AUTHORITY
        val currentUrl = urlRepo.getBackendUrl()
        viewModelScope.launch(Dispatchers.IO) {
            _loginState.value = LoginState.Loading
            try {
                val api = getLoginApi(currentUrl)
                val body = mapOf("badge_number" to badgeNumber, "password" to password)
                val response = api.authorityLogin(body)

                if (response.isSuccessful) {
                    val token = response.body()!!
                    tokenRepo.saveToken(
                        accessToken = token.accessToken,
                        userId = token.userId,
                        role = token.role,
                        expiresInSeconds = token.expiresIn
                    )
                    _isAuthenticated.value = true
                    _loginState.value = LoginState.Success(token.userId)
                    Log.d(TAG, "Authority login successful: userId=${token.userId} role=${token.role}")
                    loadTrustedContacts()
                } else {
                    val detail = parseErrorDetail(response, "")
                    val errMsg = when (response.code()) {
                        401 -> if (detail.isNotBlank()) detail else "Invalid credentials. Check badge number and password."
                        403 -> if (detail.isNotBlank()) detail else "Account is inactive. Contact an administrator."
                        404 -> "Server endpoint not found (404) at $currentUrl. Check Server URL."
                        else -> "Login failed (HTTP ${response.code()}): ${if (detail.isNotBlank()) detail else response.message()}"
                    }
                    _loginState.value = LoginState.Error(errMsg)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Authority login exception: ${e.message}", e)
                val cause = e.localizedMessage ?: e.message ?: "Network error"
                _loginState.value = LoginState.Error("Cannot reach $currentUrl ($cause). Check Server URL and connection.")
            }
        }
    }

    /**
     * Login using email + password (regular user path).
     * Calls POST auth/user-login and issues an HS256 "user" role token.
     * This is the primary path for Shake-to-SOS for ordinary users.
     */
    fun loginUser(email: String, password: String) {
        _loginType.value = LoginType.USER
        val currentUrl = urlRepo.getBackendUrl()
        viewModelScope.launch(Dispatchers.IO) {
            _loginState.value = LoginState.Loading
            try {
                val api = getLoginApi(currentUrl)
                val body = mapOf("email" to email, "password" to password)
                val response = api.userLogin(body)

                if (response.isSuccessful) {
                    val token = response.body()!!
                    tokenRepo.saveToken(
                        accessToken = token.accessToken,
                        userId = token.userId,
                        role = "user",
                        expiresInSeconds = token.expiresIn
                    )
                    _isAuthenticated.value = true
                    _loginState.value = LoginState.Success(token.userId)
                    Log.d(TAG, "User login successful: userId=${token.userId}")
                    loadTrustedContacts()
                } else {
                    val detail = parseErrorDetail(response, "")
                    val errMsg = when (response.code()) {
                        401 -> if (detail.isNotBlank()) detail else "Invalid email or password. If you haven't created an account yet, tap 'New user? Create an account' below."
                        403 -> if (detail.isNotBlank()) detail else "Account is inactive. Contact support."
                        404 -> "Server endpoint not found (404) at $currentUrl. Check Server URL."
                        422 -> "Validation error: ${if (detail.isNotBlank()) detail else "Check email and password."}"
                        else -> "Login failed (HTTP ${response.code()}): ${if (detail.isNotBlank()) detail else response.message()}"
                    }
                    _loginState.value = LoginState.Error(errMsg)
                }
            } catch (e: Exception) {
                Log.e(TAG, "User login exception: ${e.message}", e)
                val cause = e.localizedMessage ?: e.message ?: "Network error"
                _loginState.value = LoginState.Error("Cannot reach $currentUrl ($cause). Ensure HAVEN backend is running and reachable on this network.")
            }
        }
    }

    /**
     * Register a new regular user account via POST auth/user-register.
     */
    fun registerUser(email: String, name: String, password: String) {
        val currentUrl = urlRepo.getBackendUrl()
        viewModelScope.launch(Dispatchers.IO) {
            _loginState.value = LoginState.Loading
            try {
                val api = getLoginApi(currentUrl)
                val body = mapOf("email" to email, "name" to name, "password" to password)
                val response = api.userRegister(body)

                if (response.isSuccessful) {
                    val token = response.body()!!
                    tokenRepo.saveToken(
                        accessToken = token.accessToken,
                        userId = token.userId,
                        role = "user",
                        expiresInSeconds = token.expiresIn
                    )
                    _isAuthenticated.value = true
                    _loginState.value = LoginState.Success(token.userId)
                    Log.d(TAG, "User registration successful: userId=${token.userId}")
                    loadTrustedContacts()
                } else {
                    val detail = parseErrorDetail(response, "")
                    val errMsg = when (response.code()) {
                        409 -> if (detail.isNotBlank()) detail else "An account with this email already exists. Please sign in instead."
                        400, 422 -> if (detail.isNotBlank()) detail else "Invalid registration details. Email must be valid and password at least 8 characters."
                        404 -> "Server endpoint not found (404) at $currentUrl. Check Server URL."
                        else -> "Registration failed (HTTP ${response.code()}): ${if (detail.isNotBlank()) detail else response.message()}"
                    }
                    _loginState.value = LoginState.Error(errMsg)
                }
            } catch (e: Exception) {
                Log.e(TAG, "User register exception: ${e.message}", e)
                val cause = e.localizedMessage ?: e.message ?: "Network error"
                _loginState.value = LoginState.Error("Cannot reach $currentUrl ($cause). Ensure HAVEN backend is running and reachable.")
            }
        }
    }

    fun onLogout() {
        _isAuthenticated.value = false
        _trustedContacts.value = emptyList()
        _loginState.value = LoginState.Idle
    }

    // ─── Monitoring ───────────────────────────────────────────────────────────

    fun setMonitoringEnabled(enabled: Boolean) {
        viewModelScope.launch {
            monitoringRepo.setUserEnabled(enabled)
        }
    }

    fun refreshPermissions(hasLocation: Boolean, hasNotification: Boolean) {
        _hasLocationPerm.value = hasLocation
        _hasNotificationPerm.value = hasNotification
        viewModelScope.launch {
            monitoringRepo.updatePermissions(hasLocation, hasNotification)
        }
    }

    // ─── Contacts ─────────────────────────────────────────────────────────────

    fun loadTrustedContacts() {
        val authHeader = tokenRepo.getBearerHeader() ?: return
        val userId = tokenRepo.getUserId() ?: return
        _contactsLoading.value = true

        viewModelScope.launch(Dispatchers.IO) {
            try {
                val apiService = HavenApiClient.build(
                    urlRepo.getBackendUrl(),
                    isDebug = BuildConfig.DEBUG
                )
                val response = apiService.getVoiceSosConfig(authHeader, userId)
                if (response.isSuccessful) {
                    _trustedContacts.value = response.body()?.contacts ?: emptyList()
                    Log.d(TAG, "Loaded ${_trustedContacts.value.size} trusted contacts")
                }
            } catch (e: Exception) {
                Log.w(TAG, "Could not load contacts: ${e.message}")
            } finally {
                _contactsLoading.value = false
            }
        }
    }
}

class MainViewModelFactory(
    private val application: Application,
    private val tokenRepo: SecureTokenRepository,
    private val monitoringRepo: MonitoringStatusRepository,
    private val serverConfigRepo: ServerConfigRepository = ServerConfigRepository(application),
    private val urlRepo: HavenUrlRepository = HavenUrlRepository(application)
) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        @Suppress("UNCHECKED_CAST")
        return MainViewModel(application, tokenRepo, monitoringRepo, serverConfigRepo, urlRepo) as T
    }
}
