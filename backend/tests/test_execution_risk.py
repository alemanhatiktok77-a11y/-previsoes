"""Testes do Risk Manager, Paper Broker, Broker Registry, Data Guard e do pipeline de execução."""
import pytest

from app.brokers.base import BrokerAdapter, BrokerCapabilities, BrokerRegistry, RealExecutionDisabled
from app.brokers.paper import PaperBroker
from app.core.models import Asset, Candle, Direction, MarketType, Opportunity, Trade, TradeStatus, Vote
from app.data.guard import DataGuard, forex_open
from app.data.providers import OTCRegistry, MarketDataProvider
from app.engine import ai_engine as ai
from app.execution import engine as ex_mod
from app.execution.engine import ExecutionEngine
from app.risk.manager import RiskConfig, RiskManager
from tests.helpers import FakeProvider, random_walk

BTC = Asset("BTCUSDT@binance", "BTC/USD", MarketType.NORMAL, "binance", 2, ("USD", "CRYPTO"))
OTC = Asset("EURUSD-OTC@none", "EUR/USD (OTC)", MarketType.OTC, "none", 5, ("EUR", "USD"))
NOW = 1_762_600_000_000  # data fixa (sábado não importa para cripto)


# ---------------------------------------------------------------- risco
def test_fixed_stake_never_increases_after_losses():
    r = RiskManager(RiskConfig(stake=10, daily_loss_limit=1000, max_consecutive_losses=99))
    for _ in range(5):
        assert r.stake_for_next_trade() == 10
        r.on_open(10, NOW)
        r.on_close(10, -10, NOW)
    assert r.stake_for_next_trade() == 10  # sem martingale


def test_daily_loss_limit_and_trade_limit():
    r = RiskManager(RiskConfig(stake=10, daily_loss_limit=25, max_trades_day=100, max_consecutive_losses=99, min_confidence=0))
    for _ in range(3):
        r.on_open(10, NOW)
        r.on_close(10, -10, NOW)
    assert any("limite diário" in m for m in r.check(NOW, 0.6))
    r2 = RiskManager(RiskConfig(max_trades_day=2, min_confidence=0))
    r2.on_open(10, NOW); r2.on_open(10, NOW)
    assert any("operações do dia" in m for m in r2.check(NOW, 0.6))


def test_exposure_and_open_limits():
    r = RiskManager(RiskConfig(stake=10, max_exposure=20, max_open_trades=5, min_confidence=0))
    r.on_open(10, NOW); r.on_open(10, NOW)
    assert any("exposição" in m for m in r.check(NOW, 0.6))


def test_consecutive_losses_pause_and_emergency():
    r = RiskManager(RiskConfig(max_consecutive_losses=2, min_confidence=0))
    for _ in range(2):
        r.on_open(10, NOW); r.on_close(10, -10, NOW)
    assert any("perdas seguidas" in m for m in r.check(NOW, 0.6))
    r.emergency_stop()
    assert any("EMERGÊNCIA" in m for m in r.check(NOW, 0.6))


def test_confidence_rules():
    r = RiskManager(RiskConfig(min_confidence=0.56))
    assert any("sem histórico" in m for m in r.check(NOW, None))
    assert any("abaixo do mínimo" in m for m in r.check(NOW, 0.52))
    assert r.check(NOW, 0.60) == []


def test_daily_reset():
    r = RiskManager(RiskConfig(daily_loss_limit=10, min_confidence=0))
    r.on_open(10, NOW); r.on_close(10, -10, NOW)
    assert r.check(NOW, 0.6)
    assert r.check(NOW + 86_400_000, 0.6) == []


def test_invalid_risk_config():
    with pytest.raises(ValueError):
        RiskConfig(stake=50, max_exposure=10)


# ---------------------------------------------------------------- paper broker
def _trade(d=Direction.CALL, stake=10):
    return Trade("x", d, "s", stake, 0.85, 1, NOW)


def test_paper_broker_win_loss_draw():
    b = PaperBroker(100)
    t = b.open_trade(_trade(), 10.0); b.settle_trade(t, 11.0)
    assert t.status == TradeStatus.WIN and t.pnl == 8.5 and b.balance() == 108.5
    t = b.open_trade(_trade(Direction.CALL), 10.0); b.settle_trade(t, 9.0)
    assert t.status == TradeStatus.LOSS and b.balance() == 98.5
    t = b.open_trade(_trade(Direction.PUT), 10.0); b.settle_trade(t, 10.0)
    assert t.status == TradeStatus.DRAW and b.balance() == 98.5


