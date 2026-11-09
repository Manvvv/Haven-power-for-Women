package com.haven.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val HavenPrimary = Color(0xFF7B1FA2)    // Deep purple
private val HavenSecondary = Color(0xFFAD1457)   // Deep pink
private val HavenTertiary = Color(0xFF00695C)    // Teal

private val LightColorScheme = lightColorScheme(
    primary = HavenPrimary,
    secondary = HavenSecondary,
    tertiary = HavenTertiary,
)

@Composable
fun HavenTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = LightColorScheme,
        content = content
    )
}
