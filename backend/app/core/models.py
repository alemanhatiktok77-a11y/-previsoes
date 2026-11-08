"""Modelos de domínio compartilhados por todos os módulos (sem dependências externas)."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


def now_ms() -> int:
    return int(time.time() * 1000)


class MarketType(str, Enum):
    NORMAL = "NORMAL"
    OTC = "OTC"


class Direction(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class BotState(str, Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    EMERGENCY = "EMERGENCY"


class TradeStatus(str, Enum):
    PENDING = "PENDING"      # decisão tomada, aguardando o horário de entrada
    OPEN = "OPEN"            # entrada simulada registrada
    WIN = "WIN"
    LOSS = "LOSS"
    DRAW = "DRAW"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Asset:
    symbol: str            # identificador interno, ex.: "BTCUSDT@binance"
    display: str           # nome para a tela, ex.: "BTC/USD"
    market: MarketType     # NORMAL ou OTC — nunca misturados
    source_id: str         # provedor de dados responsável por ESTE ativo
    price_decimals: int = 5
    currencies: tuple = ()


@dataclass
class Candle:
    t: int      # abertura (ms, UTC)
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


@dataclass
class Vote:
    component: str
    direction: int        # +1 CALL, −1 PUT
    weight: float
    reason: str


@dataclass
class Opportunity:
    asset: str
    strategy: str
    regime: str
    direction: Direction
    strength: float
    votes: list
    candle_t: int
    price: float
    created_ms: int = field(default_factory=now_ms)


@dataclass
class Decision:
    """Registro auditável de cada passo do pipeline (aceita ou rejeitada)."""
    asset: str
    stage: str               # opportunity | data | risk | strategy | execution | settlement
    accepted: bool
    reason: str
    payload: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: int = field(default_factory=now_ms)


@dataclass
class Trade:
    asset: str
    direction: Direction
    strategy: str
    stake: float
    payout: float            # ex.: 0.85
    expiry_min: int
    entry_t: int             # início do minuto de entrada (ms)
    confidence: Optional[float] = None       # acerto histórico calibrado (0–1) ou None
    confidence_n: int = 0
    model_strength: float = 0.0
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    status: TradeStatus = TradeStatus.PENDING
    pnl: float = 0.0
    broker: str = "paper"
    reasons: list = field(default_factory=list)
    cancel_reason: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_ms: int = field(default_factory=now_ms)
    closed_ms: Optional[int] = None

    @property
    def exit_t(self) -> int:
        return self.entry_t + self.expiry_min * 60_000

    def to_dict(self) -> dict:
        d = asdict(self)
        d["direction"] = self.direction.value
        d["status"] = self.status.value
        return d


@dataclass
class NewsItem:
    source: str
    title: str
    url: str
    published_ms: Optional[int]
    summary: str
    currencies: list
    topics: list
    relevance: float          # 0–1
    impact: str               # Alto | Médio | Baixo
    reliability: float        # 0–1, pela origem (banco central = 1,0)
    fetched_ms: int = field(default_factory=now_ms)
