"""Testes do modo À VISTA (Kraken): leitura de dados, simulação com taxas, walk-forward e ciclo de vida."""
import pytest

from app.core.models import Asset, Candle, Direction, MarketType, Opportunity, TradeStatus, Vote
from app.data.guard import DataGuard
from app.data.providers import KrakenProvider
from app.engine import ai_engine as ai
from app.risk.manager import RiskConfig, RiskManager
from app.spot import engine as sp
from tests.helpers import FakeProvider, random_walk

BTC = Asset("BTC/EUR@kraken", "BTC/EUR", MarketType.NORMAL, "kraken", 1, ("EUR", "USD", "CRYPTO"))
M15 = 900_000


def rw15(n=700, seed=1, vol=0.003):
    C = random_walk(n, seed=seed, vol=vol)
    return [Candle(C[0].t // M15 * M15 + k * M15, x.o, x.h, x.l, x.c, x.v) for k, x in enumerate(C)]


# ---------------------------------------------------------------- dados Kraken
def test_parse_rest_drops_open_candle():
    j = {"error": [], "result": {"XXBTZEUR": [[1762600500, "60000.0", "60100.0", "59900.0", "60050.0", "60010.0", "1.5", 40],
                                              [1762601400, "60050.0", "60200.0", "60000.0", "60150.0", "60100.0", "2.0", 55]], "last": 1762601400}}
    rows = KrakenProvider.parse_rest(j, 15, now_ms=1762601400_000 + 60_000)
    assert len(rows) == 1 and rows[0].t == 1762600500_000 and rows[0].c == 60050.0 and rows[0].v == 1.5
    with pytest.raises(RuntimeError):
        KrakenProvider.parse_rest({"error": ["EQuery:Unknown asset pair"]}, 15, 0)


def test_parse_ws_v2_ohlc():
    msg = {"channel": "ohlc", "type": "update", "timestamp": "2026-11-08T16:45:12.345Z",
           "data": [{"symbol": "BTC/EUR", "open": 60000.0, "high": 60100.0, "low": 59950.0, "close": 60080.0, "trades": 12,
                     "volume": 0.8, "vwap": 60030.0, "interval_begin": "2026-11-08T16:45:00.000000000Z", "interval": 15,
                     "timestamp": "2026-11-08T16:45:12.345Z"}]}
    (sym, c, ts), = KrakenProvider.parse_ws(msg)
    assert sym == "BTC/EUR" and c.c == 60080.0 and c.t % M15 == 0 and ts - c.t == 12_345
    assert KrakenProvider.parse_ws({"channel": "heartbeat"}) == []


# ---------------------------------------------------------------- simulação com taxas
def forced(direction=Direction.CALL, every=1):
    def fake(F, i, asset, enabled=None):
        if i % every:
            return None, "LATERAL"
        return Opportunity(asset, "Rompimento", "TENDÊNCIA", direction, 5.0, [Vote("x", 1, 2, "teste")], F.C[i].t, F.C[i].c), "TENDÊNCIA"
    return fake


def test_fees_and_stop_first_when_both_touched(monkeypatch):
    C = rw15(200, seed=3, vol=0.02)
    i = ai.WARMUP + 5
    monkeypatch.setattr(sp.ai, "analyze", lambda F, k, a, e=None: forced()(F, k, a) if k == i else (None, "LATERAL"))
    F = ai.build_features(C)
    entry, a = C[i + 1].o, F.atr[i]
    x = C[i + 1]
    C[i + 1] = Candle(x.t, entry, entry + 10 * a, entry - 10 * a, entry)   # toca stop e alvo na mesma vela
    cfg = sp.SpotConfig(fee_rate=0.004)
    res = sp.simulate_spot(C, cfg)
    assert len(res) == 1 and res[0]["reason"] == "stop"
    assert res[0]["pnl_pct"] == pytest.approx(-cfg.stop_atr * a / entry - 0.008)


def test_random_walk_loses_after_fees():
    """Sem vantagem real, as taxas tornam o resultado médio negativo — o teste prova que as taxas entram na conta."""
    res = []
    for s in range(8):
        res += sp.simulate_spot(rw15(700, seed=200 + s, vol=0.01), sp.SpotConfig())
    s = sp.summary(res)
    assert s["n"] > 50 and s["mean_pct"] < 0
    assert s["mean_pct"] == pytest.approx(s["mean_gross_pct"] - 0.008, abs=1e-9)


def test_spot_backtest_no_lookahead():
    C = rw15(600, seed=9, vol=0.01)
    full = sp.simulate_spot(C, sp.SpotConfig())
    k = 450
    part = sp.simulate_spot(C[:k], sp.SpotConfig())
    done_before = [r for r in full if r["t"] + r["bars"] * M15 < C[k - 1].t]
    assert [r["t"] for r in done_before] == [r["t"] for r in part[:len(done_before)]]
    assert all(a["pnl_pct"] == b["pnl_pct"] for a, b in zip(done_before, part))


def test_walk_forward_spot_only_trades_positive_past():
    good = [{"strategy": "s", "bucket": "A", "pnl_pct": 0.01} for _ in range(60)]
    bad = [{"strategy": "s", "bucket": "A", "pnl_pct": -0.01} for _ in range(40)]
    wf = sp.walk_forward_spot(good + bad, folds=5, min_n=20)
    assert wf["tested"] > 0 and wf["folds"][0]["wins"] == wf["folds"][0]["tested"]
    wf2 = sp.walk_forward_spot(bad + bad + bad, folds=5, min_n=20)
    assert wf2["tested"] == 0


# ---------------------------------------------------------------- motor ao vivo
def make(cal_mean=0.01):
    log, trades = [], []
    eng = sp.SpotEngine(sp.PaperSpotBroker(1000, 0.004), RiskManager(RiskConfig(stake=100, payout=1.0, max_exposure=300, min_confidence=0)),
                        DataGuard(), sp.SpotConfig(stake=100), record=log.append, on_trade=trades.append, interval_min=15)
    cal = sp.SpotCalibrator(min_n=20)
    for _ in range(30):
        cal.add("Rompimento", "B", cal_mean)
    eng.calibrators[BTC.symbol] = cal
    return eng, log


def prov(t):
    p = FakeProvider()
    p.source_id = "kraken"
    p.last_event_ms[BTC.symbol] = t
    p.latency_ms[BTC.symbol] = 200
    return p


def test_spot_lifecycle_target_with_fees(monkeypatch):
    monkeypatch.setattr(sp.ai, "analyze", forced())
    eng, log = make()
    C = rw15(300, seed=4, vol=0.02)
    now = C[-1].t + M15
    t = eng.on_candle_closed(BTC, C, prov(now), now)
    assert t and t.status == TradeStatus.PENDING and t.kind == "spot" and t.entry_t == C[-1].t + M15
    eng.on_candle_update(BTC, Candle(t.entry_t, 100.0, 100.0, 100.0, 100.0), now + 1000)
    assert t.status == TradeStatus.OPEN and t.stop_price < 99.9 and t.target_price > 101.6
    assert t.quantity == pytest.approx(100 * 0.996 / 100.0)
    eng.on_candle_update(BTC, Candle(t.entry_t, 100.0, t.target_price + 0.01, 99.9, t.target_price), now + 2000)
    assert t.status == TradeStatus.WIN and t.exit_reason == "alvo"
    expected = t.quantity * t.target_price * 0.996 - 100
    assert t.pnl == pytest.approx(round(expected, 2)) and t.fees > 0.79
    assert eng.broker.balance() == pytest.approx(1000 + t.pnl, abs=0.01)
    assert eng.risk.st.open_trades == 0


def test_spot_ignores_sell_signals_and_bad_expectancy(monkeypatch):
    monkeypatch.setattr(sp.ai, "analyze", forced(Direction.PUT))
    eng, log = make()
    C = rw15(300, seed=5, vol=0.02)
    now = C[-1].t + M15
    assert eng.on_candle_closed(BTC, C, prov(now), now) is None and "só compra" in log[-1].reason

def test_spot_rejects_target_smaller_than_fees(monkeypatch):
    monkeypatch.setattr(sp.ai, "analyze", forced())
    eng, log = make()
    C = rw15(300, seed=5, vol=0.0005)
    now = C[-1].t + M15
    assert eng.on_candle_closed(BTC, C, prov(now), now) is None and "não cobre" in log[-1].reason
    monkeypatch.setattr(sp.ai, "analyze", forced())
    eng2, log2 = make(cal_mean=-0.002)
    assert eng2.on_candle_closed(BTC, C, prov(now), now) is None and "não compensa" in log2[-1].reason


def test_spot_emergency_closes_open_position(monkeypatch):
    monkeypatch.setattr(sp.ai, "analyze", forced())
    eng, log = make()
    C = rw15(300, seed=6, vol=0.02)
    now = C[-1].t + M15
    t = eng.on_candle_closed(BTC, C, prov(now), now)
    eng.on_candle_update(BTC, Candle(t.entry_t, 100.0, 100.5, 99.9, 100.2), now + 1000)
    eng.emergency(now + 2000)
    assert t.status in (TradeStatus.WIN, TradeStatus.LOSS) and t.exit_reason == "emergência" and t.exit_price == 100.2
    assert eng.on_candle_closed(BTC, C, prov(now), now) is None


def test_seed_calibration_report_shape():
    eng, _ = make()
    rep = eng.seed_calibration(BTC, rw15(700, seed=8, vol=0.01))
    assert "spot" in rep["walk_forward"] and rep["summary"]["n"] == rep["signals"]
