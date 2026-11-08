"""Orquestrador do robô: conecta dados → AI ENGINE → EXECUTION ENGINE → banco/eventos.

Estados:
  STOPPED   monitora o mercado, não opera
  RUNNING   opera em PAPER TRADING
  PAUSED    não abre novas operações; as abertas são liquidadas normalmente
  EMERGENCY tudo bloqueado; pendentes canceladas (exige reset manual)
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import asdict

from app.brokers.base import BrokerRegistry
from app.brokers.paper import PaperBroker
from app.config import Settings
from app.core.models import Asset, BotState, Candle, Decision, MarketType, Trade
from app.data.guard import DataGuard, GuardConfig
from app.data.providers import BinanceProvider, OTCRegistry, TwelveDataProvider, default_assets
from app.engine import ai_engine as ai
from app.execution.engine import ExecutionEngine
from app.news.engine import NewsEngine
from app.risk.manager import RiskConfig, RiskManager

log = logging.getLogger("bot")


class Bot:
    def __init__(self, settings: Settings, repo, bus):
        self.s, self.repo, self.bus = settings, repo, bus
        self.offset_ms = 0
        self.state = BotState.STOPPED
        self.started_ms = None
        self.providers = {"binance": BinanceProvider(self.now)}
        if settings.twelvedata_key:
            self.providers["twelvedata"] = TwelveDataProvider(settings.twelvedata_key, self.now)
        self.otc = OTCRegistry()
        self.assets = {a.symbol: a for a in default_assets(bool(settings.twelvedata_key))}
        self.candles: dict = {}
        self.live: dict = {}
        self.calibration_report: dict = {}
        self.news = NewsEngine()
        self.brokers = BrokerRegistry()
        self.paper = PaperBroker(settings.initial_capital)
        self.brokers.register(self.paper)
        self.risk = RiskManager(RiskConfig(**settings.risk_defaults()))
        self.guard = DataGuard(GuardConfig(max_latency_ms=settings.max_latency_ms))
        self.recent_decisions = deque(maxlen=300)
        self.engine = ExecutionEngine(self.paper, self.risk, self.guard, record=self._record, on_trade=self._on_trade,
                                      news_block=lambda a, t: self.news.risk_events(a, t, settings.news_block_min), otc_registry=self.otc)
        self.engine.active = False
        self._stop = asyncio.Event()
        self._tasks: list = []

    # ------------------------------------------------ tempo
    def now(self) -> int:
        return int(time.time() * 1000) + self.offset_ms

    async def sync_clock(self):
        import httpx
        for url in ("https://api.binance.com/api/v3/time", "https://data-api.binance.vision/api/v3/time"):
            try:
                async with httpx.AsyncClient(timeout=8) as cli:
                    t0 = time.time() * 1000
                    j = (await cli.get(url)).json()
                    t1 = time.time() * 1000
                self.offset_ms = int(j["serverTime"] - (t0 + t1) / 2)
                return
            except Exception as e:
                log.warning("sincronização de relógio falhou em %s: %s", url, e)

    # ------------------------------------------------ eventos
    def _record(self, d: Decision):
        self.recent_decisions.append(d)
        self.repo.add_decision(d)
        self.bus.publish("decision", asdict(d))

    def _on_trade(self, t: Trade):
        self.repo.upsert_trade(t)
        self.bus.publish("trade", t.to_dict())

    # ------------------------------------------------ dados
    async def start_monitoring(self):
        await self.sync_clock()
        for sym, a in self.assets.items():
            p = self.providers.get(a.source_id)
            if a.market == MarketType.OTC or p is None:
                continue
            try:
                self.candles[sym] = await p.history(a, 1000)
                self.calibration_report[sym] = await asyncio.to_thread(self.engine.seed_calibration, a, self.candles[sym])
            except Exception as e:
                log.error("histórico %s: %s", a.display, e)
                p.last_error = str(e)
        for sid, p in self.providers.items():
            assets = [a for a in self.assets.values() if a.source_id == sid and a.symbol in self.candles]
            if assets:
                self._tasks.append(asyncio.create_task(p.stream(assets, self._on_candle, self._stop)))
        self._tasks.append(asyncio.create_task(self._maintenance()))
        self._tasks.append(asyncio.create_task(self._news_loop()))

    async def _on_candle(self, sym: str, c: Candle, closed: bool, event_ms: int):
        a = self.assets[sym]
        C = self.candles.setdefault(sym, [])
        self.live[sym] = {"price": c.c, "t": event_ms}
        if not closed:
            self.engine.on_candle_update(a, c, self.now())
            self.bus.publish("price", {"symbol": sym, "price": c.c, "t": event_ms, "latency_ms": self.providers[a.source_id].latency_ms.get(sym)})
            return
        if C and C[-1].t >= c.t:
            return
        C.append(c)
        if len(C) > 1500:
            del C[:len(C) - 1500]
        await asyncio.to_thread(self.engine.on_candle_closed, a, list(C), self.providers[a.source_id], self.now())

    async def _maintenance(self):
        while not self._stop.is_set():
            self.engine.expire_stale(self.now())
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    async def _news_loop(self):
        while not self._stop.is_set():
            try:
                await self.news.refresh()
                for n in self.news.items[:50]:
                    self.repo.upsert_news(n)
            except Exception as e:
                log.warning("notícias: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=600)
            except asyncio.TimeoutError:
                pass

    async def shutdown(self):
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------ comandos
    def start(self):
        if self.state == BotState.EMERGENCY:
            raise PermissionError("Robô em STOP DE EMERGÊNCIA — use 'reset' antes de iniciar")
        self.engine.active, self.state = True, BotState.RUNNING
        self.started_ms = self.started_ms or self.now()
        self._record(Decision("*", "control", True, "robô iniciado (paper trading)"))
        self.bus.publish("state", self.status())

    def pause(self):
        self.engine.active, self.state = False, BotState.PAUSED
        self._record(Decision("*", "control", True, "robô pausado"))
        self.bus.publish("state", self.status())

    def emergency(self):
        self.engine.emergency(self.now())
        self.state = BotState.EMERGENCY
        self._record(Decision("*", "control", True, "STOP DE EMERGÊNCIA acionado"))
        self.bus.publish("state", self.status())

    def reset_emergency(self):
        self.risk.clear_emergency()
        self.state = BotState.STOPPED
        self._record(Decision("*", "control", True, "emergência liberada pelo usuário"))
        self.bus.publish("state", self.status())

    # ------------------------------------------------ consultas
    def status(self) -> dict:
        return {"state": self.state.value, "server_time": self.now(), "clock_offset_ms": self.offset_ms}

    def connections(self) -> list:
        out = [p.status() for p in self.providers.values()]
        out.append({"source": "otc", "market": "OTC", "connected": False, "error": self.otc.status()["message"], "reconnects": 0, "latency_ms": {}})
        out.append({"source": "news", "market": "-", "connected": any(v == "ok" for v in self.news.feed_status.values()),
                    "error": "" if self.news.feed_status else "aguardando primeira coleta", "reconnects": 0, "latency_ms": {}})
        return out

    def asset_view(self) -> list:
        rows = []
        for sym, a in self.assets.items():
            C = self.candles.get(sym) or []
            p = self.providers.get(a.source_id)
            row = {"symbol": sym, "display": a.display, "market": a.market.value, "source": a.source_id, "decimals": a.price_decimals,
                   "price": self.live.get(sym, {}).get("price") or (C[-1].c if C else None),
                   "latency_ms": p.latency_ms.get(sym) if p else None,
                   "blocked": self.guard.check(a, p, len(C), self.now(), self.otc) if (p or a.market == MarketType.OTC) else ["sem provedor"]}
            if len(C) > ai.WARMUP + 5:
                F = ai.build_features(C[-400:])
                i = len(F.C) - 1
                row.update({"regime": ai.regime(F, i), "rsi": F.rsi[i], "adx": F.adx[i], "atr": F.atr[i],
                            "trend_5m": ai.tf5_direction(F, i), "change_1h": (C[-1].c / C[-61].c - 1) if len(C) > 61 else None})
            rows.append(row)
        return rows
