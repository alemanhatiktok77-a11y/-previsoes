package com.bottrader.ai.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.decodeFromJsonElement
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.longOrNull
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.io.IOException
import java.util.concurrent.TimeUnit

class ApiException(val code: Int, message: String) : IOException(message)

/** Cliente REST + WebSocket do backend. O app nunca guarda credenciais de corretora. */
class ApiClient(baseUrl: String, var token: String? = null) {
    val base: String = baseUrl.trim().trimEnd('/')
    val isSecure: Boolean get() = base.startsWith("https://")
    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS)
        .pingInterval(15, TimeUnit.SECONDS).retryOnConnectionFailure(true).build()
    private val jsonType = "application/json".toMediaType()

    init {
        require(base.toHttpUrlOrNull() != null) { "Endereço do servidor inválido" }
    }

    private fun parseError(r: Response): String {
        val body = r.body?.string().orEmpty()
        return runCatching { JsonCfg.parseToJsonElement(body).jsonObject["detail"]?.jsonPrimitive?.content }.getOrNull() ?: "HTTP ${r.code}"
    }

    suspend fun raw(method: String, path: String, body: String? = null): String = withContext(Dispatchers.IO) {
        val b = Request.Builder().url(base + path)
        token?.let { b.header("Authorization", "Bearer $it") }
        when (method) {
            "GET" -> b.get()
            "POST" -> b.post((body ?: "{}").toRequestBody(jsonType))
            "PUT" -> b.put((body ?: "{}").toRequestBody(jsonType))
        }
        http.newCall(b.build()).execute().use { r ->
            if (!r.isSuccessful) throw ApiException(r.code, parseError(r))
            r.body?.string().orEmpty()
        }
    }

    suspend inline fun <reified T> get(path: String): T = JsonCfg.decodeFromString(raw("GET", path))
    suspend inline fun <reified T> post(path: String, body: String? = null): T = JsonCfg.decodeFromString(raw("POST", path, body))
    suspend inline fun <reified T> put(path: String, body: String): T = JsonCfg.decodeFromString(raw("PUT", path, body))

    suspend fun login(user: String, pass: String): String {
        val r: LoginResp = post("/auth/login", JsonCfg.encodeToString(LoginReq(user, pass)))
        token = r.access_token
        return r.access_token
    }

    /** Mede ida e volta ao servidor e o desvio do relógio do celular. */
    suspend fun measureClock(): Pair<Long, Long> {
        val t0 = System.currentTimeMillis()
        val r: TimeResp = get("/time")
        val t1 = System.currentTimeMillis()
        return (t1 - t0) to (r.server_time - (t0 + t1) / 2)
    }

    suspend fun putRisk(cfg: RiskCfg): RiskSnap = put("/risk", JsonCfg.encodeToString(cfg))
    suspend fun toggleStrategy(name: String, enabled: Boolean): String =
        raw("PUT", "/strategies/" + java.net.URLEncoder.encode(name, "UTF-8").replace("+", "%20"), JsonCfg.encodeToString(Toggle(enabled)))

    fun openStream(listener: (WsMsg) -> Unit, onState: (Boolean, String) -> Unit): WebSocket {
        val wsUrl = base.replaceFirst("http", "ws") + "/ws?token=" + (token ?: "")
        return http.newWebSocket(Request.Builder().url(wsUrl).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) = onState(true, "")
            override fun onMessage(webSocket: WebSocket, text: String) {
                runCatching { JsonCfg.decodeFromString<WsMsg>(text) }.onSuccess(listener)
            }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = onState(false, if (code == 4401) "sessão expirada" else "fechado")
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = onState(false, t.message ?: "falha")
        })
    }

    companion object {
        fun serverTimeOf(msg: WsMsg): Long? = runCatching { msg.data?.jsonObject?.get("server_time")?.jsonPrimitive?.longOrNull }.getOrNull()
        inline fun <reified T> decode(msg: WsMsg): T? = runCatching { JsonCfg.decodeFromJsonElement<T>(msg.data!!) }.getOrNull()
    }
}
