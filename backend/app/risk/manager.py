"""RISK MANAGER — todas as verificações de risco antes de qualquer entrada simulada.

Sem martingale e sem progressão: o valor por operação é FIXO (stake configurado) e nunca
aumenta após perdas.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict


@dataclass
class RiskConfig:
    stake: float = 10.0                 # valor fixo por operação (sem progressão)
    payout: float = 0.85
    daily_loss_limit: float = 50.0
    max_exposure: float = 30.0          # soma das apostas em aberto
    max_trades_day: int = 20
    max_open_trades: int = 3
    max_consecutive_losses: int = 4     # pausa para revisão (NÃO dobra a aposta)
    min_confidence: float = 0.56        # acerto histórico calibrado mínimo
    allow_uncalibrated: bool = False

    def __post_init__(self):
        if self.stake <= 0 or self.daily_loss_limit <= 0 or self.max_exposure < self.stake:
            raise ValueError("Configuração de risco inválida")


@dataclass
class RiskState:
    day: str = ""
    pnl_today: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    open_exposure: float = 0.0
    open_trades: int = 0
    emergency: bool = False
    events: list = field(default_factory=list)


class RiskManager:
    def __init__(self, cfg: RiskConfig | None = None):
        self.cfg = cfg or RiskConfig()
        self.st = RiskState()

    def _roll(self, now_ms: int):
        d = dt.datetime.fromtimestamp(now_ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
        if d != self.st.day:
            self.st.day, self.st.pnl_today, self.st.trades_today, self.st.consecutive_losses = d, 0.0, 0, 0

    def stake_for_next_trade(self) -> float:
        return self.cfg.stake  # fixo por desenho

    def check(self, now_ms: int, confidence: float | None) -> list:
        self._roll(now_ms)
        c, s, r = self.cfg, self.st, []
        if s.emergency:
            r.append("STOP DE EMERGÊNCIA acionado")
        if -s.pnl_today >= c.daily_loss_limit:
            r.append(f"limite diário de perda atingido ({s.pnl_today:.2f})")
        if s.trades_today >= c.max_trades_day:
            r.append("limite de operações do dia atingido")
        if s.open_trades >= c.max_open_trades:
            r.append("máximo de operações simultâneas")
        if s.open_exposure + c.stake > c.max_exposure:
            r.append(f"exposição máxima ({s.open_exposure:.2f} + {c.stake:.2f} > {c.max_exposure:.2f})")
        if s.consecutive_losses >= c.max_consecutive_losses:
            r.append(f"{s.consecutive_losses} perdas seguidas — robô pausado para revisão")
        if confidence is None and not c.allow_uncalibrated:
            r.append("estratégia sem histórico suficiente para calibrar")
        elif confidence is not None and confidence < c.min_confidence:
            r.append(f"confiança calibrada {confidence:.1%} abaixo do mínimo {c.min_confidence:.0%}")
        return r

    def on_open(self, stake: float, now_ms: int):
        self._roll(now_ms)
        self.st.trades_today += 1
        self.st.open_trades += 1
        self.st.open_exposure += stake

    def on_close(self, stake: float, pnl: float, now_ms: int, opened: bool = True):
        self._roll(now_ms)
        if opened:
            self.st.open_trades = max(0, self.st.open_trades - 1)
            self.st.open_exposure = max(0.0, self.st.open_exposure - stake)
        self.st.pnl_today += pnl
        if pnl < 0:
            self.st.consecutive_losses += 1
        elif pnl > 0:
            self.st.consecutive_losses = 0

    def emergency_stop(self):
        self.st.emergency = True

    def clear_emergency(self):
        self.st.emergency = False
        self.st.consecutive_losses = 0

    def snapshot(self) -> dict:
        return {"config": asdict(self.cfg), "state": {k: v for k, v in asdict(self.st).items() if k != "events"},
                "breakeven": 1 / (1 + self.cfg.payout)}
