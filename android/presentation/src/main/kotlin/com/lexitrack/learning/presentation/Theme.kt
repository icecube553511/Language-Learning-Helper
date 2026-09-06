package com.lexitrack.learning.presentation

import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

val BrandTeal = Color(0xFF087E8B)
val BrandNavy = Color(0xFF274C77)
val BusinessAmber = Color(0xFFB36B00)
val BusinessRed = Color(0xFFB42318)
val BusinessGreen = Color(0xFF2D6A4F)
val Ink = Color(0xFF17222D)
val MutedInk = Color(0xFF52606D)
val WorkSurface = Color(0xFFF4F6F8)
val DividerColor = Color(0xFFD8DEE4)

private val scheme: ColorScheme = lightColorScheme(
    primary = BrandTeal,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFD7F0F1),
    onPrimaryContainer = Color(0xFF073C42),
    secondary = BrandNavy,
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFDCE8F5),
    onSecondaryContainer = Color(0xFF17324E),
    tertiary = BusinessAmber,
    background = WorkSurface,
    onBackground = Ink,
    surface = Color.White,
    onSurface = Ink,
    surfaceVariant = Color(0xFFEDF1F4),
    onSurfaceVariant = MutedInk,
    outline = Color(0xFF71808E),
    outlineVariant = DividerColor,
    error = BusinessRed,
)

@Composable
fun LexiTrackTheme(fontScale: Float, content: @Composable () -> Unit) {
    val scale = fontScale.coerceIn(0.9f, 1.4f)
    MaterialTheme(
        colorScheme = scheme,
        typography = scaledTypography(scale),
        content = content,
    )
}

private fun scaledTypography(scale: Float) = Typography(
    displayLarge = text(42f, 50f, scale, FontWeight.Bold),
    headlineLarge = text(28f, 36f, scale, FontWeight.Bold),
    headlineMedium = text(23f, 31f, scale, FontWeight.SemiBold),
    titleLarge = text(20f, 28f, scale, FontWeight.SemiBold),
    titleMedium = text(18f, 25f, scale, FontWeight.SemiBold),
    bodyLarge = text(18f, 27f, scale),
    bodyMedium = text(16f, 24f, scale),
    labelLarge = text(16f, 22f, scale, FontWeight.SemiBold),
    labelMedium = text(13f, 18f, scale, FontWeight.Medium),
    labelSmall = text(11f, 15f, scale, FontWeight.Medium),
)

private fun text(
    size: Float,
    lineHeight: Float,
    scale: Float,
    weight: FontWeight = FontWeight.Normal,
) = TextStyle(
    fontFamily = FontFamily.SansSerif,
    fontWeight = weight,
    fontSize = (size * scale).sp,
    lineHeight = (lineHeight * scale).sp,
)
