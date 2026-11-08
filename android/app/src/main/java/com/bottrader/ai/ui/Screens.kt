package com.bottrader.ai.ui

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.bottrader.ai.MainViewModel
import com.bottrader.ai.Screen
import com.bottrader.ai.UiState
import com.bottrader.ai.data.*

/* ------------------------------------------------------------------ login */
@Composable
fun LoginScreen(ui: UiState, vm: MainViewModel) {
    var server by remember { mutableStateOf(ui.server.ifBlank { "https://" }) }
    var user by remember { mutableStateOf("admin") }
    var pass by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize().background(C.Bg).padding(20.dp), verticalArrangement = Arrangement.Center) {
        Text("BOT TRADER AI", fontSize = 28.sp, fontWeight = FontWeight.ExtraBold, color = C.Ink)
        Note("Conecte-se ao seu servidor (backend). Credenciais de corretoras nunca são pedidas nem armazenadas.")
        Spacer(Modifier.height(18.dp))
        OutlinedTextField(server, { server = it }, label = { Text("Endereço do servidor") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
        if (server.startsWith("http://")) Note("⚠ HTTP sem criptografia — use somente para testes na rede local.", C.Warn)
        OutlinedTextField(user, { user = it }, label = { Text("Usuário") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(pass, { pass = it }, label = { Text("Senha") }, singleLine = true, visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(14.dp))
        Button({ vm.login(server, user, pass) }, enabled = !ui.busy, modifier = Modifier.fillMaxWidth().height(50.dp)) {
            Text(if (ui.busy) "Conectando…" else "Entrar")
        }
        ui.error?.let { Spacer(Modifier.height(10.dp)); Note(it, C.Down) }
        Spacer(Modifier.height(26.dp))
        HorizontalDivider(color = C.Line)
        Spacer(Modifier.height(18.dp))
        Text("Não tem servidor?", color = C.Ink, fontWeight = FontWeight.Bold, fontSize = 16.sp)
        Note("O robô roda dentro do celular com os preços oficiais da Kraken (em tempo real, sem conta). Compras simuladas com stop, alvo e taxas reais. Funciona enquanto o app estiver aberto.")
        Spacer(Modifier.height(10.dp))
        OutlinedButton({ vm.startLocal() }, modifier = Modifier.fillMaxWidth().height(50.dp)) { Text("Usar sem servidor (Kraken no celular)", fontWeight = FontWeight.Bold) }
    }
}

/* ------------------------------------------------------------------ dashboard */
@Composable
fun DashboardScreen(ui: UiState, vm: MainViewModel) {
    val d = ui.dash ?: return Loading()
    StateHeader(d.state)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(bottom = 8.dp)) {
        Kpi("Capital virtual", money(d.capital), Modifier.weight(1f))
        Kpi("P&L simulado", (if (d.pnl >= 0) "+" else "") + money(d.pnl), Modifier.weight(1f), if (d.pnl >= 0) C.Up else C.Down)
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(bottom = 10.dp)) {
        Kpi("Operações", d.trades_total.toString(), Modifier.weight(1f))
        Kpi("Acerto", pct(d.win_rate, 0), Modifier.weight(1f), if (d.breakeven != null && (d.win_rate ?: 0.0) >= d.breakeven) C.Up else C.Ink)
        Kpi("Ativos", d.assets_monitored.toString(), Modifier.weight(1f))
    }
    RobotButtons(d.state, vm)
    Panel("Latência e conexões") {
        Line("Dados de mercado (fonte → servidor)", d.latency_ms?.let { "$it ms" } ?: "—", latColor(d.latency_ms))
        Line("Celular ↔ servidor (ida e volta)", ui.rttMs?.let { "$it ms" } ?: "—", latColor(ui.rttMs))
        Line("Diferença de relógio", ui.clockSkewMs?.let { "$it ms" } ?: "—")
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
            Dot(ui.wsConnected); Spacer(Modifier.width(8.dp)); Text("Tempo real (WebSocket)", color = C.Ink, fontSize = 13.5.sp, modifier = Modifier.weight(1f))
            Text(if (ui.wsConnected) "conectado" else ui.wsInfo.ifBlank { "reconectando" }, color = C.Mut, fontSize = 12.5.sp)
        }
        d.connections.forEach { c ->
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
                Dot(if (c.source == "otc") null else c.connected); Spacer(Modifier.width(8.dp))
                Text(c.source.replaceFirstChar { it.uppercase() }, color = C.Ink, fontSize = 13.5.sp, modifier = Modifier.weight(1f))
                Text(if (c.connected) "ok" else c.error.ifBlank { "desconectado" }, color = C.Mut, fontSize = 12.sp, maxLines = 2)
            }
        }
    }
    Panel("Operações em andamento") {
        if (d.open_trades.isEmpty()) Note("Nenhuma no momento. O robô só entra quando todos os filtros de dados, risco e confiança aprovam.")
        d.open_trades.forEach { TradeRow(it) }
    }
    Panel("Últimos sinais") {
        if (d.last_trades.isEmpty()) Note("Nenhum ainda.")
        d.last_trades.forEach { TradeRow(it) }
    }
    Note(if (d.mode == "kraken_spot") "Modo Kraken à vista (simulação): preços reais da Kraken, compras simuladas com stop, alvo e taxas reais. Nenhuma ordem real é enviada."
         else "Paper trading: resultados simulados com preços reais. Execução financeira real desativada.")
}

