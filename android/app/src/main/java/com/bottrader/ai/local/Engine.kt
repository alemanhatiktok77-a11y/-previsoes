package com.bottrader.ai.local

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/* =====================================================================
   Motor de análise (porta fiel do backend Python app/engine). Tudo causal:
   o valor no índice i usa apenas dados até i. NaN = ainda sem dados.
   ===================================================================== */

data class Candle(val t: Long, val o: Double, val h: Double, val l: Double, val c: Double, val v: Double = 0.0)

object Ind {
    fun sma(a: DoubleArray, n: Int): DoubleArray {
        val o = DoubleArray(a.size) { Double.NaN }; var s = 0.0
        for (i in a.indices) { s += a[i]; if (i >= n) s -= a[i - n]; if (i >= n - 1) o[i] = s / n }
        return o
    }

    fun ema(a: DoubleArray, n: Int): DoubleArray {
        val o = DoubleArray(a.size) { Double.NaN }
        val start = a.indexOfFirst { !it.isNaN() }
        if (start < 0 || a.size - start < n) return o
        var e = 0.0; for (j in start until start + n) e += a[j]; e /= n
        o[start + n - 1] = e
        val k = 2.0 / (n + 1)
        for (i in start + n until a.size) { e = a[i] * k + e * (1 - k); o[i] = e }
        return o
    }

    fun rsi(c: DoubleArray, n: Int = 14): DoubleArray {
        val o = DoubleArray(c.size) { Double.NaN }
        if (c.size <= n) return o
        var g = 0.0; var l = 0.0
        for (i in 1..n) { val d = c[i] - c[i - 1]; g += max(d, 0.0); l += max(-d, 0.0) }
        g /= n; l /= n
        o[n] = if (l == 0.0) 100.0 else 100 - 100 / (1 + g / l)
        for (i in n + 1 until c.size) {
            val d = c[i] - c[i - 1]
            g = (g * (n - 1) + max(d, 0.0)) / n; l = (l * (n - 1) + max(-d, 0.0)) / n
            o[i] = if (l == 0.0) 100.0 else 100 - 100 / (1 + g / l)
        }
        return o
    }

    fun macdHist(c: DoubleArray): DoubleArray {
        val f = ema(c, 12); val s = ema(c, 26)
        val line = DoubleArray(c.size) { if (f[it].isNaN() || s[it].isNaN()) Double.NaN else f[it] - s[it] }
        val sig = ema(line, 9)
        return DoubleArray(c.size) { if (line[it].isNaN() || sig[it].isNaN()) Double.NaN else line[it] - sig[it] }
    }

    fun bollinger(c: DoubleArray, n: Int = 20, k: Double = 2.0): Pair<DoubleArray, DoubleArray> {
        val mid = sma(c, n); val up = DoubleArray(c.size) { Double.NaN }; val lo = DoubleArray(c.size) { Double.NaN }
        for (i in n - 1 until c.size) {
            var s = 0.0; for (j in i - n + 1..i) s += (c[j] - mid[i]) * (c[j] - mid[i])
            val sd = sqrt(s / n); up[i] = mid[i] + k * sd; lo[i] = mid[i] - k * sd
        }
        return up to lo
    }

    fun trueRange(C: List<Candle>) = DoubleArray(C.size) { i ->
        if (i == 0) C[0].h - C[0].l else max(C[i].h - C[i].l, max(abs(C[i].h - C[i - 1].c), abs(C[i].l - C[i - 1].c)))
    }

    fun wilder(a: DoubleArray, n: Int): DoubleArray {
        val o = DoubleArray(a.size) { Double.NaN }
        if (a.size < n) return o
        var s = 0.0; for (j in 0 until n) s += a[j]; o[n - 1] = s / n
        for (i in n until a.size) o[i] = (o[i - 1] * (n - 1) + a[i]) / n
        return o
    }

    fun atr(C: List<Candle>, n: Int = 14) = wilder(trueRange(C), n)

