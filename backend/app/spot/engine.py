"""Operações À VISTA (spot) — compra com stop de perda, alvo de lucro e tempo máximo, taxas incluídas.

Diferenças em relação às opções binárias:
  * Só COMPRA (em spot não dá para vender o que não se tem). Sinais de queda viram "não comprar".
  * Resultado = variação real do preço − taxas de entrada e saída (sem payout fixo).
  * Stop e alvo proporcionais ao ATR; se a vela tocar os dois, assume o STOP (conservador).
Regras de tempo: decisão no fechamento da vela i; entrada na abertura da vela i+1; nada do futuro é usado.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.brokers.base import BrokerAdapter, BrokerCapabilities
from app.core.models import Asset, Candle, Decision, Direction, Trade, TradeStatus, now_ms
from app.data.guard import DataGuard
from app.engine import ai_engine as ai
from app.risk.manager import RiskManager

log = logging.getLogger("spot")


@dataclass
class SpotConfig:
    fee_rate: float = 0.004       # taxa por lado (Kraken Pro, ordem a mercado/taker, nível inicial)
    stop_atr: float = 1.5
    target_atr: float = 2.5
    max_bars: int = 16            # tempo máximo na posição (16 velas de 15 min = 4 h)
    stake: float = 100.0          # valor fixo por compra (EUR)
    min_trades_calib: int = 20    # mínimo de operações passadas para confiar na estatística
    min_reward_vs_cost: float = 2.0  # o alvo precisa valer pelo menos 2× o custo das taxas

    def round_trip_cost(self) -> float:
        return 2 * self.fee_rate


def _exit_scan(C: list, start: int, entry: float, stop: float, target: float, max_bars: int):
    """Percorre as velas a partir de `start` (vela de entrada) até sair. Retorna (índice, preço, motivo) ou None."""
    for j in range(start, min(len(C), start + max_bars)):
        x = C[j]
        if x.l <= stop:
            return j, min(stop, x.o) if x.o < stop else stop, "stop"     # gap abaixo do stop: sai na abertura
        if x.h >= target:
            return j, max(target, x.o) if x.o > target else target, "alvo"
        if j == start + max_bars - 1:
            return j, x.c, "tempo"
    return None


def simulate_spot(C: list, cfg: SpotConfig, asset: str = "bt") -> list:
    """Backtest causal com taxas. Uma posição por vez."""
    F = ai.build_features(C)
    out, busy_until = [], -1
    for i in range(ai.WARMUP, len(C) - 2):
        if i <= busy_until:
            continue
        op, reg = ai.analyze(F, i, asset)
        if not op or op.direction != Direction.CALL:
            continue
        a = F.atr[i]
        if cfg.target_atr * a / C[i].c < cfg.min_reward_vs_cost * cfg.round_trip_cost():
            continue  # alvo pequeno demais: as taxas comeriam o lucro
        entry = C[i + 1].o
        stop, target = entry - cfg.stop_atr * a, entry + cfg.target_atr * a
        ex = _exit_scan(C, i + 1, entry, stop, target, cfg.max_bars)
        if ex is None:
            break
        j, px, why = ex
        pnl_pct = (px / entry - 1) - cfg.round_trip_cost()
        out.append({"t": C[i + 1].t, "strategy": op.strategy, "bucket": ai.strength_bucket(op.strength), "regime": reg,
                    "entry": entry, "exit": px, "reason": why, "bars": j - i, "pnl_pct": pnl_pct, "gross_pct": px / entry - 1})
        busy_until = j
    return out


@dataclass
class SpotCalibrator:
    """Resultado médio líquido (após taxas) observado no PASSADO por estratégia e faixa de força."""
    min_n: int = 20
    table: dict = field(default_factory=dict)

    def add(self, strategy: str, bucket: str, pnl_pct: float):
        s = self.table.setdefault((strategy, bucket), [0, 0.0, 0.0, 0])  # n, soma, soma², vitórias
        s[0] += 1; s[1] += pnl_pct; s[2] += pnl_pct * pnl_pct; s[3] += pnl_pct > 0

    def estimate(self, strategy: str, bucket: str) -> dict:
        n, sm, sq, w = self.table.get((strategy, bucket), [0, 0.0, 0.0, 0])
        if n < self.min_n:
            rows = [v for k, v in self.table.items() if k[0] == strategy]
            n, sm, sq, w = (sum(r[i] for r in rows) for i in range(4)) if rows else (0, 0.0, 0.0, 0)
        if n < self.min_n:
            return {"calibrated": False, "n": n}
        mean = sm / n
        sd = math.sqrt(max(0.0, sq / n - mean * mean))
        se = sd / math.sqrt(n) if n > 1 else float("inf")
        return {"calibrated": True, "n": n, "mean_pct": mean, "mean_low_pct": mean - 1.0 * se, "win_rate": w / n, "ci": ai.wilson(int(w), n)}


def walk_forward_spot(results: list, folds: int = 5, min_n: int = 20) -> dict:
    """Calibra com blocos anteriores e só "opera" no bloco seguinte o que tinha expectativa positiva no passado."""
    if len(results) < folds * 4:
        return {"tested": 0, "wins": 0, "rate": None, "mean_pct": None, "total_pct": None, "folds": []}
    size = len(results) // folds
    taken, fstats = [], []
    for k in range(1, folds):
        cal = SpotCalibrator(min_n=min_n)
        for r in results[:k * size]:
            cal.add(r["strategy"], r["bucket"], r["pnl_pct"])
        sel = [r for r in results[k * size:(k + 1) * size]
               if (e := cal.estimate(r["strategy"], r["bucket"]))["calibrated"] and e["mean_low_pct"] > 0]
        fstats.append({"fold": k, "tested": len(sel), "wins": sum(r["pnl_pct"] > 0 for r in sel)})
        taken += sel
    w = sum(r["pnl_pct"] > 0 for r in taken)
    return {"tested": len(taken), "wins": w, "rate": w / len(taken) if taken else None,
            "ci": ai.wilson(w, len(taken)) if taken else None,
            "mean_pct": sum(r["pnl_pct"] for r in taken) / len(taken) if taken else None,
            "total_pct": sum(r["pnl_pct"] for r in taken) if taken else None, "folds": fstats}


def summary(results: list) -> dict:
    n = len(results)
    if not n:
        return {"n": 0}
    w = sum(r["pnl_pct"] > 0 for r in results)
    return {"n": n, "win_rate": w / n, "mean_pct": sum(r["pnl_pct"] for r in results) / n,
            "mean_gross_pct": sum(r["gross_pct"] for r in results) / n, "total_pct": sum(r["pnl_pct"] for r in results),
            "by_reason": {k: sum(r["reason"] == k for r in results) for k in ("stop", "alvo", "tempo")}}


class PaperSpotBroker(BrokerAdapter):
    """Conta à vista simulada em EUR, com taxas."""
    capabilities = BrokerCapabilities(name="paper-spot", real_money=False, official_api_docs="", supports_binary_options=False, supports_otc=False)

    def __init__(self, initial_capital: float = 1000.0, fee_rate: float = 0.004):
        self.initial, self.cash, self.fee = initial_capital, initial_capital, fee_rate

    def balance(self) -> float:
        return round(self.cash, 2)

    def open_trade(self, t: Trade, price: float) -> Trade:
        cost = t.stake
        if cost > self.cash:
            t.status, t.cancel_reason = TradeStatus.CANCELLED, "capital simulado insuficiente"
            return t
        fee = cost * self.fee
        t.quantity = (cost - fee) / price
        t.fees, t.entry_price, t.status = fee, price, TradeStatus.OPEN
        self.cash -= cost
        return t

    def settle_trade(self, t: Trade, exit_price: float) -> Trade:
        if t.status != TradeStatus.OPEN:
            return t
        gross = t.quantity * exit_price
        fee = gross * self.fee
        self.cash += gross - fee
        t.fees += fee
        t.exit_price = exit_price
        t.pnl = round(gross - fee - t.stake, 2)
        t.status = TradeStatus.WIN if t.pnl > 0 else TradeStatus.LOSS if t.pnl < 0 else TradeStatus.DRAW
        t.closed_ms = now_ms()
        return t

    def cancel(self, t: Trade, reason: str) -> Trade:
        if t.status == TradeStatus.OPEN and t.exit_price is None:   # fecha a posição no último preço de entrada (sem perda) — só simulação
            self.cash += t.stake
        t.status, t.cancel_reason, t.closed_ms = TradeStatus.CANCELLED, reason, now_ms()
        return t

    def reset(self, capital: float | None = None):
        self.initial = capital or self.initial
        self.cash = self.initial


class SpotEngine:
    """Mesma interface do ExecutionEngine (binário), para o orquestrador usar qualquer um dos dois."""

    def __init__(self, broker: PaperSpotBroker, risk: RiskManager, guard: DataGuard, cfg: SpotConfig, *,
                 record: Callable[[Decision], None], on_trade: Callable[[Trade], None],
                 news_block: Callable[[Asset, int], list] = lambda a, t: [], otc_registry=None, interval_min: int = 15):
        self.broker, self.risk, self.guard, self.cfg = broker, risk, guard, cfg
        self.record, self.on_trade, self.news_block, self.otc = record, on_trade, news_block, otc_registry
        self.interval_ms = interval_min * 60_000
        self.calibrators: dict = {}
        self.trades: list = []
        self.active = True
        self.enabled_strategies: Optional[set] = None
        self.last_price: dict = {}

    def seed_calibration(self, asset: Asset, history: list) -> dict:
        res = simulate_spot(history, self.cfg, asset.symbol)
        cal = SpotCalibrator(min_n=self.cfg.min_trades_calib)
        for r in res:
            cal.add(r["strategy"], r["bucket"], r["pnl_pct"])
        self.calibrators[asset.symbol] = cal
        return {"signals": len(res), "summary": summary(res), "walk_forward": {"spot": walk_forward_spot(res, min_n=self.cfg.min_trades_calib)}}

    def on_candle_closed(self, asset: Asset, candles: list, provider, now: int) -> Optional[Trade]:
        c = candles[-1]
        self._manage(asset, c, closed=True)
        F = ai.build_features(candles)
        i = len(candles) - 1
        op, regime = ai.analyze(F, i, asset.symbol, self.enabled_strategies)
        if op is None:
            return None
        base = {"strategy": op.strategy, "regime": regime, "direction": op.direction.value, "strength": op.strength, "votes": [v.reason for v in op.votes]}
        if op.direction != Direction.CALL:
            self.record(Decision(asset.symbol, "opportunity", False, f"{op.strategy}: sinal de QUEDA — à vista só compra, então não entra", base))
            return None
        self.record(Decision(asset.symbol, "opportunity", True, f"{op.strategy}: COMPRA (força {op.strength})", base))
        if not self.active:
            self.record(Decision(asset.symbol, "execution", False, "robô pausado", base)); return None
        problems = self.guard.check(asset, provider, len(candles), now, self.otc) + \
            [f"evento de alto impacto: {e['currency']} {e['title']}" for e in self.news_block(asset, now)]
        if problems:
            self.record(Decision(asset.symbol, "data", False, "; ".join(problems), base)); return None
        self.record(Decision(asset.symbol, "data", True, "dados válidos e atualizados", base))
        if any(t.asset == asset.symbol and t.status in (TradeStatus.PENDING, TradeStatus.OPEN) for t in self.trades):
            self.record(Decision(asset.symbol, "strategy", False, "já existe posição neste ativo", base)); return None
        est = (self.calibrators.get(asset.symbol) or SpotCalibrator(min_n=self.cfg.min_trades_calib)).estimate(op.strategy, ai.strength_bucket(op.strength))
        if not est["calibrated"]:
            self.record(Decision(asset.symbol, "strategy", False, f"histórico insuficiente para esta estratégia (n={est['n']})", base)); return None
        if est["mean_low_pct"] <= 0:
            self.record(Decision(asset.symbol, "strategy", False,
                                 f"no passado, depois das taxas, este tipo de entrada deu {est['mean_pct'] * 100:+.2f}% em média (n={est['n']}) — não compensa", base))
            return None
        self.record(Decision(asset.symbol, "strategy", True, f"resultado médio passado {est['mean_pct'] * 100:+.2f}% após taxas (n={est['n']})", {**base, "calibration": est}))
        reward = self.cfg.target_atr * F.atr[i] / c.c
        if reward < self.cfg.min_reward_vs_cost * self.cfg.round_trip_cost():
            self.record(Decision(asset.symbol, "strategy", False,
                                 f"alvo de {reward * 100:.2f}% não cobre {self.cfg.min_reward_vs_cost:.0f}× as taxas ({self.cfg.round_trip_cost() * 100:.2f}%)", base))
            return None
        problems = self.risk.check(now, est["win_rate"])
        if problems:
            self.record(Decision(asset.symbol, "risk", False, "; ".join(problems), base)); return None
        self.record(Decision(asset.symbol, "risk", True, "dentro dos limites de risco", base))
        a = F.atr[i]
        t = Trade(asset=asset.symbol, direction=Direction.CALL, strategy=op.strategy, stake=self.cfg.stake, payout=0.0,
                  expiry_min=self.cfg.max_bars * self.interval_ms // 60_000, entry_t=c.t + self.interval_ms,
                  confidence=est["win_rate"], confidence_n=est["n"], model_strength=op.strength, broker=self.broker.capabilities.name,
                  reasons=[v.reason for v in op.votes if v.direction > 0], kind="spot")
        t._atr = a  # usado para calcular stop/alvo no preço real de entrada
        self.trades.append(t)
        self.record(Decision(asset.symbol, "execution", True, "compra simulada na abertura da próxima vela", {"trade_id": t.id, **base}))
        self.on_trade(t)
        return t

    def on_candle_update(self, asset: Asset, c: Candle, now: int):
        self._manage(asset, c, closed=False)

    def _manage(self, asset: Asset, c: Candle, closed: bool):
        self.last_price[asset.symbol] = c.c
        for t in self.trades:
            if t.asset != asset.symbol:
                continue
            if t.status == TradeStatus.PENDING and c.t >= t.entry_t:
                if c.t > t.entry_t:
                    self._cancel(t, "vela de entrada não recebida"); continue
                self.broker.open_trade(t, c.o)
                if t.status == TradeStatus.OPEN:
                    a = getattr(t, "_atr", 0) or 0
                    t.stop_price, t.target_price = c.o - self.cfg.stop_atr * a, c.o + self.cfg.target_atr * a
                    self.risk.on_open(t.stake, now_ms())
                    self.record(Decision(t.asset, "execution", True, f"compra simulada @ {c.o} · stop {t.stop_price:.6g} · alvo {t.target_price:.6g}", {"trade_id": t.id}))
                self.on_trade(t)
            if t.status == TradeStatus.OPEN and c.t >= t.entry_t:
                why = px = None
                if c.l <= t.stop_price:
                    why, px = "stop", min(t.stop_price, c.o) if c.o < t.stop_price else t.stop_price
                elif c.h >= t.target_price:
                    why, px = "alvo", max(t.target_price, c.o) if c.o > t.target_price else t.target_price
                elif closed and c.t >= t.entry_t + (self.cfg.max_bars - 1) * self.interval_ms:
                    why, px = "tempo", c.c
                if why:
                    self.broker.settle_trade(t, px)
                    t.exit_reason = why
                    self.risk.on_close(t.stake, t.pnl, now_ms())
                    cal = self.calibrators.setdefault(t.asset, SpotCalibrator(min_n=self.cfg.min_trades_calib))
                    cal.add(t.strategy, ai.strength_bucket(t.model_strength), t.exit_price / t.entry_price - 1 - self.cfg.round_trip_cost())
                    self.record(Decision(t.asset, "settlement", True, f"saída por {why}: {t.status.value} {t.pnl:+.2f} € (taxas {t.fees:.2f} €)", {"trade_id": t.id}))
                    self.on_trade(t)

    def expire_stale(self, now: int):
        for t in self.trades:
            if t.status == TradeStatus.PENDING and now > t.entry_t + 60_000:
                self._cancel(t, "sem preço de entrada (dados atrasados ou desconexão)")

    def _cancel(self, t: Trade, reason: str):
        was_open = t.status == TradeStatus.OPEN
        self.broker.cancel(t, reason)
        if was_open:
            self.risk.on_close(t.stake, 0.0, now_ms())
        self.record(Decision(t.asset, "execution", False, f"operação cancelada: {reason}", {"trade_id": t.id}))
        self.on_trade(t)

    def emergency(self, now: int):
        self.active = False
        self.risk.emergency_stop()
        for t in self.trades:
            if t.status == TradeStatus.PENDING:
                self._cancel(t, "STOP DE EMERGÊNCIA")
            elif t.status == TradeStatus.OPEN:            # à vista: zera a posição no último preço conhecido
                px = self.last_price.get(t.asset, t.entry_price)
                self.broker.settle_trade(t, px)
                t.exit_reason = "emergência"
                self.risk.on_close(t.stake, t.pnl, now_ms())
                self.record(Decision(t.asset, "settlement", True, f"posição zerada no STOP DE EMERGÊNCIA @ {px}: {t.pnl:+.2f} €", {"trade_id": t.id}))
                self.on_trade(t)