fun latColor(ms: Long?) = when { ms == null -> C.Mut; ms > 2000 -> C.Down; ms > 800 -> C.Warn; else -> C.Up }

@Composable
fun StateHeader(state: String) {
    val (label, color) = when (state) {
        "RUNNING" -> "OPERANDO (PAPER)" to C.Up; "PAUSED" -> "PAUSADO" to C.Warn
        "EMERGENCY" -> "STOP DE EMERGÊNCIA" to C.Down; else -> "PARADO · MONITORANDO" to C.Mut
    }
    Row(Modifier.fillMaxWidth().padding(bottom = 10.dp).clip(RoundedCornerShape(12.dp)).background(color.copy(alpha = 0.12f)).padding(12.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Dot(state == "RUNNING"); Spacer(Modifier.width(10.dp))
        Text("Robô: $label", color = color, fontWeight = FontWeight.Bold)
    }
}

@Composable
fun RobotButtons(state: String, vm: MainViewModel) {
    var confirm by remember { mutableStateOf(false) }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(bottom = 8.dp)) {
        Button({ vm.command("/bot/start", "INICIAR ROBÔ") }, enabled = state != "RUNNING" && state != "EMERGENCY", modifier = Modifier.weight(1f),
            colors = ButtonDefaults.buttonColors(containerColor = C.Up, contentColor = Color.Black)) { Text("INICIAR", fontWeight = FontWeight.Bold) }
        Button({ vm.command("/bot/pause", "PAUSAR ROBÔ") }, enabled = state == "RUNNING", modifier = Modifier.weight(1f),
            colors = ButtonDefaults.buttonColors(containerColor = C.Warn, contentColor = Color.Black)) { Text("PAUSAR", fontWeight = FontWeight.Bold) }
    }
    if (state == "EMERGENCY") {
        OutlinedButton({ vm.command("/bot/reset-emergency", "Emergência liberada") }, modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp)) { Text("Liberar emergência (revisado)") }
    } else {
        Button({ confirm = true }, modifier = Modifier.fillMaxWidth().height(52.dp).padding(bottom = 4.dp),
            colors = ButtonDefaults.buttonColors(containerColor = C.Down, contentColor = Color.White)) { Text("■  STOP DE EMERGÊNCIA", fontWeight = FontWeight.ExtraBold) }
        Spacer(Modifier.height(8.dp))
    }
    if (confirm) AlertDialog(onDismissRequest = { confirm = false },
        title = { Text("Parar tudo agora?") }, text = { Text("Bloqueia novas operações e cancela as que ainda não começaram.") },
        confirmButton = { TextButton({ confirm = false; vm.command("/bot/emergency-stop", "STOP DE EMERGÊNCIA") }) { Text("PARAR", color = C.Down) } },
        dismissButton = { TextButton({ confirm = false }) { Text("Cancelar") } })
}

