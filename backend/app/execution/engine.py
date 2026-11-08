"""EXECUTION ENGINE — pipeline auditável. Toda etapa gera uma Decision (aceita ou rejeitada).

  1. Identificação de oportunidade (AI ENGINE)
  2. Validação dos dados (DataGuard + calendário de risco)
  3. Seleção de estratégia / expiração com calibração histórica
  4. Verificação de risco (RiskManager)
  5. Registro da decisão
  6. Simulação de entrada (abertura do minuto de entrada)
  7. Simulação de resultado (fechamento do minuto de expiração)
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from app.brokers.base import BrokerAdapter
from app.core.models import Asset, Candle, Decision, Direction, Trade, TradeStatus
from app.data.guard import DataGuard
from app.engine import ai_engine as ai
from app.risk.manager import RiskManager

log = logging.getLogger("execution")
EXPIRIES = (1, 2, 5)


class ExecutionEngine:
    def __init__(self, broker: BrokerAdapter, risk: RiskManager, guard: DataGuard, *,
                 record: Callable[[Decision], None], on_trade: Callable[[Trade], None],
                 news_block: Callable[[Asset, int], list] = lambda a, t: [], otc_registry=None,
                 enabled_strategies: Optional[set] = None):
        self.broker, self.risk, self.guard = broker, risk, guard
        self.record, self.on_trade, self.news_block = record, on_trade, news_block
        self.otc = otc_registry
        self.enabled_strategies = enabled_strategies
        self.calibrators: dict = {}      # símbolo → Calibrator
        self.trades: list = []
        self.active = True               # False = robô pausado (não abre novas)

    # ------------------------------------------------ calibração inicial (somente passado)
    def seed_calibration(self, asset: Asset, history: list) -> dict:
        cal = ai.Calibrator()
        res = ai.simulate_outcomes(history, asset.symbol, EXPIRIES)
        for r in res:
            for e in EXPIRIES:
                if r["res"][e] != 0:
                    cal.add(r["strategy"], r["bucket"], e, r["res"][e] > 0)
        self.calibrators[asset.symbol] = cal
        return {"signals": len(res), "walk_forward": {e: ai.walk_forward(res, e, min_conf=self.risk.cfg.min_confidence) for e in EXPIRIES}}

    def _choose_expiry(self, asset: Asset, op) -> tuple:
        cal = self.calibrators.get(asset.symbol) or ai.Calibrator()
        b = ai.strength_bucket(op.strength)
        best = None
        for e in EXPIRIES:
            est = cal.estimate(op.strategy, b, e)
            if est["calibrated"] and (best is None or est["ci"][0] > best[1]["ci"][0]):
                best = (e, est)
        return best or (2, cal.estimate(op.strategy, b, 2))

    # ------------------------------------------------ fechamento de vela
    def on_candle_closed(self, asset: Asset, candles: list, provider, now_ms: int) -> Optional[Trade]:
        c = candles[-1]
        self._settle(asset, c, now_ms)
        F = ai.build_features(candles)
        op, regime = ai.analyze(F, len(candles) - 1, asset.symbol, self.enabled_strategies)
        if op is None:
            return None
        base = {"strategy": op.strategy, "regime": regime, "direction": op.direction.value, "strength": op.strength,
                "votes": [v.reason for v in op.votes]}
        self.record(Decision(asset.symbol, "opportunity", True, f"{op.strategy}: {op.direction.value} (força {op.strength})", base))

        if not self.active:
            self.record(Decision(asset.symbol, "execution", False, "robô pausado", base))
            return None
        problems = self.guard.check(asset, provider, len(candles), now_ms, self.otc) + \
            [f"evento de alto impacto: {e['currency']} {e['title']}" for e in self.news_block(asset, now_ms)]
        if problems:
            self.record(Decision(asset.symbol, "data", False, "; ".join(problems), base))
            return None
        self.record(Decision(asset.symbol, "data", True, "dados válidos e atualizados", base))

        if any(t.asset == asset.symbol and t.status in (TradeStatus.PENDING, TradeStatus.OPEN) for t in self.trades):
            self.record(Decision(asset.symbol, "strategy", False, "já existe operação em andamento neste ativo", base))
            return None
        exp, est = self._choose_expiry(asset, op)
        conf = est["p"] if est["calibrated"] else None
        self.record(Decision(asset.symbol, "strategy", True, f"expiração {exp} min · confiança {'%.1f%%' % (conf * 100) if conf else 'não calibrada'} (n={est['n']})",
                             {**base, "expiry": exp, "calibration": {k: v for k, v in est.items() if k != 'ci'}}))

        problems = self.risk.check(now_ms, conf)
        if problems:
            self.record(Decision(asset.symbol, "risk", False, "; ".join(problems), base))
            return None
        self.record(Decision(asset.symbol, "risk", True, "dentro dos limites de risco", base))

        t = Trade(asset=asset.symbol, direction=op.direction, strategy=op.strategy, stake=self.risk.stake_for_next_trade(),
                  payout=self.risk.cfg.payout, expiry_min=exp, entry_t=c.t + 120_000, confidence=conf, confidence_n=est["n"],
                  model_strength=op.strength, broker=self.broker.capabilities.name, reasons=[v.reason for v in op.votes if (v.direction > 0) == (op.direction == Direction.CALL)])
        self.trades.append(t)
        self.record(Decision(asset.symbol, "execution", True, f"entrada simulada agendada para {t.entry_t}", {"trade_id": t.id, **base}))
        self.on_trade(t)
        return t

    # ------------------------------------------------ vela em formação (preço de entrada)
    def on_candle_update(self, asset: Asset, c: Candle, now_ms: int):
        for t in self.trades:
            if t.asset == asset.symbol and t.status == TradeStatus.PENDING and c.t == t.entry_t:
                self._open(t, c.o, now_ms)

    def _open(self, t: Trade, price: float, now_ms: int):
        self.broker.open_trade(t, price)
        if t.status == TradeStatus.OPEN:
            self.risk.on_open(t.stake, now_ms)
        self.record(Decision(t.asset, "execution", t.status == TradeStatus.OPEN, f"entrada simulada @ {price}" if t.status == TradeStatus.OPEN else t.cancel_reason, {"trade_id": t.id}))
        self.on_trade(t)

    def _settle(self, asset: Asset, c: Candle, now_ms: int):
        for t in self.trades:
            if t.asset != asset.symbol:
                continue
            if t.status == TradeStatus.PENDING and c.t == t.entry_t:
                self._open(t, c.o, now_ms)
            if t.status == TradeStatus.OPEN and c.t == t.entry_t + (t.expiry_min - 1) * 60_000:
                self.broker.settle_trade(t, c.c)
                self.risk.on_close(t.stake, t.pnl, now_ms)
                if t.status in (TradeStatus.WIN, TradeStatus.LOSS):
                    cal = self.calibrators.setdefault(asset.symbol, ai.Calibrator())
                    cal.add(t.strategy, ai.strength_bucket(t.model_strength), t.expiry_min, t.status == TradeStatus.WIN)
                self.record(Decision(t.asset, "settlement", True, f"{t.status.value} {t.pnl:+.2f} (entrada {t.entry_price} → saída {t.exit_price})", {"trade_id": t.id}))
                self.on_trade(t)

    # ------------------------------------------------ manutenção
    def expire_stale(self, now_ms: int):
        for t in self.trades:
            if t.status == TradeStatus.PENDING and now_ms > t.entry_t + 15_000:
                self._cancel(t, "sem preço de entrada no horário (dados atrasados ou desconexão)", now_ms)
            elif t.status == TradeStatus.OPEN and now_ms > t.exit_t + 120_000:
                self._cancel(t, "sem preço de saída (desconexão)", now_ms)

    def _cancel(self, t: Trade, reason: str, now_ms: int):
        was_open = t.status == TradeStatus.OPEN
        if hasattr(self.broker, "cancel"):
            self.broker.cancel(t, reason)
        else:
            t.status, t.cancel_reason = TradeStatus.CANCELLED, reason
        if was_open:
            self.risk.on_close(t.stake, 0.0, now_ms)
        self.record(Decision(t.asset, "execution", False, f"operação cancelada: {reason}", {"trade_id": t.id}))
        self.on_trade(t)

    def emergency(self, now_ms: int):
        """STOP DE EMERGÊNCIA: bloqueia tudo e cancela operações ainda não iniciadas."""
        self.active = False
        self.risk.emergency_stop()
        for t in self.trades:
            if t.status == TradeStatus.PENDING:
                self._cancel(t, "STOP DE EMERGÊNCIA", now_ms)
