package com.bottrader.ai

import android.Manifest
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.bottrader.ai.ui.*
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        setContent { BotTheme { App(vm) } }
    }
}

private val ICONS: Map<Screen, ImageVector> = mapOf(
    Screen.Dashboard to Icons.Filled.Dashboard, Screen.Robot to Icons.Filled.SmartToy, Screen.Assets to Icons.Filled.ShowChart,
    Screen.Otc to Icons.Filled.Block, Screen.News to Icons.Filled.Newspaper, Screen.Strategies to Icons.Filled.Psychology,
    Screen.History to Icons.Filled.History, Screen.Stats to Icons.Filled.BarChart, Screen.Risk to Icons.Filled.Shield,
    Screen.Settings to Icons.Filled.Settings,
)
private val BOTTOM = listOf(Screen.Dashboard, Screen.Robot, Screen.Assets, Screen.News)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun App(vm: MainViewModel) {
    val ui by vm.ui.collectAsStateWithLifecycle()
    val ctx = LocalContext.current
    LaunchedEffect(ui.toast) { ui.toast?.let { Toast.makeText(ctx, it, Toast.LENGTH_SHORT).show(); vm.consumeToast() } }
    if (!ui.loggedIn) { LoginScreen(ui, vm); return }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    BackHandler(enabled = ui.screen != Screen.Dashboard || drawer.isOpen) {
        if (drawer.isOpen) scope.launch { drawer.close() } else vm.go(Screen.Dashboard)
    }
    ModalNavigationDrawer(drawerState = drawer, drawerContent = {
        ModalDrawerSheet(drawerContainerColor = C.Card) {
            Text("BOT TRADER AI", fontWeight = FontWeight.ExtraBold, fontSize = 20.sp, modifier = Modifier.padding(20.dp))
            Screen.entries.forEach { s ->
                NavigationDrawerItem(label = { Text(s.title) }, icon = { Icon(ICONS.getValue(s), null) }, selected = ui.screen == s,
                    onClick = { vm.go(s); scope.launch { drawer.close() } }, modifier = Modifier.padding(horizontal = 10.dp))
            }
        }
    }) {
        Scaffold(containerColor = C.Bg,
            topBar = {
                TopAppBar(title = { Text(ui.screen.title, fontWeight = FontWeight.Bold) },
                    navigationIcon = { IconButton({ scope.launch { drawer.open() } }) { Icon(Icons.Filled.Menu, "menu") } },
                    actions = {
                        Row(Modifier.padding(end = 12.dp)) { Dot(ui.wsConnected); Spacer(Modifier.width(6.dp))
                            Text(ui.rttMs?.let { "$it ms" } ?: "—", fontSize = 12.sp, color = latColor(ui.rttMs)) }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = C.Bg, titleContentColor = C.Ink, navigationIconContentColor = C.Ink))
            },
            bottomBar = {
                NavigationBar(containerColor = C.Card) {
                    BOTTOM.forEach { s -> NavigationBarItem(selected = ui.screen == s, onClick = { vm.go(s) }, icon = { Icon(ICONS.getValue(s), null) },
                        label = { Text(s.title.substringBefore(' '), fontSize = 11.sp) }) }
                    NavigationBarItem(selected = ui.screen !in BOTTOM, onClick = { scope.launch { drawer.open() } }, icon = { Icon(Icons.Filled.MoreHoriz, null) },
                        label = { Text("Mais", fontSize = 11.sp) })
                }
            }) { pad ->
            Column(Modifier.fillMaxSize().background(C.Bg).padding(pad).verticalScroll(rememberScrollState()).padding(12.dp)) {
                ui.error?.let { Panel { Note(it, C.Down) } }
                when (ui.screen) {
                    Screen.Dashboard -> DashboardScreen(ui, vm)
                    Screen.Robot -> RobotScreen(ui, vm)
                    Screen.Assets -> AssetsScreen(ui)
                    Screen.Otc -> OtcScreen(ui)
                    Screen.News -> NewsScreen(ui)
                    Screen.Strategies -> StrategiesScreen(ui, vm)
                    Screen.History -> HistoryScreen(ui)
                    Screen.Stats -> StatsScreen(ui)
                    Screen.Risk -> RiskScreen(ui, vm)
                    Screen.Settings -> SettingsScreen(ui, vm)
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}