@Composable
fun TradeRow(t: TradeDto) {
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (t.kind == "spot") "▲ COMPRA" else if (t.direction == "CALL") "▲ CALL" else "▼ PUT",
                color = if (t.direction == "CALL") C.Up else C.Down, fontWeight = FontWeight.ExtraBold)
            Spacer(Modifier.width(8.dp)); Text(sym(t.asset), color = C.Ink, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Tag(t.status, statusColor(t.status))
        }
        if (t.kind == "spot") {
            Note("Entrada ${hhmmss(t.entry_t)}${t.entry_price?.let { " @ $it" } ?: ""} · ${money(t.stake)} € · máx. ${t.expiry_min} min")
            if (t.stop_price != null) Note("Stop ${"%.6g".format(t.stop_price)} · Alvo ${"%.6g".format(t.target_price ?: 0.0)}")
            if (t.exit_price != null) Note("Saída ${t.exit_price} por ${t.exit_reason} · ${if (t.pnl >= 0) "+" else ""}${money(t.pnl)} € (taxas ${money(t.fees)} €)",
                if (t.pnl >= 0) C.Up else C.Down)
            Note("${t.strategy} · acerto histórico ${t.confidence?.let { pct(it) + " (n=${t.confidence_n})" } ?: "—"} · força ${t.model_strength}")
        } else {
            Note("${t.expiry_min} min · entrada ${hhmmss(t.entry_t)}${t.entry_price?.let { " @ $it" } ?: ""}${t.exit_price?.let { " → $it" } ?: ""}" +
                    (if (t.status == "WIN" || t.status == "LOSS") " · ${if (t.pnl >= 0) "+" else ""}${money(t.pnl)}" else ""))
            Note("${t.strategy} · confiança ${t.confidence?.let { pct(it) + " (n=${t.confidence_n})" } ?: "não calibrada"} · força ${t.model_strength}")
        }
        if (t.cancel_reason.isNotBlank()) Note("Cancelada: ${t.cancel_reason}", C.Warn)
    }
    HorizontalDivider(color = C.Line)
}

