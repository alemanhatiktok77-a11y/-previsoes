package com.bottrader.ai.local

import kotlinx.serialization.json.*
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.time.Instant
import java.util.concurrent.TimeUnit

/** API pública OFICIAL da Kraken (sem conta, sem chave).
 *  REST  GET https://api.kraken.com/0/public/OHLC   ·   WS v2 wss://ws.kraken.com/v2 canal "ohlc" */
class KrakenClient(private val http: OkHttpClient = OkHttpClient.Builder().connectTimeout(10, TimeUnit.SECONDS)
    .readTimeout(20, TimeUnit.SECONDS).pingInterval(20, TimeUnit.SECONDS).build()) {

    companion object {
        val REST_PAIR = mapOf("BTC/EUR" to "XBTEUR", "ETH/EUR" to "ETHEUR", "SOL/EUR" to "SOLEUR")

        fun parseRest(body: String, intervalMin: Int, nowMs: Long): List<Candle> {
            val j = Json.parseToJsonElement(body).jsonObject
            val err = j["error"]?.jsonArray
            if (err != null && err.isNotEmpty()) throw IllegalStateException(err.joinToString { it.jsonPrimitive.content })
            val res = j.getValue("result").jsonObject
            val key = res.keys.first { it != "last" }
            val rows = res.getValue(key).jsonArray.map { r ->
                val a = r.jsonArray
                Candle(a[0].jsonPrimitive.long * 1000, a[1].jsonPrimitive.content.toDouble(), a[2].jsonPrimitive.content.toDouble(),
                    a[3].jsonPrimitive.content.toDouble(), a[4].jsonPrimitive.content.toDouble(), a[6].jsonPrimitive.content.toDouble())
            }.toMutableList()
            if (rows.isNotEmpty() && rows.last().t + intervalMin * 60_000L > nowMs) rows.removeAt(rows.size - 1)  // vela em formação
            return rows
        }

        data class WsRow(val symbol: String, val candle: Candle, val tradeTs: Long?)

        /** Retorna (tipo, linhas) para mensagens do canal ohlc; null para outras. */
        fun parseWs(text: String): Pair<String, List<WsRow>>? {
            val j = runCatching { Json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return null
            if (j["channel"]?.jsonPrimitive?.content != "ohlc") return null
            val type = j["type"]?.jsonPrimitive?.content ?: return null
            val rows = j["data"]?.jsonArray?.map { e ->
                val d = e.jsonObject
                fun num(k: String) = d.getValue(k).jsonPrimitive.double
                WsRow(d.getValue("symbol").jsonPrimitive.content,
                    Candle(Instant.parse(d.getValue("interval_begin").jsonPrimitive.content).toEpochMilli(), num("open"), num("high"), num("low"), num("close"),
                        d["volume"]?.jsonPrimitive?.doubleOrNull ?: 0.0),
                    d["timestamp"]?.jsonPrimitive?.contentOrNull?.let { Instant.parse(it).toEpochMilli() })
            } ?: emptyList()
            return type to rows
        }
    }

    fun ohlc(symbol: String, intervalMin: Int, nowMs: Long): List<Candle> {
        val url = "https://api.kraken.com/0/public/OHLC?pair=${REST_PAIR.getValue(symbol)}&interval=$intervalMin"
        http.newCall(Request.Builder().url(url).build()).execute().use { r ->
            if (!r.isSuccessful) throw IllegalStateException("HTTP ${r.code}")
            return parseRest(r.body!!.string(), intervalMin, nowMs)
        }
    }

    /** Diferença entre o relógio da Kraken e o do celular (resolução de 1 s). */
    fun clockOffset(): Long {
        val t0 = System.currentTimeMillis()
        val body = http.newCall(Request.Builder().url("https://api.kraken.com/0/public/Time").build()).execute().use { it.body!!.string() }
        val t1 = System.currentTimeMillis()
        val unix = Json.parseToJsonElement(body).jsonObject.getValue("result").jsonObject.getValue("unixtime").jsonPrimitive.long
        return unix * 1000 - (t0 + t1) / 2
    }

    fun stream(symbols: List<String>, intervalMin: Int, onText: (String) -> Unit, onState: (Boolean, String) -> Unit): WebSocket {
        val sub = buildJsonObject {
            put("method", "subscribe")
            putJsonObject("params") { put("channel", "ohlc"); putJsonArray("symbol") { symbols.forEach { add(it) } }; put("interval", intervalMin) }
        }.toString()
        return http.newWebSocket(Request.Builder().url("wss://ws.kraken.com/v2").build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { webSocket.send(sub); onState(true, "") }
            override fun onMessage(webSocket: WebSocket, text: String) = onText(text)
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = onState(false, "fechado")
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = onState(false, t.message ?: "falha")
        })
    }
}