    fun adx(C: List<Candle>, n: Int = 14): DoubleArray {
        val out = DoubleArray(C.size) { Double.NaN }
        if (C.size < 2 * n + 1) return out
        val tr = trueRange(C); val pdm = DoubleArray(C.size); val ndm = DoubleArray(C.size)
        for (i in 1 until C.size) {
            val up = C[i].h - C[i - 1].h; val dn = C[i - 1].l - C[i].l
            pdm[i] = if (up > dn && up > 0) up else 0.0; ndm[i] = if (dn > up && dn > 0) dn else 0.0
        }
        val sTr = wilder(tr, n); val sP = wilder(pdm, n); val sN = wilder(ndm, n)
        val dx = DoubleArray(C.size)
        for (i in C.indices) if (!sTr[i].isNaN() && sTr[i] != 0.0) {
            val p = 100 * sP[i] / sTr[i]; val m = 100 * sN[i] / sTr[i]
            dx[i] = if (p + m == 0.0) 0.0 else 100 * abs(p - m) / (p + m)
        }
        val first = 2 * n - 1
        var s = 0.0; for (j in n..first) s += dx[j]; out[first] = s / n
        for (i in first + 1 until C.size) out[i] = (out[i - 1] * (n - 1) + dx[i]) / n
        return out
    }

    fun aggregate(C: List<Candle>, minutes: Int): List<Candle> {
        val span = minutes * 60_000L; val out = ArrayList<Candle>()
        for (x in C) {
            val b = x.t / span * span
            if (out.isNotEmpty() && out.last().t == b) {
                val cur = out.last(); out[out.size - 1] = Candle(b, cur.o, max(cur.h, x.h), min(cur.l, x.l), x.c, cur.v + x.v)
            } else out.add(Candle(b, x.o, x.h, x.l, x.c, x.v))
        }
        return out
    }

    /** Zonas de suporte/resistência (≥2 toques) usando velas até `end`. */
    fun pivotLevels(C: List<Candle>, end: Int, tol: Double, look: Int = 120, w: Int = 3): List<Pair<Double, Int>> {
        val piv = ArrayList<Double>()
        for (i in max(w, end - look)..end - w) {
            if ((1..w).all { C[i].h > C[i - it].h && C[i].h >= C[i + it].h }) piv.add(C[i].h)
            if ((1..w).all { C[i].l < C[i - it].l && C[i].l <= C[i + it].l }) piv.add(C[i].l)
        }
        piv.sort()
        val zones = ArrayList<DoubleArray>()  // [preço, toques]
        for (p in piv) {
            val z = zones.lastOrNull()
            if (z != null && p - z[0] <= tol) { z[0] = (z[0] * z[1] + p) / (z[1] + 1); z[1] += 1.0 } else zones.add(doubleArrayOf(p, 1.0))
        }
        return zones.filter { it[1] >= 2 }.map { it[0] to it[1].toInt() }
    }

    fun fibonacci(C: List<Candle>, end: Int, look: Int = 60): List<Triple<Double, Double, Boolean>> {
        val from = max(0, end - look)
        var hiI = from; var loI = from
        for (i in from..end) { if (C[i].h > C[hiI].h) hiI = i; if (C[i].l < C[loI].l) loI = i }
        val hi = C[hiI].h; val lo = C[loI].l; val upLeg = loI < hiI; val r = hi - lo
        return listOf(0.382, 0.5, 0.618).map { f -> Triple(f, if (upLeg) hi - r * f else lo + r * f, upLeg) }
    }

    fun candlePattern(C: List<Candle>, i: Int): Pair<Int, String>? {
        val x = C[i]; val p = C[i - 1]
        val body = abs(x.c - x.o); val rng = (x.h - x.l).takeIf { it > 0 } ?: 1e-12
        val upW = x.h - max(x.o, x.c); val loW = min(x.o, x.c) - x.l; val pb = abs(p.c - p.o)
        return when {
            x.c > x.o && p.c < p.o && x.c >= p.o && x.o <= p.c && body > pb -> 1 to "Engolfo de alta"
            x.c < x.o && p.c > p.o && x.o >= p.c && x.c <= p.o && body > pb -> -1 to "Engolfo de baixa"
            loW >= 2 * body && upW <= body * 0.6 && body / rng < 0.4 -> 1 to "Martelo / pin bar de alta"
            upW >= 2 * body && loW <= body * 0.6 && body / rng < 0.4 -> -1 to "Estrela cadente / pin bar de baixa"
            body / rng < 0.1 -> 0 to "Doji"
            else -> null
        }
    }
}