/* ------------------------------------------------------------------ robô */
@Composable
fun RobotScreen(ui: UiState, vm: MainViewModel) {
    val d = ui.dash ?: return Loading()
    StateHeader(d.state)
    RobotButtons(d.state, vm)
    Panel("Risco hoje") {
        Line("Resultado do dia", money(d.risk.pnl_today), if (d.risk.pnl_today >= 0) C.Up else C.Down)
        Line("Operações hoje", d.risk.trades_today.toString())
        Line("Exposição aberta", money(d.risk.open_exposure))
        Line("Perdas seguidas", d.risk.consecutive_losses.toString())
    }
    Panel("Registro de decisões", trailing = { TextButton({ vm.refresh(Screen.Robot) }) { Text("Atualizar") } }) {
        if (ui.decisions.isEmpty()) Note("Nenhuma decisão registrada ainda.")
        ui.decisions.forEach { dec ->
            Row(Modifier.padding(vertical = 5.dp)) {
                Text(if (dec.accepted) "✓" else "✗", color = if (dec.accepted) C.Up else C.Down, modifier = Modifier.width(18.dp))
                Column(Modifier.weight(1f)) {
                    Text("${hhmmss(dec.ts)} · ${dec.stage.uppercase()} · ${sym(dec.asset)}", color = C.Mut, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
                    Text(dec.reason, color = C.Ink, fontSize = 13.sp)
                }
            }
        }
    }
}

/* ------------------------------------------------------------------ ativos */
@Composable
fun AssetsScreen(ui: UiState) {
    if (ui.assets.isEmpty()) return Loading()
    ui.assets.filter { it.market == "NORMAL" }.forEach { a -> AssetCard(a, ui.livePrices[a.symbol]) }
}

@Composable
fun AssetCard(a: AssetDto, live: Double?) {
    Panel(a.display, trailing = { Tag(a.source, C.Acc) }) {
        val p = live ?: a.price
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(bottom = 8.dp)) {
            Kpi("Preço", p?.let { String.format("%.${a.decimals}f", it) } ?: "—", Modifier.weight(1.4f))
            Kpi("1 hora", a.change_1h?.let { (if (it >= 0) "+" else "") + pct(it, 2) } ?: "—", Modifier.weight(1f), if ((a.change_1h ?: 0.0) >= 0) C.Up else C.Down)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Kpi("RSI", a.rsi?.let { "%.0f".format(it) } ?: "—", Modifier.weight(1f))
            Kpi("ADX", a.adx?.let { "%.0f".format(it) } ?: "—", Modifier.weight(1f))
            Kpi("Latência", a.latency_ms?.let { "$it ms" } ?: "—", Modifier.weight(1f), latColor(a.latency_ms))
        }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            a.regime?.let { Tag("Regime: $it", if (it == "TENDÊNCIA") C.Acc else if (it == "VOLÁTIL") C.Down else C.Mut) }
            a.trend_5m?.let { Tag("5m: " + if (it > 0) "alta" else if (it < 0) "baixa" else "—", if (it > 0) C.Up else C.Down) }
        }
        if (a.blocked.isNotEmpty()) { Spacer(Modifier.height(6.dp)); Note("Bloqueado: " + a.blocked.joinToString("; "), C.Warn) }
    }
}

/* ------------------------------------------------------------------ OTC */
@Composable
fun OtcScreen(ui: UiState) {
    val o = ui.otc ?: return Loading()
    Panel("Status OTC") {
        Row(verticalAlignment = Alignment.CenterVertically) { Dot(o.available); Spacer(Modifier.width(8.dp)); Text(if (o.available) "Fonte OTC disponível" else "Fonte OTC indisponível", color = C.Ink, fontWeight = FontWeight.Bold) }
        Spacer(Modifier.height(8.dp)); Note(o.message, if (o.available) C.Mut else C.Warn)
        Spacer(Modifier.height(8.dp)); Note(o.explanation)
    }
    Panel("Ativos OTC (módulo separado)") {
        o.assets.forEach { a -> Line(a.display, if (a.blocked.isEmpty()) "liberado" else "bloqueado", if (a.blocked.isEmpty()) C.Up else C.Down)
            a.blocked.forEach { Note("• $it") } }
    }
    Note("Cotações OTC nunca são misturadas com cotações do mercado normal. Cada ativo tem sua própria fonte de dados.")
}

