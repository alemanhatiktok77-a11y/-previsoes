package com.bottrader.ai.local

import android.content.SharedPreferences
import com.bottrader.ai.data.*
import kotlinx.coroutines.*
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.encodeToString
import okhttp3.WebSocket
import java.util.UUID
import kotlin.math.max

/**
 * Robô completo rodando no celular (sem servidor): dados oficiais da Kraken → motor → risco → compras SIMULADAS.
 * Gera os mesmos objetos (DTOs) que o servidor, então todas as telas funcionam igual.
 */
class LocalBot(private val prefs: SharedPreferences?, private val kraken: KrakenClient = KrakenClient(),
               private val scope: CoroutineScope, val intervalMin: Int = 15,
               private val onTrade: (TradeDto) -> Unit = {}) {

    val symbols = listOf("BTC/EUR", "ETH/EUR", "SOL/EUR")
    val spot = SpotConfig(stake = 100.0)
    var risk = RiskCfg(stake = 100.0, payout = 1.0, daily_loss_limit = 50.0, max_exposure = 300.0, max_trades_day = 20,
        max_open_trades = 3, max_consecutive_losses = 4, min_confidence = 0.0, allow_uncalibrated = false)
    var state = "STOPPED"; private set
    var initialCapital = 1000.0
    var cash = 1000.0
    private var emergency = false
    var enabledStrategies: MutableSet<String> = Ai.STRATEGIES.map { it.name }.toMutableSet()

    private val ms = intervalMin * 60_000L
    val lock = java.util.concurrent.Executors.newSingleThreadExecutor().asCoroutineDispatcher()   // fila única (sem corrida)
    val candles = HashMap<String, MutableList<Candle>>()
    private val current = HashMap<String, Candle>()
    val lastPrice = HashMap<String, Double>()
    val latency = HashMap<String, Long>()
    private val lastEvent = HashMap<String, Long>()
    val calibrators = HashMap<String, Spot.Calibrator>()
    val report = HashMap<String, Pair<List<SimResult>, Spot.WalkForward>>()
    val trades = ArrayList<TradeDto>()
    private val atrAtSignal = HashMap<String, Double>()
    val decisions = ArrayDeque<DecisionDto>()
    var offsetMs = 0L
    var wsConnected = false; var wsInfo = "desconectado"; var restInfo = "não iniciado"; var reconnects = 0
    private var ws: WebSocket? = null
    private var job: Job? = null

    fun now() = System.currentTimeMillis() + offsetMs

    init { load() }

    // ------------------------------------------------ ciclo de vida
    fun startMonitoring() {
        if (job != null) return
        job = scope.launch(Dispatchers.IO) {
            runCatching { offsetMs = kraken.clockOffset() }
            var ok = 0
            for (s in symbols) {
                runCatching { kraken.ohlc(s, intervalMin, now()) }
                    .onSuccess { c -> withContext(lock) { candles[s] = c.toMutableList(); seed(s, c) }; ok++ }
                    .onFailure { restInfo = "erro ${s}: ${it.message}" }
            }
            if (ok > 0) restInfo = "histórico ok ($ok/${symbols.size})"
            connect(1000)
            while (isActive) {                                  // manutenção
                delay(5000)
                withContext(lock) { expireStale() }
                if (!wsConnected) continue
                val silent = symbols.all { now() - (lastEvent[it] ?: 0) > 60_000 }
                if (silent) { record("*", "data", false, "sem dados da Kraken há 60 s — reconectando"); ws?.cancel() }
            }
        }
    }

    private fun connect(backoff: Long) {
        ws = kraken.stream(symbols, intervalMin, { txt -> scope.launch(lock) { onMessage(txt) } }) { ok, info ->
            wsConnected = ok; wsInfo = if (ok) "tempo real" else info
            if (!ok && job?.isActive == true) { reconnects++; scope.launch { delay(backoff); connect((backoff * 2).coerceAtMost(30_000)) } }
        }
    }

    fun stop() { job?.cancel(); job = null; ws?.cancel(); wsConnected = false }

    fun start(): String { if (emergency) return "Robô em STOP DE EMERGÊNCIA — libere antes de iniciar"; state = "RUNNING"; record("*", "control", true, "robô iniciado (simulação Kraken)"); save(); return state }
    fun pause(): String { state = "PAUSED"; record("*", "control", true, "robô pausado"); save(); return state }
    fun emergencyStop(): String {
        scope.launch(lock) {
            emergency = true; state = "EMERGENCY"
            trades.filter { it.status == "PENDING" }.forEach { cancel(it, "STOP DE EMERGÊNCIA") }
            trades.filter { it.status == "OPEN" }.forEach { t -> close(t, lastPrice[t.asset] ?: t.entry_price!!, "emergência") }
            record("*", "control", true, "STOP DE EMERGÊNCIA acionado — posições zeradas"); save()
        }
        state = "EMERGENCY"; return state
    }
    fun resetEmergency(): String { emergency = false; state = "STOPPED"; record("*", "control", true, "emergência liberada pelo usuário"); save(); return state }

    // ------------------------------------------------ dados ao vivo
    private fun onMessage(text: String) {
        val (type, rows) = KrakenClient.parseWs(text) ?: run {
            if (text.contains("\"heartbeat\"")) symbols.forEach { lastEvent[it] = now() }
            return
        }
        for (r in rows) {
            val s = r.symbol; if (s !in symbols) continue
            lastEvent[s] = now()
            if (type == "snapshot") { if ((current[s]?.t ?: 0) <= r.candle.t) current[s] = r.candle; continue }
            r.tradeTs?.let { latency[s] = max(0, now() - it) }
            lastPrice[s] = r.candle.c
            val prev = current[s]
            if (prev != null && r.candle.t > prev.t) onClosed(s, prev)
            if (prev == null || r.candle.t >= prev.t) { current[s] = r.candle; manage(s, r.candle, closed = false) }
        }
    }

    private fun onClosed(s: String, c: Candle) {
        val C = candles.getOrPut(s) { mutableListOf() }
        if (C.isNotEmpty() && C.last().t >= c.t) return
        C.add(c); if (C.size > 1000) C.removeAt(0)
        manage(s, c, closed = true)
        analyzeAndDecide(s, C)
    }

    // ------------------------------------------------ calibração (somente passado)
    private fun seed(s: String, C: List<Candle>) {
        val res = Spot.simulate(C, spot)
        val cal = Spot.Calibrator(spot.minTradesCalib); res.forEach { cal.add(it.strategy, it.bucket, it.pnlPct) }
        trades.filter { it.asset == s && it.exit_price != null && it.entry_price != null }
            .forEach { cal.add(it.strategy, Ai.bucket(it.model_strength), it.exit_price!! / it.entry_price!! - 1 - spot.roundTrip) }
        calibrators[s] = cal
        report[s] = res to Spot.walkForward(res, minN = spot.minTradesCalib)
    }

    // ------------------------------------------------ pipeline de decisão
    private fun guard(s: String, n: Int): List<String> {
        val r = ArrayList<String>()
        if (!wsConnected) r.add("conexão com a Kraken indisponível")
        val le = lastEvent[s]; if (le == null) r.add("nenhum dado ao vivo") else if (now() - le > 60_000) r.add("sem dados há ${(now() - le) / 1000} s")
        latency[s]?.let { if (it > 5000) r.add("dados atrasados ($it ms)") }
        if (n < 200) r.add("histórico insuficiente ($n velas)")
        return r
    }

    private fun riskCheck(): List<String> {
        val r = ArrayList<String>(); val today = todayTrades()
        if (emergency) r.add("STOP DE EMERGÊNCIA acionado")
        val pnl = today.sumOf { it.pnl }
        if (-pnl >= risk.daily_loss_limit) r.add("limite diário de perda atingido (${"%.2f".format(pnl)} €)")
        if (today.size >= risk.max_trades_day) r.add("limite de operações do dia atingido")
        val open = trades.filter { it.status == "OPEN" || it.status == "PENDING" }
        if (open.size >= risk.max_open_trades) r.add("máximo de posições simultâneas")
        if (open.sumOf { it.stake } + risk.stake > risk.max_exposure) r.add("exposição máxima atingida")
        val streak = trades.filter { it.status == "WIN" || it.status == "LOSS" }.sortedBy { it.closed_ms ?: 0 }.takeLastWhile { it.status == "LOSS" }.size
        if (streak >= risk.max_consecutive_losses) r.add("$streak perdas seguidas — robô pausado para revisão")
        if (risk.stake > cash) r.add("capital simulado insuficiente")
        return r
    }

    private fun analyzeAndDecide(s: String, C: List<Candle>) {
        val F = Features(C); val i = C.size - 1
        val (op, reg) = Ai.analyze(F, i, enabledStrategies)
        if (op == null) return
        if (op.dir != 1) { record(s, "opportunity", false, "${op.strategy}: sinal de QUEDA — à vista só compra, não entra"); return }
        record(s, "opportunity", true, "${op.strategy}: COMPRA (força ${op.strength}) · regime $reg")
        if (state != "RUNNING") { record(s, "execution", false, if (state == "PAUSED") "robô pausado" else "robô parado (só monitorando)"); return }
        guard(s, C.size).takeIf { it.isNotEmpty() }?.let { record(s, "data", false, it.joinToString("; ")); return }
        if (trades.any { it.asset == s && (it.status == "PENDING" || it.status == "OPEN") }) { record(s, "strategy", false, "já existe posição neste ativo"); return }
        val est = (calibrators[s] ?: Spot.Calibrator(spot.minTradesCalib)).estimate(op.strategy, Ai.bucket(op.strength))
        if (!est.calibrated) { record(s, "strategy", false, "histórico insuficiente para esta estratégia (n=${est.n})"); return }
        if (est.meanLow <= 0) { record(s, "strategy", false, "no passado, após taxas, este tipo de entrada deu ${"%+.2f".format(est.mean * 100)}% em média (n=${est.n}) — não compensa"); return }
        val reward = spot.targetAtr * F.atr[i] / C[i].c
        if (reward < spot.minRewardVsCost * spot.roundTrip) { record(s, "strategy", false, "alvo de ${"%.2f".format(reward * 100)}% não cobre 2× as taxas"); return }
        record(s, "strategy", true, "resultado médio passado ${"%+.2f".format(est.mean * 100)}% após taxas (n=${est.n})")
        riskCheck().takeIf { it.isNotEmpty() }?.let { record(s, "risk", false, it.joinToString("; ")); return }
        record(s, "risk", true, "dentro dos limites de risco")
        val t = TradeDto(id = UUID.randomUUID().toString().replace("-", ""), asset = s, direction = "CALL", strategy = op.strategy, stake = risk.stake,
            payout = 0.0, expiry_min = spot.maxBars * intervalMin, entry_t = C[i].t + ms, confidence = est.winRate, confidence_n = est.n,
            model_strength = op.strength, status = "PENDING", reasons = op.votes.filter { it.dir > 0 }.map { it.reason }, created_ms = now(), kind = "spot")
        atrAtSignal[t.id] = F.atr[i]
        upsert(t); record(s, "execution", true, "compra simulada na abertura da próxima vela")
    }

    // ------------------------------------------------ posições
    private fun manage(s: String, c: Candle, closed: Boolean) {
        for (t in trades.toList()) {
            if (t.asset != s) continue
            if (t.status == "PENDING" && c.t >= t.entry_t) {
                if (c.t > t.entry_t) { cancel(t, "vela de entrada não recebida"); continue }
                val a = atrAtSignal[t.id] ?: 0.0
                val fee = t.stake * spot.feeRate
                cash -= t.stake
                val opened = t.copy(status = "OPEN", entry_price = c.o, quantity = (t.stake - fee) / c.o, fees = fee,
                    stop_price = c.o - spot.stopAtr * a, target_price = c.o + spot.targetAtr * a)
                upsert(opened); record(s, "execution", true, "compra simulada @ ${c.o} · stop ${"%.6g".format(opened.stop_price)} · alvo ${"%.6g".format(opened.target_price)}")
                continue
            }
            if (t.status == "OPEN" && c.t >= t.entry_t) {
                val st = t.stop_price!!; val tg = t.target_price!!
                when {
                    c.l <= st -> close(t, if (c.o < st) c.o else st, "stop")
                    c.h >= tg -> close(t, if (c.o > tg) c.o else tg, "alvo")
                    closed && c.t >= t.entry_t + (spot.maxBars - 1) * ms -> close(t, c.c, "tempo")
                }
            }
        }
    }

    private fun close(t: TradeDto, px: Double, why: String) {
        val gross = t.quantity * px; val fee = gross * spot.feeRate
        cash += gross - fee
        val pnl = Math.round((gross - fee - t.stake) * 100) / 100.0
        val done = t.copy(status = if (pnl > 0) "WIN" else if (pnl < 0) "LOSS" else "DRAW", exit_price = px, pnl = pnl, fees = t.fees + fee,
            exit_reason = why, closed_ms = now())
        upsert(done)
        calibrators.getOrPut(t.asset) { Spot.Calibrator(spot.minTradesCalib) }.add(t.strategy, Ai.bucket(t.model_strength), px / t.entry_price!! - 1 - spot.roundTrip)
        record(t.asset, "settlement", true, "saída por $why: ${done.status} ${"%+.2f".format(pnl)} € (taxas ${"%.2f".format(done.fees)} €)")
    }

    private fun cancel(t: TradeDto, reason: String) {
        if (t.status == "OPEN") cash += t.stake
        upsert(t.copy(status = "CANCELLED", cancel_reason = reason, closed_ms = now()))
        record(t.asset, "execution", false, "operação cancelada: $reason")
    }

    private fun expireStale() { trades.filter { it.status == "PENDING" && now() > it.entry_t + 60_000 }.forEach { cancel(it, "sem preço de entrada (dados atrasados ou desconexão)") } }

    private fun upsert(t: TradeDto) {
        val i = trades.indexOfFirst { it.id == t.id }
        if (i >= 0) trades[i] = t else trades.add(t)
        if (trades.size > 1000) trades.removeAt(0)
        save(); onTrade(t)
    }

    private fun record(asset: String, stage: String, ok: Boolean, reason: String) {
        decisions.addFirst(DecisionDto(UUID.randomUUID().toString(), now(), asset, stage, ok, reason))
        while (decisions.size > 300) decisions.removeLast()
    }

    private fun todayTrades(): List<TradeDto> {
        val day = now() / 86_400_000
        return trades.filter { it.created_ms / 86_400_000 == day && it.status != "CANCELLED" }
    }

    // ------------------------------------------------ persistência
    private fun save() {
        prefs?.edit()?.putString("local_trades", JsonCfg.encodeToString(ListSerializer(TradeDto.serializer()), trades.takeLast(500)))
            ?.putString("local_cash", cash.toString())?.putString("local_initial", initialCapital.toString())
            ?.putString("local_state", if (state == "EMERGENCY") "EMERGENCY" else state)
            ?.putString("local_risk", JsonCfg.encodeToString(risk))?.apply()
    }

    private fun load() {
        val p = prefs ?: return
        runCatching { trades.addAll(JsonCfg.decodeFromString(ListSerializer(TradeDto.serializer()), p.getString("local_trades", "[]")!!)) }
        cash = p.getString("local_cash", null)?.toDoubleOrNull() ?: 1000.0
        initialCapital = p.getString("local_initial", null)?.toDoubleOrNull() ?: 1000.0
        runCatching { risk = JsonCfg.decodeFromString(RiskCfg.serializer(), p.getString("local_risk", null)!!) }
        when (p.getString("local_state", "STOPPED")) { "EMERGENCY" -> { emergency = true; state = "EMERGENCY" }; "RUNNING" -> state = "RUNNING"; "PAUSED" -> state = "PAUSED" }
        // posições que ficaram abertas com o app fechado não podem ser acompanhadas: cancela de forma transparente
        trades.filter { it.status == "PENDING" || it.status == "OPEN" }.forEach {
            if (it.status == "OPEN") cash += it.stake
            trades[trades.indexOf(it)] = it.copy(status = "CANCELLED", cancel_reason = "app foi fechado durante a operação", closed_ms = System.currentTimeMillis())
        }
    }

    fun resetPaper(): Boolean {
        if (trades.any { it.status == "OPEN" || it.status == "PENDING" }) return false
        cash = initialCapital; save(); return true
    }

    fun setStake(v: Double) { spot.stake = v }

    // ------------------------------------------------ visões para as telas
    fun dashboard(): Dashboard {
        val closed = trades.filter { it.status == "WIN" || it.status == "LOSS" }
        val lat = latency.values.toList()
        val today = todayTrades()
        val openT = trades.filter { it.status == "OPEN" || it.status == "PENDING" }
        return Dashboard(state = state, server_time = now(), clock_offset_ms = offsetMs, capital = Math.round((cash + openT.sumOf { t ->
                if (t.status == "OPEN") t.quantity * (lastPrice[t.asset] ?: t.entry_price ?: 0.0) else t.stake }) * 100) / 100.0,
            initial_capital = initialCapital, pnl = Math.round(trades.sumOf { it.pnl } * 100) / 100.0, trades_total = closed.size,
            open_trades = openT.reversed(), win_rate = if (closed.isEmpty()) null else closed.count { it.status == "WIN" }.toDouble() / closed.size,
            breakeven = null, mode = "kraken_spot", assets_monitored = candles.size, latency_ms = if (lat.isEmpty()) null else lat.sum() / lat.size,
            last_trades = trades.takeLast(8).reversed(),
            connections = listOf(ConnDto("kraken", "NORMAL", wsConnected, if (wsConnected) "" else wsInfo, reconnects, latency.toMap()),
                ConnDto("histórico", "NORMAL", restInfo.startsWith("histórico ok"), restInfo), ConnDto("otc", "OTC", false, "nenhuma fonte OTC oficial — bloqueado")),
            risk = RiskState(pnl_today = today.sumOf { it.pnl }, trades_today = today.size,
                consecutive_losses = closed.sortedBy { it.closed_ms ?: 0 }.takeLastWhile { it.status == "LOSS" }.size,
                open_exposure = openT.sumOf { it.stake }, open_trades = openT.size, emergency = emergency))
    }

    fun assets(): List<AssetDto> = symbols.map { s ->
        val C = candles[s].orEmpty()
        var a = AssetDto(symbol = s, display = s, market = "NORMAL", source = "kraken", decimals = if (s.startsWith("BTC")) 1 else 2,
            price = lastPrice[s] ?: C.lastOrNull()?.c, latency_ms = latency[s], blocked = guard(s, C.size))
        if (C.size > Ai.WARMUP + 5) {
            val F = Features(C.takeLast(400)); val i = F.C.size - 1; val back = 60 / intervalMin
            a = a.copy(regime = Ai.regime(F, i), rsi = F.rsi[i], adx = F.adx[i], atr = F.atr[i], trend_5m = Ai.htfDir(F, i),
                change_1h = if (C.size > back + 1) (lastPrice[s] ?: C.last().c) / C[C.size - 1 - back].c - 1 else null)
        }
        a
    }

    fun stats(): StatsDto {
        val closed = trades.filter { it.status == "WIN" || it.status == "LOSS" }.sortedBy { it.closed_ms ?: 0 }
        fun group(f: (TradeDto) -> String) = closed.groupBy(f).map { (k, v) -> val w = v.count { it.status == "WIN" }
            val ci = Ai.wilson(w, v.size); GroupDto(k, w, v.size, w.toDouble() / v.size, listOf(ci.first, ci.second)) }.sortedByDescending { it.n }
        var eq = initialCapital
        val w = closed.count { it.status == "WIN" }
        val rr = { l: List<TradeDto> -> if (l.isEmpty()) null else l.count { it.status == "WIN" }.toDouble() / l.size }
        val det = if (closed.size >= 60) { val r = rr(closed.takeLast(30))!!; val b = rr(closed.dropLast(30))!!; DetDto(r, b, r < b - 0.1 && r < 0.5) } else null
        return StatsDto(n = closed.size, wins = w, rate = if (closed.isEmpty()) null else w.toDouble() / closed.size,
            ci = if (closed.isEmpty()) null else Ai.wilson(w, closed.size).toList(), breakeven = null, mode = "kraken_spot",
            pnl_total = Math.round(closed.sumOf { it.pnl } * 100) / 100.0, fees_total = Math.round(closed.sumOf { it.fees } * 100) / 100.0,
            by_asset = group { it.asset }, by_strategy = group { it.strategy }, by_expiry = group { it.exit_reason.ifBlank { "—" } },
            by_hour = group { "%02dh".format(java.util.Calendar.getInstance().apply { timeInMillis = it.entry_t }.get(java.util.Calendar.HOUR_OF_DAY)) },
            equity = closed.map { eq += it.pnl; EqDto(it.closed_ms, Math.round(eq * 100) / 100.0) }, deterioration = det,
            backtest = report.mapValues { (_, v) -> val (res, wf) = v
                BtDto(res.size, if (res.isEmpty()) SumDto() else SumDto(res.size, res.count { it.pnlPct > 0 }.toDouble() / res.size,
                    res.sumOf { it.pnlPct } / res.size, res.sumOf { it.grossPct } / res.size, res.sumOf { it.pnlPct }),
                    mapOf("spot" to WfDto2(wf.tested, wf.wins, if (wf.tested > 0) wf.wins.toDouble() / wf.tested else null, wf.meanPct, wf.totalPct))) })
    }

    fun strategies(): List<StrategyDto> = Ai.STRATEGIES.map { s ->
        StrategyDto(s.name, s.regimes.toList(), s.doc, s.name in enabledStrategies,
            calibrators.mapValues { (_, cal) -> cal.table.filterKeys { it.first == s.name }
                .map { (k, v) -> k.second to StrategyDto.Cal(v[3].toInt(), v[0].toInt()) }.toMap() })
    }

    fun riskSnap() = RiskSnap(risk, dashboard().risk, 0.5)
    fun settings() = SettingsDto(mode = "kraken_spot_local", spot = SpotCfgDto(spot.feeRate, spot.stopAtr, spot.targetAtr, spot.maxBars, spot.stake, intervalMin),
        database = "celular", brokers = listOf(BrokerDto("paper-spot (celular)", false)), real_execution = false,
        real_execution_note = "Simulação no celular com preços reais da Kraken. Nenhuma ordem real é enviada.")
}
