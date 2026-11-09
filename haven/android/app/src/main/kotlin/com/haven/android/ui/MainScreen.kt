package com.haven.android.ui

import android.net.Uri
import android.webkit.ValueCallback
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.haven.android.data.MonitoringStatus
import com.haven.android.data.PendingIncidentRecord
import com.haven.android.data.PendingIncidentStatus
import com.haven.android.data.TrustedContact

/**
 * MainScreen
 *
 * The primary authenticated UI screen for HAVEN Android.
 *
 * Layout: BottomNavigationBar with two tabs:
 *   1. 🌐 Website — full-screen WebView of the HAVEN website (the same site users see in their browser)
 *   2. 🛡️ Monitor — native Shake-to-SOS controls, permissions, diagnostics
 *
 * The WebView embeds the actual HAVEN frontend running at [frontendUrl].
 * The Monitor tab preserves all existing native shake detection functionality.
 *
 * @param frontendUrl              The local Next.js server URL (e.g. http://192.168.1.8:3000)
 * @param fileChooserCallback      Mutable state shared with MainActivity for file picker results
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    viewModel: MainViewModel,
    frontendUrl: String,
    fileChooserCallback: MutableState<ValueCallback<Array<Uri>>?>,
    onRequestLocationPermission: ((Boolean) -> Unit) -> Unit,
    onRequestNotificationPermission: ((Boolean) -> Unit) -> Unit,
    onStartMonitoring: () -> Unit,
    onStopMonitoring: () -> Unit,
    onStartTest: () -> Unit,
    onLogout: () -> Unit
) {
    // 0 = Website, 1 = Monitor
    var selectedTab by remember { mutableStateOf(0) }
    val monitoringStatus by viewModel.monitoringStatus.collectAsState()
    val hasLocationPerm by viewModel.hasLocationPerm.collectAsState()
    val hasNotificationPerm by viewModel.hasNotificationPerm.collectAsState()

    Scaffold(
        bottomBar = {
            NavigationBar {
                NavigationBarItem(
                    selected = selectedTab == 0,
                    onClick = { selectedTab = 0 },
                    icon = { Icon(Icons.Default.Language, contentDescription = null) },
                    label = { Text("Website") }
                )
                NavigationBarItem(
                    selected = selectedTab == 1,
                    onClick = { selectedTab = 1 },
                    icon = {
                        // Show green dot badge when monitoring is active
                        BadgedBox(badge = {
                            if (monitoringStatus.isActuallyMonitoring) {
                                Badge(containerColor = Color(0xFF2E7D32))
                            }
                        }) {
                            Icon(Icons.Default.Shield, contentDescription = null)
                        }
                    },
                    label = { Text("Monitor") }
                )
            }
        }
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
        ) {
            when (selectedTab) {
                0 -> {
                    // ── Website Tab ───────────────────────────────────────────
                    HavenWebViewScreen(
                        frontendUrl = frontendUrl,
                        viewModel = viewModel,
                        onRequestPermissions = {
                            onRequestLocationPermission { granted ->
                                viewModel.refreshPermissions(granted, hasNotificationPerm)
                            }
                        },
                        onStartService = onStartMonitoring,
                        onStopService = onStopMonitoring,
                        fileChooserCallback = fileChooserCallback
                    )
                }
                1 -> {
                    // ── Monitor Tab ───────────────────────────────────────────
                    MonitorTabContent(
                        viewModel = viewModel,
                        onRequestLocationPermission = onRequestLocationPermission,
                        onRequestNotificationPermission = onRequestNotificationPermission,
                        onStartMonitoring = onStartMonitoring,
                        onStopMonitoring = onStopMonitoring,
                        onStartTest = onStartTest,
                        onLogout = onLogout
                    )
                }
            }
        }
    }
}

/**
 * MonitorTabContent — the original MainScreen content moved into the Monitor tab.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MonitorTabContent(
    viewModel: MainViewModel,
    onRequestLocationPermission: ((Boolean) -> Unit) -> Unit,
    onRequestNotificationPermission: ((Boolean) -> Unit) -> Unit,
    onStartMonitoring: () -> Unit,
    onStopMonitoring: () -> Unit,
    onStartTest: () -> Unit,
    onLogout: () -> Unit
) {
    val monitoringStatus by viewModel.monitoringStatus.collectAsState()
    val trustedContacts by viewModel.trustedContacts.collectAsState()
    val contactsLoading by viewModel.contactsLoading.collectAsState()
    val hasLocationPerm by viewModel.hasLocationPerm.collectAsState()
    val hasNotificationPerm by viewModel.hasNotificationPerm.collectAsState()
    val unresolvedIncidents by viewModel.unresolvedIncidents.collectAsState()
    val storageError by viewModel.storageError.collectAsState()

    var showTestConfirm by remember { mutableStateOf(false) }
    var showStopConfirm by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text("🛡️ HAVEN", fontWeight = FontWeight.Bold)
                },
                actions = {
                    IconButton(onClick = onLogout) {
                        Icon(Icons.AutoMirrored.Filled.Logout, contentDescription = "Log out")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer
                )
            )
        }
    ) { paddingValues ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues)
                .padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
            contentPadding = PaddingValues(vertical = 16.dp)
        ) {
            // ── Monitoring Status ────────────────────────────────────────────
            item {
                MonitoringStatusCard(monitoringStatus)
            }

            // ── Storage Integrity Warning ────────────────────────────────────
            storageError?.let { err ->
                item {
                    StorageIntegrityAlertCard(
                        errorMessage = err,
                        onRecover = { viewModel.recoverStorage() }
                    )
                }
            }

            // ── Unresolved SOS Incidents ─────────────────────────────────────
            if (unresolvedIncidents.isNotEmpty()) {
                item {
                    UnresolvedIncidentsSection(
                        incidents = unresolvedIncidents,
                        onDismiss = { triggerId -> viewModel.dismissIncident(triggerId) }
                    )
                }
            }

            // ── Permissions ─────────────────────────────────────────────────
            item {
                PermissionsCard(
                    hasLocation = hasLocationPerm,
                    hasNotification = hasNotificationPerm,
                    onRequestLocation = { onRequestLocationPermission { granted ->
                        viewModel.refreshPermissions(granted, hasNotificationPerm)
                    }},
                    onRequestNotification = { onRequestNotificationPermission { granted ->
                        viewModel.refreshPermissions(hasLocationPerm, granted)
                    }}
                )
            }

            // ── Start/Stop Monitoring ────────────────────────────────────────
            item {
                val canStart = hasLocationPerm && hasNotificationPerm
                MonitoringControlCard(
                    status = monitoringStatus,
                    canStart = canStart,
                    onStart = {
                        viewModel.setMonitoringEnabled(true)
                        onStartMonitoring()
                    },
                    onStop = { showStopConfirm = true }
                )
            }

            // ── Test Mode ────────────────────────────────────────────────────
            item {
                TestModeCard(onStartTest = { showTestConfirm = true })
            }

            // ── Platform Limitations Disclosure ──────────────────────────────
            item {
                PlatformLimitationsCard()
            }

            // ── Trusted Contacts ────────────────────────────────────────────
            item {
                Text(
                    "Trusted Contacts",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
            }
            if (contactsLoading) {
                item { CircularProgressIndicator(modifier = Modifier.padding(8.dp)) }
            } else if (trustedContacts.isEmpty()) {
                item {
                    Card {
                        Text(
                            "No trusted contacts configured. Open HAVEN web app to add contacts.",
                            modifier = Modifier.padding(16.dp),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            } else {
                items(trustedContacts) { contact ->
                    TrustedContactItem(contact)
                }
            }

            // ── Diagnostics ──────────────────────────────────────────────────
            item {
                DiagnosticsCard(monitoringStatus)
            }
        }
    }

    // ── Stop confirmation dialog ─────────────────────────────────────────────
    if (showStopConfirm) {
        AlertDialog(
            onDismissRequest = { showStopConfirm = false },
            title = { Text("Stop Monitoring?") },
            text = { Text("This will stop Shake-to-SOS detection. You will not be monitored until you restart it.") },
            confirmButton = {
                TextButton(onClick = {
                    showStopConfirm = false
                    viewModel.setMonitoringEnabled(false)
                    onStopMonitoring()
                }) { Text("Stop", color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = {
                TextButton(onClick = { showStopConfirm = false }) { Text("Cancel") }
            }
        )
    }

    // ── Test confirmation dialog ─────────────────────────────────────────────
    if (showTestConfirm) {
        AlertDialog(
            onDismissRequest = { showTestConfirm = false },
            title = { Text("⚠️ Start Shake Test") },
            text = {
                Text(
                    "This is a DETECTOR TEST ONLY.\n\n" +
                    "• Shake your phone three times.\n" +
                    "• This will NOT notify real trusted contacts.\n" +
                    "• This will NOT create a real emergency incident.\n" +
                    "• A test entry will be submitted to the staging backend.\n\n" +
                    "Proceed with the test?"
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    showTestConfirm = false
                    onStartTest()
                }) { Text("Start Test") }
            },
            dismissButton = {
                TextButton(onClick = { showTestConfirm = false }) { Text("Cancel") }
            }
        )
    }
}

@Composable
private fun MonitoringStatusCard(status: MonitoringStatus) {
    val (color, icon, title, subtitle) = when {
        status.isActuallyMonitoring -> Quadruple(
            Color(0xFF2E7D32), Icons.Default.Shield,
            "🟢 Monitoring Active",
            "Shake 3× to trigger SOS — works with screen locked"
        )
        status.userEnabled && !status.serviceRunning -> Quadruple(
            Color(0xFFF57F17), Icons.Default.Warning,
            "⚠️ Monitoring Interrupted",
            "Service was stopped by the OS. Tap 'Restart Monitoring' to resume."
        )
        else -> Quadruple(
            Color(0xFFC62828), Icons.Default.ShieldMoon,
            "🔴 Monitoring Inactive",
            "Enable monitoring to activate Shake-to-SOS protection"
        )
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = color.copy(alpha = 0.12f)),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier.padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(40.dp))
            Spacer(modifier = Modifier.width(16.dp))
            Column {
                Text(title, fontWeight = FontWeight.Bold, fontSize = 16.sp, color = color)
                Text(subtitle, style = MaterialTheme.typography.bodySmall,
                     color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun PermissionsCard(
    hasLocation: Boolean,
    hasNotification: Boolean,
    onRequestLocation: () -> Unit,
    onRequestNotification: () -> Unit
) {
    if (hasLocation && hasNotification) return  // All granted — don't show card

    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.3f)
        ),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Required Permissions", fontWeight = FontWeight.Bold,
                 style = MaterialTheme.typography.titleSmall)
            Spacer(modifier = Modifier.height(8.dp))

            if (!hasLocation) {
                PermissionRow(
                    label = "📍 Location (for GPS in SOS)",
                    rationale = "Sends your GPS coordinates with the emergency to help authorities find you.",
                    granted = false,
                    onRequest = onRequestLocation
                )
            }
            if (!hasNotification) {
                Spacer(modifier = Modifier.height(8.dp))
                PermissionRow(
                    label = "🔔 Notifications (for monitoring indicator)",
                    rationale = "Required to show the persistent notification that indicates monitoring is active.",
                    granted = false,
                    onRequest = onRequestNotification
                )
            }
        }
    }
}

@Composable
private fun PermissionRow(label: String, rationale: String, granted: Boolean, onRequest: () -> Unit) {
    Column {
        Text(label, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
        Text(rationale, style = MaterialTheme.typography.bodySmall,
             color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(modifier = Modifier.height(4.dp))
        OutlinedButton(onClick = onRequest, modifier = Modifier.fillMaxWidth()) {
            Text(if (granted) "✓ Granted" else "Grant Permission")
        }
    }
}

@Composable
private fun MonitoringControlCard(
    status: MonitoringStatus,
    canStart: Boolean,
    onStart: () -> Unit,
    onStop: () -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("Shake-to-SOS Control", style = MaterialTheme.typography.titleSmall,
                 fontWeight = FontWeight.Bold)
            Spacer(modifier = Modifier.height(12.dp))

            if (status.isActuallyMonitoring) {
                Button(
                    onClick = onStop,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error
                    )
                ) {
                    Icon(Icons.Default.Stop, contentDescription = null)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Stop Monitoring")
                }
            } else {
                Button(
                    onClick = onStart,
                    modifier = Modifier.fillMaxWidth(),
                    enabled = canStart
                ) {
                    Icon(Icons.Default.PlayArrow, contentDescription = null)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text(
                        if (status.userEnabled && !status.serviceRunning)
                            "Restart Monitoring"
                        else
                            "Start Monitoring"
                    )
                }
                if (!canStart) {
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        "Grant location and notification permissions above to enable monitoring.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

@Composable
private fun TestModeCard(onStartTest: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.tertiaryContainer.copy(alpha = 0.5f)
        ),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("🧪 Shake Detector Test", fontWeight = FontWeight.Bold,
                 style = MaterialTheme.typography.titleSmall)
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                "Safely test the shake detection without triggering a real SOS. " +
                "Trusted contacts will NOT be notified. A test record will be created.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(modifier = Modifier.height(12.dp))
            OutlinedButton(onClick = onStartTest, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Default.Science, contentDescription = null)
                Spacer(modifier = Modifier.width(8.dp))
                Text("Run Shake Test")
            }
        }
    }
}

@Composable
private fun PlatformLimitationsCard() {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        ),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("ℹ️ Android Platform Limitations", fontWeight = FontWeight.Bold,
                 style = MaterialTheme.typography.titleSmall)
            Spacer(modifier = Modifier.height(8.dp))
            val items = listOf(
                "Screen locked: ✅ Service continues while screen is locked (foreground service + WakeLock)",
                "Background: ✅ Service runs while the app is in the background",
                "App removed from Recents: ✅ Service continues (stopWithTask=false)",
                "OS memory pressure: ⚠️ Android may terminate the service; it will auto-restart",
                "OEM battery saver (MIUI/EMUI): ⚠️ Aggressive OEM optimisations may kill the service",
                "Force-stop via Settings: ❌ Cannot detect shakes — all processes are terminated. Re-open HAVEN to restart."
            )
            items.forEach { item ->
                Text("• $item", style = MaterialTheme.typography.bodySmall,
                     modifier = Modifier.padding(vertical = 2.dp))
            }
        }
    }
}

@Composable
private fun TrustedContactItem(contact: TrustedContact) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(Icons.Default.Person, contentDescription = null,
                 tint = MaterialTheme.colorScheme.primary)
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(contact.name, fontWeight = FontWeight.Medium)
                Text(contact.phone, style = MaterialTheme.typography.bodySmall,
                     color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(
                "Priority ${contact.priority}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary
            )
        }
    }
}

@Composable
private fun DiagnosticsCard(status: MonitoringStatus) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("🔍 Diagnostics", fontWeight = FontWeight.Bold,
                 style = MaterialTheme.typography.titleSmall)
            Spacer(modifier = Modifier.height(8.dp))

            val heartbeatAge = if (status.lastHeartbeatMs > 0)
                "${(System.currentTimeMillis() - status.lastHeartbeatMs) / 1000}s ago"
            else "Never"

            DiagRow("User enabled monitoring", status.userEnabled.toString())
            DiagRow("Service actually running", status.serviceRunning.toString())
            DiagRow("Location permission", status.locationPermissionGranted.toString())
            DiagRow("Notification permission", status.notificationPermissionGranted.toString())
            DiagRow("Last heartbeat", heartbeatAge)
            DiagRow("Current shake count", "${status.shakeCount} / 3")
        }
    }
}

@Composable
private fun DiagRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(label, style = MaterialTheme.typography.bodySmall,
             color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun StorageIntegrityAlertCard(
    errorMessage: String,
    onRecover: () -> Unit
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer
        ),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Default.Warning,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(24.dp)
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    "Local Storage Alert",
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onErrorContainer
                )
            }
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                "Offline emergency persistence warning:\n$errorMessage\n\nShake-to-SOS will attempt direct network delivery, but offline queueing may fail until storage is recovered.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer
            )
            Spacer(modifier = Modifier.height(8.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                OutlinedButton(onClick = onRecover) {
                    Text("Attempt Storage Recovery")
                }
            }
        }
    }
}

@Composable
private fun UnresolvedIncidentsSection(
    incidents: List<PendingIncidentRecord>,
    onDismiss: (String) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            "Incident Queue Status",
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Bold
        )
        for (incident in incidents) {
            val isAttention = incident.status == PendingIncidentStatus.NEEDS_ATTENTION
            val containerColor = if (isAttention) {
                MaterialTheme.colorScheme.errorContainer
            } else {
                MaterialTheme.colorScheme.secondaryContainer
            }
            val title = if (isAttention) {
                "⚠️ Attention Required: ${incident.triggerId}"
            } else {
                "⏳ Pending SOS Delivery: ${incident.triggerId}"
            }
            val desc = if (isAttention) {
                incident.failureReason ?: "Submission blocked by server (validation or auth error)"
            } else {
                "Stored in encrypted write-ahead log. Retries: ${incident.attemptCount}"
            }

            Card(
                colors = CardDefaults.cardColors(containerColor = containerColor),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Text(title, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.bodyMedium)
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(desc, style = MaterialTheme.typography.bodySmall)
                    if (isAttention) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                            TextButton(onClick = { onDismiss(incident.triggerId) }) {
                                Text("Dismiss", color = MaterialTheme.colorScheme.error)
                            }
                        }
                    }
                }
            }
        }
    }
}

// Simple data carrier
private data class Quadruple<A, B, C, D>(val a: A, val b: B, val c: C, val d: D)

// ─── Public entry point for MonitorControlActivity (TWA mode) ─────────────────────────────

/**
 * MonitorTab
 *
 * Public wrapper around MonitorTabContent for use in TWA mode, where the website
 * is hosted in a Trusted Web Activity and monitoring controls are shown in a
 * separate standalone activity (MonitorControlActivity).
 *
 * @param onOpenWebsite  Called when the user taps "Open Haven Website" — launches TwaLauncherActivity.
 */
@Composable
fun MonitorTab(
    viewModel: MainViewModel,
    onRequestLocationPermission: ((Boolean) -> Unit) -> Unit,
    onRequestNotificationPermission: ((Boolean) -> Unit) -> Unit,
    onStartMonitoring: () -> Unit,
    onStopMonitoring: () -> Unit,
    onStartTest: () -> Unit,
    onOpenWebsite: () -> Unit = {}
) {
    MonitorTabContent(
        viewModel = viewModel,
        onRequestLocationPermission = onRequestLocationPermission,
        onRequestNotificationPermission = onRequestNotificationPermission,
        onStartMonitoring = onStartMonitoring,
        onStopMonitoring = onStopMonitoring,
        onStartTest = onStartTest,
        onLogout = onOpenWebsite  // In TWA mode "back to website" replaces logout
    )
}