/* ------------------------------------------------------------------ notícias */
@Composable
fun NewsScreen(ui: UiState) {
    val n = ui.news ?: return Loading()
    val ctx = LocalContext.current
    var filter by remember { mutableStateOf("Todas") }
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(bottom = 8.dp)) {
        listOf("Todas", "Alto", "USD", "EUR", "CRYPTO").forEach { f -> FilterChip(filter == f, { filter = f }, label = { Text(f) }) }
    }
    val high = n.calendar.filter { it.impact == "High" && it.t > System.currentTimeMillis() - 3_600_000 }.take(8)
    Panel("Calendário — alto impacto") {
        if (high.isEmpty()) Note(if (n.calendar_status == "ok") "Nenhum evento de alto impacto próximo." else "Calendário: ${n.calendar_status}")
        high.forEach { e -> Line("${dateTime(e.t)} · ${e.currency} · ${e.title}", listOfNotNull(e.forecast?.takeIf { it.isNotBlank() }?.let { "prev. $it" }).joinToString()) }
    }
    val items = n.items.filter { when (filter) { "Todas" -> true; "Alto" -> it.impact == "Alto"; else -> filter in it.currencies } }
    Panel("Notícias (${items.size})") {
        items.take(80).forEach { it ->
            Column(Modifier.fillMaxWidth().clickable { if (it.url.startsWith("http")) ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(it.url))) }.padding(vertical = 7.dp)) {
                Text(it.title, color = C.Ink, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                Note("${it.source} · ${it.published_ms?.let(::dateTime) ?: "sem data"} · confiabilidade ${pct(it.reliability, 0)} · relevância ${pct(it.relevance, 0)}")
                Row(horizontalArrangement = Arrangement.spacedBy(5.dp), modifier = Modifier.padding(top = 4.dp)) {
                    Tag("impacto ${it.impact.lowercase()}", if (it.impact == "Alto") C.Down else if (it.impact == "Médio") C.Warn else C.Mut)
                    it.currencies.take(3).forEach { c -> Tag(c, C.Acc) }
                    it.topics.take(2).forEach { t -> Tag(t, C.Mut) }
                }
            }
            HorizontalDivider(color = C.Line)
        }
    }
    Panel("Fontes") { n.feeds.forEach { (k, v) -> Line(k, if (v == "ok") "ok" else v, if (v == "ok") C.Up else C.Down) } }
    Note("Notícias não são usadas como confirmação de entrada — apenas para informar e bloquear operações perto de eventos de risco.")
}

/* ------------------------------------------------------------------ estratégias */
@Composable
fun StrategiesScreen(ui: UiState, vm: MainViewModel) {
    if (ui.strategies.isEmpty()) return Loading()
    ui.strategies.forEach { s ->
        Panel(s.name, trailing = { Switch(s.enabled, { vm.toggleStrategy(s.name, it) }) }) {
            Note(s.doc)
            Spacer(Modifier.height(6.dp)); Note("Regimes: " + s.regimes.joinToString())
            s.calibration.forEach { (asset, cells) ->
                val w = cells.values.sumOf { it.wins }; val n = cells.values.sumOf { it.n }
                if (n > 0) Line(sym(asset), "${pct(w.toDouble() / n)} em $n (histórico)")
            }
        }
    }
    Note("Sem martingale e sem progressão de apostas: o valor por operação é fixo.")
}

/* ------------------------------------------------------------------ histórico */
@Composable
fun HistoryScreen(ui: UiState) {
    Panel("Histórico completo (${ui.trades.size})") {
        if (ui.trades.isEmpty()) Note("Nenhuma operação simulada ainda.")
        ui.trades.forEach { TradeRow(it) }
    }
}