def test_paper_broker_insufficient_capital():
    b = PaperBroker(5)
    t = b.open_trade(_trade(stake=10), 1.0)
    assert t.status == TradeStatus.CANCELLED


# ---------------------------------------------------------------- registry
class FakeReal(BrokerAdapter):
    capabilities = BrokerCapabilities("real-x", True, "https://docs.example.com", True, False)
    def open_trade(self, t, p): return t
    def settle_trade(self, t, p): return t
    def balance(self): return 0


def test_real_execution_blocked_without_approval():
    reg = BrokerRegistry()
    with pytest.raises(RealExecutionDisabled):
        reg.register(FakeReal())
    reg.register(PaperBroker())
    assert reg.list() == [{"name": "paper", "real_money": False}]


# ---------------------------------------------------------------- dados
def test_guard_blocks_stale_disconnected_and_otc():
    g = DataGuard()
    p = FakeProvider()
    p.last_event_ms[BTC.symbol] = NOW
    p.latency_ms[BTC.symbol] = 150
    assert g.check(BTC, p, 1000, NOW) == []
    p.latency_ms[BTC.symbol] = 5000
    assert any("atrasados" in m for m in g.check(BTC, p, 1000, NOW))
    p.latency_ms[BTC.symbol] = 100
    assert any("sem dados" in m for m in g.check(BTC, p, 1000, NOW + 60_000))
    p.connected = False
    assert any("conexão" in m for m in g.check(BTC, p, 1000, NOW))
    assert g.check(OTC, p, 1000, NOW, OTCRegistry()) == ["sem fonte OTC confiável — operação bloqueada"]


def test_otc_registry_rejects_normal_provider_and_normal_assets():
    reg = OTCRegistry()
    class NormalP(MarketDataProvider):
        source_id = "binance"
        async def history(self, a, limit=1): return []
        async def stream(self, a, cb, s): return None
    with pytest.raises(ValueError):
        reg.register(NormalP())
    with pytest.raises(ValueError):
        reg.provider_for(BTC)
    assert reg.status()["available"] is False


def test_forex_hours():
    sat = 1_762_560_000_000  # 2025-11-08 sábado 00:00 UTC
    assert forex_open(sat) is False
    assert forex_open(sat + 2 * 86_400_000 + 12 * 3_600_000) is True  # segunda 12h


# ---------------------------------------------------------------- pipeline
def make_engine(**risk_kw):
    log, trades = [], []
    cfg = RiskConfig(**{"min_confidence": 0.0, "allow_uncalibrated": True, **risk_kw})
    eng = ExecutionEngine(PaperBroker(1000), RiskManager(cfg), DataGuard(), record=log.append, on_trade=trades.append, otc_registry=OTCRegistry())
    return eng, log, trades


def forced_op(direction=Direction.CALL):
    def fake(F, i, asset, enabled=None):
        return Opportunity(asset, "Seguidor de tendência", "TENDÊNCIA", direction, 5.0,
                           [Vote("EMAs", 1 if direction == Direction.CALL else -1, 2, "teste")], F.C[i].t, F.C[i].c), "TENDÊNCIA"
    return fake


def live_provider(t):
    p = FakeProvider()
    p.last_event_ms[BTC.symbol] = t
    p.latency_ms[BTC.symbol] = 120
    return p


