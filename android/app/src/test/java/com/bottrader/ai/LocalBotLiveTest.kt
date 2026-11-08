package com.bottrader.ai

import com.bottrader.ai.local.LocalBot
import kotlinx.coroutines.*
import org.junit.Assume.assumeTrue
import org.junit.Assert.*
import org.junit.Test

/** Teste com a Kraken REAL (só roda no CI com KRAKEN_LIVE=1): o mesmo LocalBot que roda no celular. */
class LocalBotLiveTest {
    @Test fun connectsToRealKrakenAndProducesDashboard() = runBlocking {
        assumeTrue(System.getenv("KRAKEN_LIVE") == "1")
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val bot = LocalBot(null, scope = scope)
        bot.startMonitoring()
        var waited = 0
        while (waited < 90 && !(bot.wsConnected && bot.latency.size == 3)) { delay(1000); waited++ }
        val d = withContext(bot.lock) { bot.dashboard() }
        val a = withContext(bot.lock) { bot.assets() }
        val s = withContext(bot.lock) { bot.stats() }
        println("LIVE: ws=${bot.wsConnected} rest='${bot.restInfo}' offset=${bot.offsetMs}ms latência=${bot.latency} velas=${bot.candles.mapValues { it.value.size }}")
        a.forEach { println("LIVE: ${it.display} preço=${it.price} regime=${it.regime} RSI=${it.rsi?.let { r -> "%.0f".format(r) }} bloqueios=${it.blocked}") }
        s.backtest.forEach { (k, v) -> println("LIVE: backtest $k: ${v.signals} entradas · média ${v.summary?.mean_pct?.let { "%+.2f%%".format(it * 100) }} · fora da amostra ${v.walk_forward["spot"]?.tested} entradas") }
        bot.stop(); scope.cancel()
        assertTrue("WebSocket não conectou", bot.wsConnected || d.connections.first().connected)
        assertEquals(3, bot.candles.size)
        assertTrue(bot.candles.values.all { it.size > 500 })
        assertTrue("nenhuma atualização ao vivo", bot.latency.isNotEmpty())
        assertTrue(a.all { it.price != null && it.regime != null })
    }
}