/* ------------------------------------------------------------------ estatísticas */
@Composable
fun StatsScreen(ui: UiState) {
    val s = ui.stats ?: return Loading()
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(bottom = 10.dp)) {
        Kpi("Operações", s.n.toString(), Modifier.weight(1f))
        Kpi("Acerto real", pct(s.rate), Modifier.weight(1f))
        if (s.breakeven != null) Kpi("Equilíbrio", pct(s.breakeven), Modifier.weight(1f))
        else Kpi("Resultado", (if (s.pnl_total >= 0) "+" else "") + money(s.pnl_total), Modifier.weight(1f), if (s.pnl_total >= 0) C.Up else C.Down)
    }
    if (s.mode == "kraken_spot") Note("Taxas pagas: ${money(s.fees_total)} €. No modo à vista o que importa é o resultado em euros depois das taxas, não só a taxa de acerto.")
    s.ci?.let { Note("Intervalo de confiança 95%: ${pct(it[0])} a ${pct(it[1])}. Abaixo de ~100 operações o resultado ainda é muito incerto.") }
    s.deterioration?.let { Panel("Detecção de deterioração") {
        Note("Últimas 30: ${pct(it.recent)} · anteriores: ${pct(it.before)}", if (it.degraded) C.Down else C.Mut)
        if (it.degraded) Note("⚠ Desempenho caiu abaixo do ponto de equilíbrio — revise ou pause o robô.", C.Down) } }
    if (s.equity.size > 1) Panel("Curva de capital (simulado)") { Equity(s.equity.map { it.equity }) }
    val be = s.breakeven ?: 0.5
    GroupPanel("Por ativo", s.by_asset, be); GroupPanel("Por estratégia", s.by_strategy, be)
    GroupPanel("Por expiração / tempo máximo", s.by_expiry, be); GroupPanel("Por horário", s.by_hour, be)
    Panel("Backtest walk-forward (fora da amostra)") {
        if (s.backtest.isEmpty()) Note("Aguardando histórico dos ativos.")
        s.backtest.forEach { (asset, bt) ->
            Text(sym(asset) + " · ${bt.signals} sinais no histórico", color = C.Ink, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 6.dp))
            bt.summary?.takeIf { it.n > 0 }?.let { sm -> Line("  Todas as entradas (${sm.n})", "acerto ${pct(sm.win_rate)} · média ${pct(sm.mean_pct, 2)} após taxas", if ((sm.mean_pct ?: 0.0) > 0) C.Up else C.Down) }
            bt.walk_forward.forEach { (exp, wf) ->
                val label = if (exp == "spot") "  Fora da amostra" else "  $exp min"
                Line(label, if (wf.tested > 0) "${pct(wf.rate)} em ${wf.tested}" + (wf.mean_pct?.let { " · média ${pct(it, 2)}" } ?: "") else "nenhuma entrada qualificada",
                    if ((wf.mean_pct ?: wf.rate?.minus(0.55) ?: 0.0) > 0) C.Up else C.Mut)
            }
        }
        Spacer(Modifier.height(6.dp)); Note("Calibrado só com blocos anteriores e testado no bloco seguinte — sem dados futuros.")
    }
}

@Composable
fun GroupPanel(title: String, g: List<GroupDto>, be: Double) {
    if (g.isEmpty()) return
    Panel(title) { g.forEach { Line("${it.key} (${it.n})", "${pct(it.rate)}  [${pct(it.ci.getOrNull(0), 0)}–${pct(it.ci.getOrNull(1), 0)}]", if (it.rate >= be) C.Up else C.Down) } }
}

@Composable
fun Equity(v: List<Double>) {
    Canvas(Modifier.fillMaxWidth().height(140.dp)) {
        val mn = v.min(); val mx = v.max(); val r = (mx - mn).takeIf { it > 0 } ?: 1.0
        val path = Path()
        v.forEachIndexed { i, y ->
            val x = size.width * i / (v.size - 1); val yy = size.height - ((y - mn) / r * size.height).toFloat()
            if (i == 0) path.moveTo(x, yy) else path.lineTo(x, yy)
        }
        val base = size.height - ((v.first() - mn) / r * size.height).toFloat()
        drawLine(C.Line, Offset(0f, base), Offset(size.width, base), 2f)
        drawPath(path, if (v.last() >= v.first()) C.Up else C.Down, style = Stroke(width = 4f))
    }
}

