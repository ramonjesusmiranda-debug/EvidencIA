package com.evidencia.app

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

private val Light = lightColorScheme(primary = Color(0xFF00696B), secondary = Color(0xFF4A6363), tertiary = Color(0xFF4B607C))
private val Dark = darkColorScheme(primary = Color(0xFF4CDADC), secondary = Color(0xFFB0CCCC), tertiary = Color(0xFFB3C8E8))

/** Material You: colores dinámicos del fondo de pantalla en Android 12+, paleta teal en versiones anteriores. */
@Composable
fun EvidenciaTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val ctx = LocalContext.current
    val scheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> if (dark) dynamicDarkColorScheme(ctx) else dynamicLightColorScheme(ctx)
        dark -> Dark
        else -> Light
    }
    MaterialTheme(colorScheme = scheme, content = content)
}
