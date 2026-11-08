package com.bottrader.ai

import com.bottrader.ai.data.*
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class ApiClientTest {
    private lateinit var server: MockWebServer

    @Before fun setUp() { server = MockWebServer(); server.start() }
    @After fun tearDown() { server.shutdown() }

    private fun client() = ApiClient(server.url("/").toString())

    @Test fun loginStoresTokenAndSendsBearer() = runTest {
        server.enqueue(MockResponse().setBody("""{"access_token":"abc","token_type":"bearer","expires_min":720}"""))
        server.enqueue(MockResponse().setBody("""{"state":"RUNNING","server_time":1,"capital":1000.0,"pnl":-5.5,
            "open_trades":[],"last_trades":[{"id":"t1","asset":"BTCUSDT@binance","direction":"PUT","status":"LOSS","pnl":-10.0,"confidence":null}],
            "connections":[{"source":"binance","connected":true,"latency_ms":{"BTCUSDT@binance":120}}],"risk":{"pnl_today":-10.0},"campo_novo":123}"""))
        val c = client()
        assertEquals("abc", c.login("admin", "x"))
        val d: Dashboard = c.get("/dashboard")
        assertEquals("RUNNING", d.state)
        assertNull(d.last_trades[0].confidence)
        assertEquals(120L, d.connections[0].latency_ms["BTCUSDT@binance"])
        server.takeRequest()
        assertEquals("Bearer abc", server.takeRequest().getHeader("Authorization"))
    }

    @Test fun errorDetailIsSurfaced() = runTest {
        server.enqueue(MockResponse().setResponseCode(409).setBody("""{"detail":"Robô em STOP DE EMERGÊNCIA"}"""))
        val e = runCatching { client().raw("POST", "/bot/start") }.exceptionOrNull() as ApiException
        assertEquals(409, e.code)
        assertTrue(e.message!!.contains("EMERGÊNCIA"))
    }

    @Test fun statsParseWithTuplesAndNulls() {
        val s = JsonCfg.decodeFromString(StatsDto.serializer(), """{"n":3,"wins":2,"rate":0.666,"ci":[0.2,0.94],"breakeven":0.54,
            "by_asset":[{"key":"BTCUSDT@binance","wins":2,"n":3,"rate":0.666,"ci":[0.2,0.94]}],"equity":[{"t":1,"equity":1008.5}],
            "deterioration":null,"backtest":{"BTCUSDT@binance":{"signals":40,"walk_forward":{"1":{"tested":0,"wins":0,"rate":null,"ci":null}}}}}""")
        assertEquals(3, s.n)
        assertNull(s.deterioration)
        assertNull(s.backtest.getValue("BTCUSDT@binance").walk_forward.getValue("1").rate)
    }

    @Test fun rejectsInvalidServerUrl() {
        assertTrue(runCatching { ApiClient("nao é url") }.isFailure)
        assertTrue(ApiClient("https://bot.exemplo.com/").isSecure)
        assertEquals("https://bot.exemplo.com", ApiClient("https://bot.exemplo.com/").base)
    }
}