/* ------------------------------------------------------------------ risco */
@Composable
fun RiskScreen(ui: UiState, vm: MainViewModel) {
    val r = ui.risk ?: return Loading()
    var stake by remember(r) { mutableStateOf(r.config.stake.toString()) }
    var payout by remember(r) { mutableStateOf((r.config.payout * 100).toInt().toString()) }
    var loss by remember(r) { mutableStateOf(r.config.daily_loss_limit.toString()) }
    var expo by remember(r) { mutableStateOf(r.config.max_exposure.toString()) }
    var maxT by remember(r) { mutableStateOf(r.config.max_trades_day.toString()) }
    var maxO by remember(r) { mutableStateOf(r.config.max_open_trades.toString()) }
    var cons by remember(r) { mutableStateOf(r.config.max_consecutive_losses.toString()) }
    var conf by remember(r) { mutableStateOf((r.config.min_confidence * 100).toInt().toString()) }
    Panel("Estado") {
        Line("Resultado hoje", money(r.state.pnl_today), if (r.state.pnl_today >= 0) C.Up else C.Down)
        Line("Operações hoje", r.state.trades_today.toString()); Line("Exposição aberta", money(r.state.open_exposure))
        Line("Emergência", if (r.state.emergency) "ATIVA" else "não", if (r.state.emergency) C.Down else C.Mut)
        Line("Ponto de equilíbrio", pct(r.breakeven))
    }
    Panel("Limites") {
        RiskField("Valor fixo por operação", stake) { stake = it }; RiskField("Payout da corretora (%)", payout) { payout = it }
        RiskField("Limite diário de perda", loss) { loss = it }; RiskField("Exposição máxima", expo) { expo = it }
        RiskField("Máx. operações por dia", maxT) { maxT = it }; RiskField("Máx. operações simultâneas", maxO) { maxO = it }
        RiskField("Pausa após perdas seguidas", cons) { cons = it }; RiskField("Confiança mínima calibrada (%)", conf) { conf = it }
        Button({
            val d = { s: String -> s.replace(',', '.').toDoubleOrNull() }
            val cfg = runCatching { RiskCfg(d(stake)!!, d(payout)!! / 100, d(loss)!!, d(expo)!!, maxT.toInt(), maxO.toInt(), cons.toInt(), d(conf)!! / 100, false) }.getOrNull()
            if (cfg != null) vm.saveRisk(cfg)
        }, modifier = Modifier.fillMaxWidth()) { Text("Salvar limites") }
        Note("Sem martingale: o valor por operação nunca aumenta após perdas.")
    }
    Panel("Capital simulado") { OutlinedButton({ vm.resetPaper() }, modifier = Modifier.fillMaxWidth()) { Text("Reiniciar capital virtual") } }
}

/* ------------------------------------------------------------------ configurações */
@Composable
fun SettingsScreen(ui: UiState, vm: MainViewModel) {
    val s = ui.settings
    Panel("Servidor") {
        Line("Endereço", ui.server)
        Line("Criptografia", if (ui.local) "conexões HTTPS/WSS com a Kraken ✓" else if (vm.isSecure) "HTTPS ✓" else "HTTP sem criptografia", if (vm.isSecure) C.Up else C.Warn)
        s?.let { Line("Modo", if (it.mode == "kraken_spot") "Kraken à vista (simulação)" else "Opções binárias (simulação)")
            it.spot?.let { sp -> Line("Velas", "${sp.interval_min} min"); Line("Valor por compra", "${money(sp.stake)} €")
                Line("Taxa por lado", pct(sp.fee_rate, 2)); Line("Stop / Alvo", "${sp.stop_atr}× / ${sp.target_atr}× ATR"); Line("Tempo máximo", "${sp.max_bars} velas") }
            Line("Banco de dados", it.database); Line("Redis", if (it.redis) "ativo" else "não configurado"); Line("Forex (Twelve Data)", if (it.twelvedata_configured) "configurado" else "sem chave") }
    }
    s?.let { Panel("Corretoras") {
        it.brokers.forEach { b -> Line(b.name, if (b.real_money) "dinheiro real" else "simulação") }
        Note(it.real_execution_note, C.Warn)
        Note("Para integrar uma corretora é preciso uma API oficial documentada, aprovação legal e validação de segurança. Engenharia reversa e automação de cliques não são usadas.")
    } }
    if (ui.local) Note("O monitoramento só acontece com o app aberto. Ative 'manter a tela ligada' deixando o robô em execução: a tela não apaga enquanto ele opera.")
    OutlinedButton({ vm.logout() }, modifier = Modifier.fillMaxWidth()) { Text(if (ui.local) "Sair do modo celular" else "Sair") }
}

@Composable
fun RiskField(label: String, v: String, set: (String) -> Unit) = OutlinedTextField(v, set, label = { Text(label) }, singleLine = true,
    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp))

@Composable fun Loading() = Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