data class Vote(val component: String, val dir: Int, val weight: Double, val reason: String)
data class Opportunity(val strategy: String, val regime: String, val dir: Int, val strength: Double, val votes: List<Vote>)

class Features(val C: List<Candle>) {
    val close = DoubleArray(C.size) { C[it].c }
    val e9 = Ind.ema(close, 9); val e21 = Ind.ema(close, 21); val e50 = Ind.ema(close, 50)
    val rsi = Ind.rsi(close); val hist = Ind.macdHist(close)
    private val bb = Ind.bollinger(close); val bbUp = bb.first; val bbLo = bb.second
    val atr = Ind.atr(C); val adx = Ind.adx(C)
    val volMa = Ind.sma(DoubleArray(C.size) { C[it].v }, 20); val hasVol = C.any { it.v > 0 }
    val baseMin: Int = if (C.size > 1) max(1L, (C[1].t - C[0].t) / 60_000).toInt() else 1
    val htfMin: Int = if (baseMin == 1) 5 else baseMin * 4
    private val htf = Ind.aggregate(C, htfMin)
    private val htfClose = DoubleArray(htf.size) { htf[it].c }
    val hFast = Ind.ema(htfClose, 9); val hSlow = Ind.ema(htfClose, 21)
    val idxH: IntArray = run {
        val span = htfMin * 60_000L; val pos = HashMap<Long, Int>(); htf.forEachIndexed { i, x -> pos[x.t] = i }
        IntArray(C.size) { pos.getValue(C[it].t / span * span) }
    }
}

object Ai {
    const val WARMUP = 80

    fun regime(F: Features, i: Int): String {
        val a = F.atr[i]
        val win = (max(0, i - 240) until i).map { F.atr[it] }.filter { !it.isNaN() }
        if (!a.isNaN() && win.size >= 60 && win.count { it < a }.toDouble() / win.size > 0.97) return "VOLÁTIL"
        return if (!F.adx[i].isNaN() && F.adx[i] >= 23) "TENDÊNCIA" else "LATERAL"
    }

    /** Direção do timeframe superior usando apenas a vela superior já FECHADA. */
    fun htfDir(F: Features, i: Int): Int {
        val j = F.idxH[i] - 1
        if (j < 21 || F.hFast[j].isNaN() || F.hSlow[j].isNaN()) return 0
        return if (F.hFast[j] > F.hSlow[j]) 1 else -1
    }

    abstract class Strategy(val name: String, val regimes: Set<String>, val doc: String) {
        open val minVotes = 3; open val minStrength = 3.5
        abstract fun evaluate(F: Features, i: Int): List<Vote>
        fun run(F: Features, i: Int, reg: String): Opportunity? {
            val v = evaluate(F, i); if (v.isEmpty()) return null
            val score = v.sumOf { it.dir * it.weight }; val d = if (score > 0) 1 else if (score < 0) -1 else return null
            val pro = v.filter { it.dir == d }.map { it.component }.toSet(); val against = v.count { it.dir != d }
            if (pro.size < minVotes || abs(score) < minStrength || against > 1) return null
            return Opportunity(name, reg, d, Math.round(abs(score) * 100) / 100.0, v)
        }
    }

