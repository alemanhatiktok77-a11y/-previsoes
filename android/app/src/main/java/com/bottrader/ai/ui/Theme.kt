package com.bottrader.ai.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

object C {
    val Bg = Color(0xFF0B0F14); val Card = Color(0xFF121821); val Card2 = Color(0xFF0E141C); val Line = Color(0xFF1E2833)
    val Ink = Color(0xFFE6EDF5); val Mut = Color(0xFF7D8B9C); val Up = Color(0xFF22D39A); val Down = Color(0xFFF2545B)
    val Acc = Color(0xFF3D8BFF); val Warn = Color(0xFFF5A524)
}

private val scheme = darkColorScheme(primary = C.Acc, onPrimary = Color.White, background = C.Bg, surface = C.Card,
    onSurface = C.Ink, onBackground = C.Ink, surfaceVariant = C.Card2, outline = C.Line, error = C.Down)

@Composable
fun BotTheme(content: @Composable () -> Unit) = MaterialTheme(colorScheme = scheme, content = content)

@Composable
fun Panel(title: String? = null, trailing: (@Composable () -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().padding(bottom = 10.dp).clip(RoundedCornerShape(14.dp)).background(C.Card)
        .border(1.dp, C.Line, RoundedCornerShape(14.dp)).padding(14.dp)) {
        if (title != null) Row(Modifier.fillMaxWidth().padding(bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(title, fontWeight = FontWeight.Bold, fontSize = 15.sp, color = C.Ink, modifier = Modifier.weight(1f)); trailing?.invoke()
        }
        content()
    }
}

@Composable
fun Kpi(label: String, value: String, modifier: Modifier = Modifier, color: Color = C.Ink) {
    Column(modifier.clip(RoundedCornerShape(10.dp)).background(C.Card2).padding(horizontal = 10.dp, vertical = 8.dp)) {
        Text(label.uppercase(), fontSize = 10.sp, color = C.Mut, letterSpacing = 0.4.sp, maxLines = 1)
        Text(value, fontSize = 17.sp, fontWeight = FontWeight.Bold, color = color, fontFamily = FontFamily.Monospace, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

@Composable
fun Tag(text: String, color: Color) {
    Text(text, color = color, fontSize = 11.sp, fontWeight = FontWeight.Bold,
        modifier = Modifier.clip(RoundedCornerShape(20.dp)).background(color.copy(alpha = 0.15f)).padding(horizontal = 8.dp, vertical = 3.dp))
}

@Composable
fun Dot(ok: Boolean?) {
    Box(Modifier.size(9.dp).clip(CircleShape).background(when (ok) { true -> C.Up; false -> C.Down; null -> C.Mut }))
}

@Composable
fun Line(left: String, right: String, rightColor: Color = C.Mut) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(left, color = C.Ink, fontSize = 13.5.sp, modifier = Modifier.weight(1f))
        Text(right, color = rightColor, fontSize = 12.5.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}

@Composable fun Note(text: String, color: Color = C.Mut) = Text(text, color = color, fontSize = 12.5.sp, lineHeight = 18.sp)

fun pct(x: Double?, d: Int = 1): String = if (x == null) "—" else String.format(Locale("pt", "BR"), "%.${d}f%%", x * 100)
fun money(x: Double): String = String.format(Locale("pt", "BR"), "%,.2f", x)
fun hhmmss(t: Long): String = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date(t))
fun dateTime(t: Long): String = SimpleDateFormat("dd/MM HH:mm", Locale.getDefault()).format(Date(t))
fun sym(s: String) = s.substringBefore('@')
fun statusColor(s: String) = when (s) { "WIN" -> C.Up; "LOSS" -> C.Down; "PENDING", "OPEN" -> C.Acc; else -> C.Mut }
