package com.bottrader.ai

import com.bottrader.ai.local.*
import org.junit.Assert.*
import org.junit.Test
import kotlin.random.Random

class LocalEngineTest {
    private fun walk(n: Int, seed: Int, vol: Double = 0.01, stepMs: Long = 900_000L): List<Candle> {
        val r = Random(seed); var p = 100.0; val t0 = 1_762_600_000_000L / stepMs * stepMs
        return List(n) { i ->
            val o = p; var h = o; var l = o
            repeat(6) { p *= 1 + (r.nextDouble() - 0.5) * vol; h = maxOf(h, p); l = minOf(l, p) }
            Candle(t0 + i * stepMs, o, h, l, p, r.nextDouble() * 50)
        }
    }

    @Test fun rsiMatchesWilderReference() {
        val c = doubleArrayOf(44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28)
        assertEquals(70.46, Ind.rsi(c)[14], 0.1)
    }

    @Test fun analysisNeverUsesFutureCandles() {
        val C = walk(600, 11)
        val full = Features(C); var checked = 0
        for (i in Ai.WARMUP until C.size - 10 step 7) {
            val (a, ra) = Ai.analyze(full, i)
            val (b, rb) = Ai.analyze(Features(C.subList(0, i + 1)), i)
            assertEquals(ra, rb); assertEquals(a?.dir, b?.dir); assertEquals(a?.strength, b?.strength)
            if (a != null) checked++
        }
        assertTrue(checked > 0)
    }

    @Test fun randomWalkLosesAfterFees() {
        val res = (0 until 8).flatMap { Spot.simulate(walk(700, 200 + it), SpotConfig()) }
        assertTrue(res.size > 30)
        val mean = res.sumOf { it.pnlPct } / res.size
        val gross = res.sumOf { it.grossPct } / res.size
        assertTrue("taxas precisam entrar na conta", mean < 0)
        assertEquals(gross - 0.008, mean, 1e-9)
    }

    @Test fun matchesPythonIndicatorsOnSameSeries() {
        // mesma regra de entrada/saída do backend: entrada na abertura da vela seguinte, stop tem prioridade
        val res = Spot.simulate(walk(700, 5), SpotConfig())
        res.forEach { assertTrue(it.reason in setOf("stop", "alvo", "tempo")); assertTrue(it.bars in 1..16) }
    }

    @Test fun parsesKrakenRestAndWebSocket() {
        val rest = """{"error":[],"result":{"XXBTZEUR":[[1762600500,"60000.0","60100.0","59900.0","60050.0","60010.0","1.5",40],
            [1762601400,"60050.0","60200.0","60000.0","60150.0","60100.0","2.0",55]],"last":1762601400}}"""
        val rows = KrakenClient.parseRest(rest, 15, 1762601400_000L + 60_000)
        assertEquals(1, rows.size); assertEquals(60050.0, rows[0].c, 0.0)
        val ws = """{"channel":"ohlc","type":"update","timestamp":"2026-11-08T16:45:12.345Z","data":[{"symbol":"BTC/EUR","open":60000.0,
            "high":60100.0,"low":59950.0,"close":60080.0,"trades":12,"volume":0.8,"vwap":60030.0,
            "interval_begin":"2026-11-08T16:45:00.000000000Z","interval":15,"timestamp":"2026-11-08T16:45:12.345Z"}]}"""
        val (type, list) = KrakenClient.parseWs(ws)!!
        assertEquals("update", type); assertEquals("BTC/EUR", list[0].symbol); assertEquals(12_345L, list[0].tradeTs!! - list[0].candle.t)
        assertNull(KrakenClient.parseWs("""{"channel":"heartbeat"}"""))
    }

    @Test fun walkForwardOnlyTakesPositivePast() {
        fun r(p: Double) = SimResult(0, "s", "A", 1.0, 1.0, "alvo", 1, p, p)
        val wf = Spot.walkForward(List(60) { r(0.01) } + List(40) { r(-0.01) })
        assertTrue(wf.tested > 0)
        assertEquals(0, Spot.walkForward(List(120) { r(-0.01) }).tested)
    }
}