def test_full_lifecycle_paper_trade(monkeypatch):
    monkeypatch.setattr(ex_mod.ai, "analyze", forced_op(Direction.CALL))
    eng, log, _ = make_engine()
    C = random_walk(300, seed=2)
    now = C[-1].t + 60_000
    t = eng.on_candle_closed(BTC, C, live_provider(now), now)
    assert t and t.status == TradeStatus.PENDING and t.entry_t == C[-1].t + 120_000
    stages = [d.stage for d in log]
    assert stages[:5] == ["opportunity", "data", "strategy", "risk", "execution"]
    # minuto seguinte fecha; a vela de entrada começa
    C.append(Candle(C[-1].t + 60_000, 100, 101, 99, 100.5))
    monkeypatch.setattr(ex_mod.ai, "analyze", lambda *a, **k: (None, "LATERAL"))
    eng.on_candle_closed(BTC, C, live_provider(now + 60_000), now + 60_000)
    eng.on_candle_update(BTC, Candle(t.entry_t, 100.0, 100.0, 100.0, 100.0), now + 61_000)
    assert t.status == TradeStatus.OPEN and t.entry_price == 100.0
    # vela de expiração fecha acima → WIN
    exit_t = t.entry_t + (t.expiry_min - 1) * 60_000
    while C[-1].t < exit_t:
        C.append(Candle(C[-1].t + 60_000, 100.0, 102, 99, 101.0))
        eng.on_candle_closed(BTC, C, live_provider(C[-1].t + 60_000), C[-1].t + 60_000)
    assert t.status == TradeStatus.WIN and t.pnl == pytest.approx(10 * 0.85)
    assert eng.broker.balance() == pytest.approx(1008.5)
    assert any(d.stage == "settlement" for d in log)
    assert eng.risk.st.open_trades == 0 and eng.risk.st.open_exposure == 0


def test_stale_data_blocks_decision(monkeypatch):
    monkeypatch.setattr(ex_mod.ai, "analyze", forced_op())
    eng, log, _ = make_engine()
    C = random_walk(300, seed=3)
    now = C[-1].t + 60_000
    p = live_provider(now)
    p.latency_ms[BTC.symbol] = 9000
    assert eng.on_candle_closed(BTC, C, p, now) is None
    assert log[-1].stage == "data" and not log[-1].accepted


def test_otc_never_trades(monkeypatch):
    monkeypatch.setattr(ex_mod.ai, "analyze", forced_op())
    eng, log, _ = make_engine()
    C = random_walk(300, seed=4)
    assert eng.on_candle_closed(OTC, C, live_provider(C[-1].t + 60_000), C[-1].t + 60_000) is None
    assert "OTC" in log[-1].reason


def test_pause_and_emergency(monkeypatch):
    monkeypatch.setattr(ex_mod.ai, "analyze", forced_op())
    eng, log, _ = make_engine()
    C = random_walk(300, seed=5)
    now = C[-1].t + 60_000
    t = eng.on_candle_closed(BTC, C, live_provider(now), now)
    eng.emergency(now + 1000)
    assert t.status == TradeStatus.CANCELLED and "EMERGÊNCIA" in t.cancel_reason
    assert eng.on_candle_closed(BTC, C, live_provider(now), now) is None
    assert eng.broker.balance() == 1000


def test_disconnection_cancels_pending_and_recovers(monkeypatch):
    """Teste de desconexão/recuperação: sem preço no horário → cancela; depois volta a operar."""
    monkeypatch.setattr(ex_mod.ai, "analyze", forced_op())
    eng, log, _ = make_engine()
    C = random_walk(300, seed=6)
    now = C[-1].t + 60_000
    t = eng.on_candle_closed(BTC, C, live_provider(now), now)
    eng.expire_stale(t.entry_t + 20_000)          # nenhum preço chegou (queda de conexão)
    assert t.status == TradeStatus.CANCELLED
    assert eng.risk.st.open_trades == 0
    C2 = C + [Candle(C[-1].t + k * 60_000, 100, 101, 99, 100) for k in range(1, 4)]
    later = C2[-1].t + 60_000
    t2 = eng.on_candle_closed(BTC, C2, live_provider(later), later)  # conexão restabelecida
    assert t2 is not None and t2.status == TradeStatus.PENDING


def test_one_trade_per_asset(monkeypatch):
    monkeypatch.setattr(ex_mod.ai, "analyze", forced_op())
    eng, log, _ = make_engine()
    C = random_walk(300, seed=7)
    now = C[-1].t + 60_000
    assert eng.on_candle_closed(BTC, C, live_provider(now), now)
    assert eng.on_candle_closed(BTC, C, live_provider(now), now) is None


def test_seed_calibration_runs_on_history():
    eng, _, _ = make_engine()
    rep = eng.seed_calibration(BTC, random_walk(1200, seed=12))
    assert rep["signals"] > 0 and set(rep["walk_forward"]) == {1, 2, 5}