    object TrendFollowing : Strategy("Seguidor de tendência", setOf("TENDÊNCIA"),
        "Segue a tendência em pullbacks: EMAs alinhadas + timeframe superior + momentum.") {
        override fun evaluate(F: Features, i: Int): List<Vote> {
            val x = F.C[i]; val v = ArrayList<Vote>()
            val up = F.e9[i] > F.e21[i] && F.e21[i] > F.e50[i] && x.c > F.e50[i]
            val dn = F.e9[i] < F.e21[i] && F.e21[i] < F.e50[i] && x.c < F.e50[i]
            if (!(up || dn)) return v
            val d = if (up) 1 else -1
            v.add(Vote("EMAs 9/21/50", d, 2.0, "EMAs alinhadas ${if (up) "para cima" else "para baixo"} · ADX ${"%.0f".format(F.adx[i])}"))
            val t = htfDir(F, i); if (t != 0) v.add(Vote("Timeframe superior", t, 1.0, "EMA 9 ${if (t > 0) "acima" else "abaixo"} da EMA 21 no gráfico de ${F.htfMin} min"))
            val h = F.hist[i]; val hp = F.hist[i - 1]
            if (!h.isNaN() && !hp.isNaN() && (h > 0) == (d > 0) && abs(h) >= abs(hp)) v.add(Vote("MACD", d, 1.0, "Histograma do MACD a favor e crescendo"))
            val r = F.rsi[i]
            if (!r.isNaN() && ((d > 0 && r > 50 && r < 70) || (d < 0 && r > 30 && r < 50))) v.add(Vote("RSI", d, 0.75, "RSI ${"%.0f".format(r)} confirma força sem exaustão"))
            val a = F.atr[i].takeIf { !it.isNaN() } ?: 1e-12
            val near = if (d > 0) abs(F.C[i - 1].l - F.e21[i - 1]) < 0.5 * a else abs(F.C[i - 1].h - F.e21[i - 1]) < 0.5 * a
            if (near && (x.c > x.o) == (d > 0)) v.add(Vote("Pullback", d, 1.25, "Correção até a EMA 21 seguida de vela a favor"))
            return v
        }
    }

    object MeanReversion : Strategy("Reversão à média", setOf("LATERAL"),
        "Reversão em mercado lateral: extremos de Bollinger/RSI + reação em suporte/resistência.") {
        override fun evaluate(F: Features, i: Int): List<Vote> {
            val x = F.C[i]; val v = ArrayList<Vote>(); val a = F.atr[i].takeIf { !it.isNaN() } ?: 1e-12
            if (!F.bbLo[i].isNaN()) {
                if (x.l < F.bbLo[i] && x.c > F.bbLo[i]) v.add(Vote("Bollinger", 1, 1.5, "Rejeição abaixo da banda inferior"))
                else if (x.h > F.bbUp[i] && x.c < F.bbUp[i]) v.add(Vote("Bollinger", -1, 1.5, "Rejeição acima da banda superior"))
            }
            val r = F.rsi[i]
            if (!r.isNaN() && r <= 30) v.add(Vote("RSI", 1, 1.25, "RSI ${"%.0f".format(r)} sobrevendido"))
            else if (!r.isNaN() && r >= 70) v.add(Vote("RSI", -1, 1.25, "RSI ${"%.0f".format(r)} sobrecomprado"))
            for ((p, n) in Ind.pivotLevels(F.C, i - 1, 0.5 * a)) {
                if (abs(x.l - p) < 0.3 * a && x.c > x.o) { v.add(Vote("Suporte", 1, 1.25, "Reação compradora no suporte ${"%.6g".format(p)} ($n toques)")); break }
                if (abs(x.h - p) < 0.3 * a && x.c < x.o) { v.add(Vote("Resistência", -1, 1.25, "Reação vendedora na resistência ${"%.6g".format(p)} ($n toques)")); break }
            }
            Ind.candlePattern(F.C, i)?.let { (d, name) -> if (d != 0) v.add(Vote("Vela", d, 1.0, name)) }
            for ((f, p, upLeg) in Ind.fibonacci(F.C, i - 1)) {
                if (x.l <= p && p <= x.h) {
                    val d = if (x.c > x.o) 1 else if (x.c < x.o) -1 else 0
                    if (d != 0 && (d > 0) == upLeg) v.add(Vote("Fibonacci", d, 0.5, "Reação na retração de ${"%.1f".format(f * 100)}%"))
                    break
                }
            }
            return v
        }
    }

