package com.bottrader.ai

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import androidx.core.app.NotificationCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.bottrader.ai.data.*
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.WebSocket

enum class Screen(val title: String) {
    Dashboard("Dashboard"), Robot("Robô automático"), Assets("Ativos"), Otc("OTC"), News("Notícias"),
    Strategies("Estratégias"), History("Histórico"), Stats("Estatísticas"), Risk("Gestão de risco"), Settings("Configurações")
}

data class UiState(
    val loggedIn: Boolean = false,
    val server: String = "",
    val screen: Screen = Screen.Dashboard,
    val busy: Boolean = false,
    val error: String? = null,
    val toast: String? = null,
    val wsConnected: Boolean = false,
    val wsInfo: String = "",
    val rttMs: Long? = null,
    val clockSkewMs: Long? = null,
    val lastServerEventMs: Long = 0,
    val dash: Dashboard? = null,
    val assets: List<AssetDto> = emptyList(),
    val otc: OtcDto? = null,
    val news: NewsResp? = null,
    val strategies: List<StrategyDto> = emptyList(),
    val trades: List<TradeDto> = emptyList(),
    val decisions: List<DecisionDto> = emptyList(),
    val stats: StatsDto? = null,
    val risk: RiskSnap? = null,
    val settings: SettingsDto? = null,
    val livePrices: Map<String, Double> = emptyMap(),
)

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("bot", Context.MODE_PRIVATE)
    private val _ui = MutableStateFlow(UiState(server = prefs.getString("server", "") ?: ""))
    val ui: StateFlow<UiState> = _ui.asStateFlow()
    private var api: ApiClient? = null
    private var ws: WebSocket? = null
    private var poll: Job? = null
    private var wsRetry = 1000L

    init {
        val tok = prefs.getString("token", null)
        val srv = prefs.getString("server", null)
        if (tok != null && srv != null) runCatching { api = ApiClient(srv, tok); onLoggedIn() }
        val nm = app.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("ops", "Operações simuladas", NotificationManager.IMPORTANCE_HIGH))
    }

    private fun set(f: UiState.() -> UiState) { _ui.value = _ui.value.f() }
    fun consumeToast() = set { copy(toast = null) }
    fun go(s: Screen) { set { copy(screen = s) }; refresh(s) }

    fun login(server: String, user: String, pass: String) = viewModelScope.launch {
        set { copy(busy = true, error = null) }
        try {
            val c = ApiClient(server)
            c.login(user, pass)
            api = c
            prefs.edit().putString("server", c.base).putString("token", c.token).apply()
            set { copy(server = c.base) }
            onLoggedIn()
        } catch (e: Exception) {
            set { copy(error = e.message ?: "falha no login") }
        } finally { set { copy(busy = false) } }
    }

    fun logout() {
        ws?.close(1000, null); poll?.cancel()
        prefs.edit().remove("token").apply()
        api = null
        set { UiState(server = server) }
    }

    private fun onLoggedIn() {
        set { copy(loggedIn = true) }
        connectStream()
        poll?.cancel()
        poll = viewModelScope.launch {
            while (isActive) {
                refresh(_ui.value.screen, quiet = true)
                runCatching { api!!.measureClock() }.onSuccess { (rtt, skew) -> set { copy(rttMs = rtt, clockSkewMs = skew) } }
                delay(5000)
            }
        }
    }

    private fun connectStream() {
        val c = api ?: return
        ws?.cancel()
        ws = c.openStream(::onWs) { ok, info ->
            set { copy(wsConnected = ok, wsInfo = info) }
            if (ok) wsRetry = 1000
            else if (info == "sessão expirada") viewModelScope.launch { logout() }
            else viewModelScope.launch { delay(wsRetry); wsRetry = (wsRetry * 2).coerceAtMost(30000); if (_ui.value.loggedIn) connectStream() }
        }
    }

    private fun onWs(m: WsMsg) {
        ApiClient.serverTimeOf(m)?.let { t -> set { copy(lastServerEventMs = t) } }
        when (m.type) {
            "price" -> ApiClient.decode<PriceEvt>(m)?.let { p -> set { copy(livePrices = livePrices + (p.symbol to p.price)) } }
            "trade" -> ApiClient.decode<TradeDto>(m)?.let { t ->
                notifyTrade(t)
                set { copy(trades = (listOf(t) + trades.filter { it.id != t.id }).take(500)) }
                viewModelScope.launch { refresh(Screen.Dashboard, quiet = true) }
            }
            "state" -> viewModelScope.launch { refresh(Screen.Dashboard, quiet = true) }
        }
    }

    @kotlinx.serialization.Serializable data class PriceEvt(val symbol: String, val price: Double, val t: Long = 0)

    private fun notifyTrade(t: TradeDto) {
        val ctx = getApplication<Application>()
        val title = when (t.status) {
            "PENDING" -> "Nova operação simulada: ${t.direction} ${t.asset.substringBefore('@')}"
            "WIN" -> "WIN +%.2f · ${t.asset.substringBefore('@')}".format(t.pnl)
            "LOSS" -> "LOSS %.2f · ${t.asset.substringBefore('@')}".format(t.pnl)
            else -> return
        }
        val text = if (t.status == "PENDING") "Expiração ${t.expiry_min} min · ${t.strategy}" else "Entrada ${t.entry_price} → saída ${t.exit_price}"
        runCatching {
            ctx.getSystemService(NotificationManager::class.java).notify(t.id.hashCode(),
                NotificationCompat.Builder(ctx, "ops").setSmallIcon(android.R.drawable.ic_dialog_info)
                    .setContentTitle(title).setContentText(text).setAutoCancel(true).build())
        }
    }

    fun refresh(s: Screen = _ui.value.screen, quiet: Boolean = false) = viewModelScope.launch {
        val c = api ?: return@launch
        if (!quiet) set { copy(busy = true) }
        try {
            when (s) {
                Screen.Dashboard, Screen.Robot -> { val d: Dashboard = c.get("/dashboard"); set { copy(dash = d) }
                    if (s == Screen.Robot) { val dec: List<DecisionDto> = c.get("/decisions?limit=60"); set { copy(decisions = dec) } } }
                Screen.Assets -> { val a: List<AssetDto> = c.get("/assets"); set { copy(assets = a) } }
                Screen.Otc -> { val o: OtcDto = c.get("/otc"); set { copy(otc = o) } }
                Screen.News -> { val n: NewsResp = c.get("/news?limit=120"); set { copy(news = n) } }
                Screen.Strategies -> { val st: List<StrategyDto> = c.get("/strategies"); set { copy(strategies = st) } }
                Screen.History -> { val t: List<TradeDto> = c.get("/trades?limit=500"); set { copy(trades = t) } }
                Screen.Stats -> { val st: StatsDto = c.get("/stats"); set { copy(stats = st) } }
                Screen.Risk -> { val r: RiskSnap = c.get("/risk"); set { copy(risk = r) } }
                Screen.Settings -> { val st: SettingsDto = c.get("/settings"); set { copy(settings = st) } }
            }
            set { copy(error = null) }
        } catch (e: ApiException) {
            if (e.code == 401) logout() else set { copy(error = e.message) }
        } catch (e: Exception) {
            set { copy(error = "Servidor inacessível: ${e.message}") }
        } finally { if (!quiet) set { copy(busy = false) } }
    }

    fun command(path: String, label: String) = viewModelScope.launch {
        val c = api ?: return@launch
        try { val r: StatusResp = c.post(path); set { copy(toast = "$label · estado: ${r.state}") }; refresh(Screen.Dashboard, true) }
        catch (e: Exception) { set { copy(toast = e.message) } }
    }

    fun saveRisk(cfg: RiskCfg) = viewModelScope.launch {
        try { val r = api!!.putRisk(cfg); set { copy(risk = r, toast = "Gestão de risco salva") } }
        catch (e: Exception) { set { copy(toast = e.message) } }
    }

    fun toggleStrategy(name: String, on: Boolean) = viewModelScope.launch {
        try { api!!.toggleStrategy(name, on); refresh(Screen.Strategies, true) } catch (e: Exception) { set { copy(toast = e.message) } }
    }

    fun resetPaper() = viewModelScope.launch {
        try { api!!.raw("POST", "/paper/reset"); set { copy(toast = "Capital virtual reiniciado") }; refresh(Screen.Dashboard, true) }
        catch (e: Exception) { set { copy(toast = e.message) } }
    }

    val isSecure: Boolean get() = api?.isSecure ?: _ui.value.server.startsWith("https")
}
