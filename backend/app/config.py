"""Configuração por variáveis de ambiente (nunca no código)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _f(name, default):
    return float(os.getenv(name, default))


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./bot.db"))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET") or secrets.token_urlsafe(48))
    jwt_minutes: int = field(default_factory=lambda: int(os.getenv("JWT_MINUTES", "720")))
    admin_user: str = field(default_factory=lambda: os.getenv("ADMIN_USER", "admin"))
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))
    twelvedata_key: str = field(default_factory=lambda: os.getenv("TWELVEDATA_API_KEY", ""))
    market_data: bool = field(default_factory=lambda: os.getenv("MARKET_DATA", "1") == "1")
    initial_capital: float = field(default_factory=lambda: _f("PAPER_CAPITAL", 1000))
    max_latency_ms: int = field(default_factory=lambda: int(os.getenv("MAX_LATENCY_MS", "2000")))
    news_block_min: int = field(default_factory=lambda: int(os.getenv("NEWS_BLOCK_MIN", "15")))
    stake: float = field(default_factory=lambda: _f("RISK_STAKE", 10))
    payout: float = field(default_factory=lambda: _f("RISK_PAYOUT", 0.85))
    daily_loss_limit: float = field(default_factory=lambda: _f("RISK_DAILY_LOSS", 50))
    max_exposure: float = field(default_factory=lambda: _f("RISK_MAX_EXPOSURE", 30))
    max_trades_day: int = field(default_factory=lambda: int(os.getenv("RISK_MAX_TRADES", "20")))
    min_confidence: float = field(default_factory=lambda: _f("RISK_MIN_CONFIDENCE", 0.56))

    def risk_defaults(self) -> dict:
        return {"stake": self.stake, "payout": self.payout, "daily_loss_limit": self.daily_loss_limit,
                "max_exposure": self.max_exposure, "max_trades_day": self.max_trades_day, "min_confidence": self.min_confidence}