    object Breakout : Strategy("Rompimento", setOf("TENDÊNCIA", "LATERAL"),
        "Rompimento de zona com expansão de volatilidade (e volume); também falsos rompimentos.") {
        override fun evaluate(F: Features, i: Int): List<Vote> {
            val x = F.C[i]; val prev = F.C[i - 1]; val v = ArrayList<Vote>(); val a = F.atr[i].takeIf { !it.isNaN() } ?: 1e-12
            for ((p, n) in Ind.pivotLevels(F.C, i - 1, 0.5 * a)) {
                val s = "%.6g".format(p)
                if (prev.c <= p && x.c > p + 0.25 * a && x.c > x.o) { v.add(Vote("Rompimento", 1, 2.0, "Fechou acima da resistência $s ($n toques)")); break }
                if (prev.c >= p && x.c < p - 0.25 * a && x.c < x.o) { v.add(Vote("Rompimento", -1, 2.0, "Fechou abaixo do suporte $s ($n toques)")); break }
                if (x.h > p + 0.1 * a && x.c < p && prev.c < p) { v.add(Vote("Falso rompimento", -1, 2.0, "Pavio acima de $s e fechamento abaixo")); break }
                if (x.l < p - 0.1 * a && x.c > p && prev.c > p) { v.add(Vote("Falso rompimento", 1, 2.0, "Pavio abaixo de $s e fechamento acima")); break }
            }
            if (v.isEmpty()) return v
            val d = v[0].dir
            if (x.h - x.l > 1.3 * a) v.add(Vote("Expansão", d, 1.0, "Vela ${"%.1f".format((x.h - x.l) / a)}× o ATR"))
            if (F.hasVol && !F.volMa[i].isNaN() && F.volMa[i] > 0 && x.v > 1.5 * F.volMa[i]) v.add(Vote("Volume", d, 1.0, "Volume ${"%.1f".format(x.v / F.volMa[i])}× a média"))
            val t = htfDir(F, i); if (t != 0) v.add(Vote("Timeframe superior", t, 0.75, "Direção do gráfico de ${F.htfMin} min"))
            return v
        }
    }

    val STRATEGIES: List<Strategy> = listOf(TrendFollowing, MeanReversion, Breakout)

    fun analyze(F: Features, i: Int, enabled: Set<String>? = null): Pair<Opportunity?, String> {
        if (i < WARMUP || F.adx[i].isNaN() || F.e50[i].isNaN() || F.atr[i].isNaN()) return null to "AQUECENDO"
        val reg = regime(F, i)
        if (reg == "VOLÁTIL") return null to reg
        var best: Opportunity? = null
        for (s in STRATEGIES) {
            if (enabled != null && s.name !in enabled) continue
            if (reg !in s.regimes) continue
            val op = s.run(F, i, reg)
            if (op != null && (best == null || op.strength > best.strength)) best = op
        }
        return best to reg
    }

    fun bucket(s: Double) = if (s >= 6) "A" else if (s >= 4.5) "B" else "C"

    fun wilson(k: Int, n: Int, z: Double = 1.96): Pair<Double, Double> {
        if (n == 0) return 0.0 to 1.0
        val p = k.toDouble() / n; val d = 1 + z * z / n; val c = p + z * z / (2 * n)
        val m = z * sqrt(p * (1 - p) / n + z * z / (4.0 * n * n))
        return (c - m) / d to (c + m) / d
    }
}

/* ---------------------------------------------------------------- operações à vista */
data class SpotConfig(val feeRate: Double = 0.004, val stopAtr: Double = 1.5, val targetAtr: Double = 2.5, val maxBars: Int = 16,
                      var stake: Double = 100.0, val minTradesCalib: Int = 20, val minRewardVsCost: Double = 2.0) {
    val roundTrip get() = 2 * feeRate
}

