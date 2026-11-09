package com.haven.android.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * LoginScreen
 *
 * Authentication screen for HAVEN Android app.
 *
 * Supports two login paths:
 *   1. User Login  — email + password → POST auth/user-login (primary, for Shake-to-SOS)
 *   2. Authority Login — badge_number + password → POST auth/authority-login
 *
 * Features:
 * - Tab selector to switch between User and Authority modes.
 * - Dynamic Backend Server URL configuration card so the user can connect
 *   to local Wi-Fi IP, emulator, or production server.
 * - Clear error diagnostics showing actionable feedback if connection fails.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LoginScreen(viewModel: MainViewModel) {
    val loginState by viewModel.loginState.collectAsState()
    val currentServerUrl by viewModel.serverUrl.collectAsState()
    val currentFrontendUrl by viewModel.frontendUrl.collectAsState()
    val currentWsUrl by viewModel.wsUrl.collectAsState()

    // Tab selection: 0 = User Login, 1 = Authority Login
    var selectedTab by remember { mutableStateOf(0) }

    // User login / register fields
    var email by remember { mutableStateOf("") }
    var name by remember { mutableStateOf("") }
    var userPassword by remember { mutableStateOf("") }
    var userPasswordVisible by remember { mutableStateOf(false) }
    var isRegisterMode by remember { mutableStateOf(false) }

    // Authority login fields
    var badgeNumber by remember { mutableStateOf("") }
    var authorityPassword by remember { mutableStateOf("") }
    var authorityPasswordVisible by remember { mutableStateOf(false) }

    // Server config fields
    var showServerConfig by remember { mutableStateOf(false) }
    var customUrlInput by remember(currentServerUrl) { mutableStateOf(currentServerUrl) }
    var customFrontendInput by remember(currentFrontendUrl) { mutableStateOf(currentFrontendUrl) }
    var customWsInput by remember(currentWsUrl) { mutableStateOf(currentWsUrl) }

    val isLoading = loginState is MainViewModel.LoginState.Loading
    val errorMessage = (loginState as? MainViewModel.LoginState.Error)?.message

    val scrollState = rememberScrollState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(scrollState)
            .padding(horizontal = 24.dp, vertical = 32.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        // ── Logo / Title ───────────────────────────────────────────────────────
        Text(
            text = "🛡️ HAVEN",
            fontSize = 38.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary
        )
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = "Women's Safety Platform",
            fontSize = 15.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Spacer(modifier = Modifier.height(24.dp))

        // ── Tab Selector ───────────────────────────────────────────────────────
        TabRow(selectedTabIndex = selectedTab) {
            Tab(
                selected = selectedTab == 0,
                onClick = { selectedTab = 0; isRegisterMode = false },
                text = { Text("User Login") }
            )
            Tab(
                selected = selectedTab == 1,
                onClick = { selectedTab = 1 },
                text = { Text("Authority Login") }
            )
        }

        Spacer(modifier = Modifier.height(20.dp))

        when (selectedTab) {
            // ── User Login / Register ──────────────────────────────────────────
            0 -> {
                if (isRegisterMode) {
                    // Registration Mode Header
                    Text(
                        text = "Create a New HAVEN Account",
                        fontWeight = FontWeight.SemiBold,
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(modifier = Modifier.height(12.dp))

                    // Name field (register only)
                    OutlinedTextField(
                        value = name,
                        onValueChange = { name = it },
                        label = { Text("Full Name") },
                        leadingIcon = { Icon(Icons.Default.Person, contentDescription = null) },
                        modifier = Modifier.fillMaxWidth(),
                        enabled = !isLoading,
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text)
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                }

                // Email field
                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it },
                    label = { Text("Email Address") },
                    leadingIcon = { Icon(Icons.Default.Email, contentDescription = null) },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !isLoading,
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email)
                )
                Spacer(modifier = Modifier.height(12.dp))

                // Password field
                OutlinedTextField(
                    value = userPassword,
                    onValueChange = { userPassword = it },
                    label = { Text(if (isRegisterMode) "Password (min 8 chars)" else "Password") },
                    leadingIcon = { Icon(Icons.Default.Lock, contentDescription = null) },
                    trailingIcon = {
                        IconButton(onClick = { userPasswordVisible = !userPasswordVisible }) {
                            Icon(
                                imageVector = if (userPasswordVisible) Icons.Default.VisibilityOff
                                              else Icons.Default.Visibility,
                                contentDescription = if (userPasswordVisible) "Hide password" else "Show password"
                            )
                        }
                    },
                    visualTransformation = if (userPasswordVisible) VisualTransformation.None
                                           else PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !isLoading,
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password)
                )

                // Error Message Card
                errorMessage?.let {
                    Spacer(modifier = Modifier.height(12.dp))
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.errorContainer
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(
                            modifier = Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "⚠️ $it",
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(20.dp))

                if (isRegisterMode) {
                    // Register button
                    Button(
                        onClick = { viewModel.registerUser(email.trim(), name.trim(), userPassword) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(50.dp),
                        enabled = !isLoading && email.isNotBlank() && name.isNotBlank() && userPassword.isNotBlank()
                    ) {
                        if (isLoading) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                color = MaterialTheme.colorScheme.onPrimary,
                                strokeWidth = 2.dp
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("Registering…")
                        } else {
                            Text("Create Account")
                        }
                    }
                    Spacer(modifier = Modifier.height(10.dp))
                    TextButton(onClick = { isRegisterMode = false }) {
                        Text("Already have an account? Sign In")
                    }
                } else {
                    // Sign In button
                    Button(
                        onClick = { viewModel.loginUser(email.trim(), userPassword) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(50.dp),
                        enabled = !isLoading && email.isNotBlank() && userPassword.isNotBlank()
                    ) {
                        if (isLoading) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                color = MaterialTheme.colorScheme.onPrimary,
                                strokeWidth = 2.dp
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text("Signing in…")
                        } else {
                            Text("Sign In")
                        }
                    }
                    Spacer(modifier = Modifier.height(10.dp))
                    TextButton(onClick = { isRegisterMode = true }) {
                        Text("New user? Create an account")
                    }
                }
            }

            // ── Authority Login ────────────────────────────────────────────────
            1 -> {
                // Badge Number field
                OutlinedTextField(
                    value = badgeNumber,
                    onValueChange = { badgeNumber = it },
                    label = { Text("Badge Number") },
                    leadingIcon = { Icon(Icons.Default.Person, contentDescription = null) },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !isLoading,
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text)
                )
                Spacer(modifier = Modifier.height(12.dp))

                // Password field
                OutlinedTextField(
                    value = authorityPassword,
                    onValueChange = { authorityPassword = it },
                    label = { Text("Password") },
                    leadingIcon = { Icon(Icons.Default.Lock, contentDescription = null) },
                    trailingIcon = {
                        IconButton(onClick = { authorityPasswordVisible = !authorityPasswordVisible }) {
                            Icon(
                                imageVector = if (authorityPasswordVisible) Icons.Default.VisibilityOff
                                              else Icons.Default.Visibility,
                                contentDescription = if (authorityPasswordVisible) "Hide password" else "Show password"
                            )
                        }
                    },
                    visualTransformation = if (authorityPasswordVisible) VisualTransformation.None
                                           else PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !isLoading,
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password)
                )

                errorMessage?.let {
                    Spacer(modifier = Modifier.height(12.dp))
                    Card(
                        colors = CardDefaults.cardColors(
                            containerColor = MaterialTheme.colorScheme.errorContainer
                        ),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Row(
                            modifier = Modifier.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text(
                                text = "⚠️ $it",
                                color = MaterialTheme.colorScheme.onErrorContainer,
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(20.dp))

                Button(
                    onClick = { viewModel.loginAuthority(badgeNumber.trim(), authorityPassword) },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(50.dp),
                    enabled = !isLoading && badgeNumber.isNotBlank() && authorityPassword.isNotBlank()
                ) {
                    if (isLoading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            color = MaterialTheme.colorScheme.onPrimary,
                            strokeWidth = 2.dp
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("Signing in…")
                    } else {
                        Text("Authority Sign In")
                    }
                }
            }
        }

        // ── Server URL Settings Card (Strictly isolated to DEBUG builds) ───────────────
        if (com.haven.android.BuildConfig.DEBUG) {
            Spacer(modifier = Modifier.height(24.dp))
            Card(
                modifier = Modifier.fillMaxWidth(),
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f)
                )
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                imageVector = Icons.Default.Settings,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                                tint = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Spacer(modifier = Modifier.width(6.dp))
                            Text(
                                text = "Developer Server Config",
                                style = MaterialTheme.typography.labelMedium,
                                fontWeight = FontWeight.SemiBold
                            )
                        }
                        TextButton(onClick = { showServerConfig = !showServerConfig }) {
                            Text(if (showServerConfig) "Hide" else "Change")
                        }
                    }

                    // Summary line showing current URLs
                    Text(
                        text = "API: $currentServerUrl",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                        fontWeight = FontWeight.Medium
                    )
                    Text(
                        text = "Web: $currentFrontendUrl",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.secondary
                    )

                    if (showServerConfig) {
                        Spacer(modifier = Modifier.height(12.dp))

                        // ── Backend API URL ────────────────────────────────────────
                        Text(
                            "Backend API URL",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        OutlinedTextField(
                            value = customUrlInput,
                            onValueChange = { customUrlInput = it },
                            label = { Text("Backend URL (FastAPI)") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            placeholder = { Text("https://haven-power-for-women.onrender.com") }
                        )
                        Spacer(modifier = Modifier.height(8.dp))

                        // ── Frontend URL ───────────────────────────────────────────
                        Text(
                            "Frontend URL",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        OutlinedTextField(
                            value = customFrontendInput,
                            onValueChange = { customFrontendInput = it },
                            label = { Text("Frontend URL (Next.js)") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            placeholder = { Text("https://haven-your-own-voice.vercel.app") }
                        )
                        Spacer(modifier = Modifier.height(8.dp))

                        // ── WebSocket URL ──────────────────────────────────────────
                        Text(
                            "WebSocket URL",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        OutlinedTextField(
                            value = customWsInput,
                            onValueChange = { customWsInput = it },
                            label = { Text("WebSocket URL (auto-derived if blank)") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true,
                            placeholder = { Text("wss://haven-power-for-women.onrender.com") }
                        )
                        Spacer(modifier = Modifier.height(10.dp))

                        // ── Action Buttons ─────────────────────────────────────────
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            Button(
                                onClick = {
                                    viewModel.setBackendUrl(customUrlInput)
                                    viewModel.setFrontendUrl(customFrontendInput)
                                    if (customWsInput.isNotBlank()) {
                                        viewModel.setWsUrl(customWsInput)
                                    } else {
                                        viewModel.clearWsOverride()
                                    }
                                    showServerConfig = false
                                },
                                modifier = Modifier.weight(1f)
                            ) {
                                Text("Apply")
                            }

                            OutlinedButton(
                                onClick = {
                                    viewModel.applyLocalPreset()
                                    customUrlInput = "https://haven-power-for-women.onrender.com"
                                    customFrontendInput = "https://haven-your-own-voice.vercel.app"
                                    customWsInput = "wss://haven-power-for-women.onrender.com"
                                    showServerConfig = false
                                }
                            ) {
                                Text("Reset")
                            }
                        }
                    }
                }
            }
        }
    }
}
