package com.bottrader.ai.data

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

val JsonCfg = Json { ignoreUnknownKeys = true; isLenient = true; explicitNulls = false; coerceInputValues = true }

@Serializable data class LoginReq(val username: String, val password: String)
@Serializable data class LoginResp(val access_token: String, val expires_min: Int = 0)
@Serializable data class TimeResp(val server_time: Long, val clock_offset_ms: Long = 0)

@Serializable
data class TradeDto(
    val id: String, val asset: String, val direction: String, val strategy: String = "",
    val stake: Double = 0.0, val payout: Double = 0.0, val expiry_min: Int = 1, val entry_t: Long = 0,
    val confidence: Double? = null, val confidence_n: Int = 0, val model_strength: Double = 0.0,
    val entry_price: Double? = null, val exit_price: Double? = null, val status: String = "",
    val pnl: Double = 0.0, val reasons: List<String> = emptyList(), val cancel_reason: String = "",
    val created_ms: Long = 0, val closed_ms: Long? = null,
)

@Serializable
data class ConnDto(val source: String, val market: String = "", val connected: Boolean = false, val error: String = "",
                   val reconnects: Int = 0, val latency_ms: Map<String, Long> = emptyMap())

@Serializable
data class RiskState(val day: String = "", val pnl_today: Double = 0.0, val trades_today: Int = 0, val consecutive_losses: Int = 0,
                     val open_exposure: Double = 0.0, val open_trades: Int = 0, val emergency: Boolean = false)

@Serializable
data class RiskCfg(val stake: Double = 10.0, val payout: Double = 0.85, val daily_loss_limit: Double = 50.0, val max_exposure: Double = 30.0,
                   val max_trades_day: Int = 20, val max_open_trades: Int = 3, val max_consecutive_losses: Int = 4,
                   val min_confidence: Double = 0.56, val allow_uncalibrated: Boolean = false)

@Serializable data class RiskSnap(val config: RiskCfg = RiskCfg(), val state: RiskState = RiskState(), val breakeven: Double = 0.54)

@Serializable
data class Dashboard(
    val state: String = "STOPPED", val server_time: Long = 0, val clock_offset_ms: Long = 0,
    val capital: Double = 0.0, val initial_capital: Double = 0.0, val pnl: Double = 0.0, val trades_total: Int = 0,
    val open_trades: List<TradeDto> = emptyList(), val win_rate: Double? = null, val breakeven: Double = 0.54,
    val assets_monitored: Int = 0, val latency_ms: Long? = null, val last_trades: List<TradeDto> = emptyList(),
    val connections: List<ConnDto> = emptyList(), val risk: RiskState = RiskState(),
)

@Serializable data class StatusResp(val state: String, val server_time: Long = 0)

@Serializable
data class AssetDto(val symbol: String, val display: String, val market: String, val source: String, val decimals: Int = 5,
                    val price: Double? = null, val latency_ms: Long? = null, val blocked: List<String> = emptyList(),
                    val regime: String? = null, val rsi: Double? = null, val adx: Double? = null, val atr: Double? = null,
                    val trend_5m: Int? = null, val change_1h: Double? = null)

@Serializable
data class OtcDto(val available: Boolean = false, val providers: List<String> = emptyList(), val message: String = "",
                  val assets: List<AssetDto> = emptyList(), val explanation: String = "")

@Serializable
data class NewsDto(val source: String, val title: String, val url: String = "", val published_ms: Long? = null, val summary: String = "",
                   val currencies: List<String> = emptyList(), val topics: List<String> = emptyList(), val relevance: Double = 0.0,
                   val impact: String = "Baixo", val reliability: Double = 0.0, val asset_impact: Map<String, String> = emptyMap())

@Serializable
data class CalDto(val title: String? = null, val currency: String? = null, val t: Long = 0, val impact: String? = null,
                  val forecast: String? = null, val previous: String? = null)

@Serializable
data class NewsResp(val items: List<NewsDto> = emptyList(), val feeds: Map<String, String> = emptyMap(), val updated_ms: Long = 0,
                    val calendar_status: String = "", val calendar: List<CalDto> = emptyList())

@Serializable
data class StrategyDto(val name: String, val regimes: List<String> = emptyList(), val doc: String = "", val enabled: Boolean = true,
                       val calibration: Map<String, Map<String, Cal>> = emptyMap()) {
    @Serializable data class Cal(val wins: Int = 0, val n: Int = 0)
}

@Serializable data class GroupDto(val key: String, val wins: Int = 0, val n: Int = 0, val rate: Double = 0.0, val ci: List<Double> = emptyList())
@Serializable data class EqDto(val t: Long? = null, val equity: Double = 0.0)
@Serializable data class DetDto(val recent: Double? = null, val before: Double? = null, val degraded: Boolean = false)
@Serializable data class WfDto(val tested: Int = 0, val wins: Int = 0, val rate: Double? = null, val ci: List<Double>? = null)
@Serializable data class BtDto(val signals: Int = 0, val walk_forward: Map<String, WfDto> = emptyMap())

@Serializable
data class StatsDto(val n: Int = 0, val wins: Int = 0, val rate: Double? = null, val ci: List<Double>? = null, val breakeven: Double = 0.54,
                    val by_asset: List<GroupDto> = emptyList(), val by_strategy: List<GroupDto> = emptyList(),
                    val by_expiry: List<GroupDto> = emptyList(), val by_hour: List<GroupDto> = emptyList(),
                    val equity: List<EqDto> = emptyList(), val deterioration: DetDto? = null, val backtest: Map<String, BtDto> = emptyMap())

@Serializable
data class DecisionDto(val id: String, val ts: Long = 0, val asset: String = "", val stage: String = "", val accepted: Boolean = false,
                       val reason: String = "", val payload: JsonElement? = null)

@Serializable data class BrokerDto(val name: String, val real_money: Boolean = false)

@Serializable
data class SettingsDto(val twelvedata_configured: Boolean = false, val redis: Boolean = false, val database: String = "",
                       val max_latency_ms: Int = 0, val news_block_min: Int = 0, val brokers: List<BrokerDto> = emptyList(),
                       val real_execution: Boolean = false, val real_execution_note: String = "")

@Serializable data class WsMsg(val type: String, val data: JsonElement? = null)
@Serializable data class Toggle(val enabled: Boolean)