data class SimResult(val t: Long, val strategy: String, val bucket: String, val entry: Double, val exit: Double, val reason: String,
                     val bars: Int, val pnlPct: Double, val grossPct: Double)

object Spot {
    /** Backtest causal com taxas: decisão no fechamento da vela i, entrada na abertura de i+1. Stop tem prioridade sobre o alvo. */
    fun simulate(C: List<Candle>, cfg: SpotConfig): List<SimResult> {
        val F = Features(C); val out = ArrayList<SimResult>(); var busy = -1
        for (i in Ai.WARMUP until C.size - 2) {
            if (i <= busy) continue
            val (op, _) = Ai.analyze(F, i)
            if (op == null || op.dir != 1) continue
            val a = F.atr[i]
            if (cfg.targetAtr * a / C[i].c < cfg.minRewardVsCost * cfg.roundTrip) continue
            val entry = C[i + 1].o; val stop = entry - cfg.stopAtr * a; val target = entry + cfg.targetAtr * a
            var done: Triple<Int, Double, String>? = null
            for (j in i + 1 until min(C.size, i + 1 + cfg.maxBars)) {
                val x = C[j]
                if (x.l <= stop) { done = Triple(j, if (x.o < stop) x.o else stop, "stop"); break }
                if (x.h >= target) { done = Triple(j, if (x.o > target) x.o else target, "alvo"); break }
                if (j == i + cfg.maxBars) { done = Triple(j, x.c, "tempo"); break }
            }
            val (j, px, why) = done ?: break
            out.add(SimResult(C[i + 1].t, op.strategy, Ai.bucket(op.strength), entry, px, why, j - i, px / entry - 1 - cfg.roundTrip, px / entry - 1))
            busy = j
        }
        return out
    }

    class Calibrator(val minN: Int = 20) {
        val table = HashMap<Pair<String, String>, DoubleArray>()   // n, soma, soma², vitórias
        fun add(strategy: String, bucket: String, pnl: Double) {
            val s = table.getOrPut(strategy to bucket) { DoubleArray(4) }
            s[0] += 1.0; s[1] += pnl; s[2] += pnl * pnl; if (pnl > 0) s[3] += 1.0
        }
        data class Est(val calibrated: Boolean, val n: Int, val mean: Double = 0.0, val meanLow: Double = 0.0, val winRate: Double = 0.0)
        fun estimate(strategy: String, bucket: String): Est {
            var s = table[strategy to bucket] ?: DoubleArray(4)
            if (s[0] < minN) {
                val rows = table.filterKeys { it.first == strategy }.values
                s = DoubleArray(4) { k -> rows.sumOf { it[k] } }
            }
            val n = s[0].toInt(); if (n < minN) return Est(false, n)
            val mean = s[1] / n; val sd = sqrt(max(0.0, s[2] / n - mean * mean)); val se = if (n > 1) sd / sqrt(n.toDouble()) else Double.MAX_VALUE
            return Est(true, n, mean, mean - se, s[3] / n)
        }
    }

    data class WalkForward(val tested: Int, val wins: Int, val meanPct: Double?, val totalPct: Double?)

    fun walkForward(results: List<SimResult>, folds: Int = 5, minN: Int = 20): WalkForward {
        if (results.size < folds * 4) return WalkForward(0, 0, null, null)
        val size = results.size / folds; val taken = ArrayList<SimResult>()
        for (k in 1 until folds) {
            val cal = Calibrator(minN); results.subList(0, k * size).forEach { cal.add(it.strategy, it.bucket, it.pnlPct) }
            results.subList(k * size, min(results.size, (k + 1) * size)).forEach { r ->
                val e = cal.estimate(r.strategy, r.bucket); if (e.calibrated && e.meanLow > 0) taken.add(r)
            }
        }
        if (taken.isEmpty()) return WalkForward(0, 0, null, null)
        return WalkForward(taken.size, taken.count { it.pnlPct > 0 }, taken.sumOf { it.pnlPct } / taken.size, taken.sumOf { it.pnlPct })
    }
}
