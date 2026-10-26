package io.github.projectbarry.onicompanion.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Dark = darkColorScheme(
    primary = Color(0xFF4CC9B0), onPrimary = Color(0xFF00201A),
    background = Color(0xFF101B20), onBackground = Color(0xFFE3EEF0),
    surface = Color(0xFF16262D), onSurface = Color(0xFFE3EEF0),
    surfaceVariant = Color(0xFF1F343C), onSurfaceVariant = Color(0xFFA9C0C6),
    error = Color(0xFFFF8A80),
)
private val Light = lightColorScheme(
    primary = Color(0xFF00695C), onPrimary = Color.White,
    background = Color(0xFFF4F8F8), onBackground = Color(0xFF111C1F),
    surface = Color.White, onSurface = Color(0xFF111C1F),
    surfaceVariant = Color(0xFFE2ECEE), onSurfaceVariant = Color(0xFF3F5559),
    error = Color(0xFFB3261E),
)

@Composable
fun OniTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = if (isSystemInDarkTheme()) Dark else Light, content = content)
}
