"""Provedores de dados de mercado. Cada ativo pertence a UM provedor (source_id).

Provedores reais incluídos (documentação pública oficial):
  * binance     — https://developers.binance.com/docs/binance-spot-api-docs  (REST klines + WebSocket kline_1m, sem chave)
  * twelvedata  — https://twelvedata.com/docs (REST time_series 1min, exige chave; plano gratuito com limite de créditos)
OTC: nenhum provedor público existe; ver OTCRegistry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional

from app.core.models import Asset, Candle, MarketType

log = logging.getLogger("data")
OnCandle = Callable[[str, Candle, bool, int], Awaitable[None]]  # (símbolo, vela, fechada?, timestamp do evento na fonte)


class MarketDataProvider(ABC):
    source_id: str = "base"
    market: MarketType = MarketType.NORMAL

    def __init__(self):
        self.connected = False
        self.last_error = ""
        self.last_event_ms: dict = {}
        self.latency_ms: dict = {}
        self.reconnects = 0

    @abstractmethod
    async def history(self, asset: Asset, limit: int = 1000) -> list: ...

    @abstractmethod
    async def stream(self, assets: list, on_candle: OnCandle, stop: asyncio.Event) -> None: ...

    def status(self) -> dict:
        return {"source": self.source_id, "market": self.market.value, "connected": self.connected,
                "error": self.last_error, "reconnects": self.reconnects, "latency_ms": dict(self.latency_ms)}


def _ext(asset: Asset) -> str:
    return asset.symbol.split("@")[0]


class BinanceProvider(MarketDataProvider):
    source_id = "binance"
    REST = ["https://data-api.binance.vision", "https://api.binance.com"]
    WS = ["wss://data-stream.binance.vision/stream?streams=", "wss://stream.binance.com:9443/stream?streams="]

    def __init__(self, clock=None):
        super().__init__()
        self.clock = clock or (lambda: int(time.time() * 1000))

    async def history(self, asset: Asset, limit: int = 1000) -> list:
        import httpx
        err = None
        async with httpx.AsyncClient(timeout=15) as cli:
            for host in self.REST:
                try:
                    r = await cli.get(f"{host}/api/v3/klines", params={"symbol": _ext(asset), "interval": "1m", "limit": limit})
                    r.raise_for_status()
                    rows = [Candle(k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in r.json()]
                    if rows and rows[-1].t + 60_000 > self.clock():
                        rows.pop()  # vela ainda aberta
                    return rows
                except Exception as e:  # tenta o próximo host
                    err = e
        raise RuntimeError(f"Binance histórico {asset.display}: {err}")

    async def stream(self, assets, on_candle, stop):
        import websockets
        backoff, host = 1, 0
        names = "/".join(_ext(a).lower() + "@kline_1m" for a in assets)
        by_ext = {_ext(a): a.symbol for a in assets}
        while not stop.is_set():
            url = self.WS[host % len(self.WS)] + names
            try:
                async with websockets.connect(url, ping_interval=15, ping_timeout=10, open_timeout=10) as ws:
                    self.connected, self.last_error, backoff = True, "", 1
                    log.info("binance conectado")
                    while not stop.is_set():
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        d = json.loads(raw).get("data", {})
                        k = d.get("k")
                        if not k:
                            continue
                        sym = by_ext.get(k["s"])
                        if not sym:
                            continue
                        ev = int(d["E"])
                        self.last_event_ms[sym] = self.clock()
                        self.latency_ms[sym] = max(0, self.clock() - ev)
                        c = Candle(int(k["t"]), float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]), float(k["v"]))
                        await on_candle(sym, c, bool(k["x"]), ev)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.connected, self.last_error = False, f"{type(e).__name__}: {e}"
                self.reconnects += 1
                host += 1
                log.warning("binance desconectado (%s) — nova tentativa em %ss", e, backoff)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                backoff = min(30, backoff * 2)
        self.connected = False


class TwelveDataProvider(MarketDataProvider):
    """Forex/metais via REST (não há WebSocket no plano gratuito). Sonda 1x por minuto."""
    source_id = "twelvedata"
    URL = "https://api.twelvedata.com/time_series"

    def __init__(self, api_key: str, clock=None):
        super().__init__()
        self.key = api_key
        self.clock = clock or (lambda: int(time.time() * 1000))

    async def _fetch(self, cli, asset, n):
        r = await cli.get(self.URL, params={"symbol": _ext(asset), "interval": "1min", "outputsize": n, "timezone": "UTC", "apikey": self.key})
        j = r.json()
        if j.get("status") == "error" or "values" not in j:
            raise RuntimeError(j.get("message", "sem dados"))
        from datetime import datetime, timezone
        rows = [Candle(int(datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000),
                       float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"]), float(v.get("volume") or 0)) for v in j["values"]]
        return rows[::-1]

    async def history(self, asset, limit=1000):
        import httpx
        async with httpx.AsyncClient(timeout=20) as cli:
            rows = await self._fetch(cli, asset, limit)
        if rows and rows[-1].t + 60_000 > self.clock():
            rows.pop()
        return rows

    async def stream(self, assets, on_candle, stop):
        import httpx
        if not self.key:
            self.last_error = "sem chave da API"
            return
        seen: dict = {}
        async with httpx.AsyncClient(timeout=20) as cli:
            while not stop.is_set():
                wait = 63 - (self.clock() // 1000) % 60   # 3 s após a virada do minuto
                try:
                    await asyncio.wait_for(stop.wait(), timeout=wait)
                    break
                except asyncio.TimeoutError:
                    pass
                for a in assets:
                    try:
                        rows = await self._fetch(cli, a, 3)
                        self.connected, self.last_error = True, ""
                        for c in rows:
                            closed = c.t + 60_000 <= self.clock()
                            if closed and seen.get(a.symbol, 0) >= c.t:
                                continue
                            self.last_event_ms[a.symbol] = self.clock()
                            if closed:
                                seen[a.symbol] = c.t
                                self.latency_ms[a.symbol] = self.clock() - (c.t + 60_000)
                            await on_candle(a.symbol, c, closed, c.t + 60_000 if closed else self.clock())
                    except Exception as e:
                        self.connected, self.last_error = False, str(e)
                    await asyncio.sleep(8)  # 8 req/min no plano gratuito


class OTCRegistry:
    """Fontes OTC — vazio por padrão.

    Cotações OTC de corretoras de opções binárias são geradas pela própria corretora e não há
    API pública documentada para elas. Para adicionar uma fonte, implemente MarketDataProvider com
    market=MarketType.OTC usando a API OFICIAL da corretora e registre aqui. Sem provedor, todo
    ativo OTC fica bloqueado.
    """

    def __init__(self):
        self.providers: dict = {}

    def register(self, p: MarketDataProvider):
        if p.market != MarketType.OTC:
            raise ValueError("Somente provedores OTC podem ser registrados no módulo OTC")
        self.providers[p.source_id] = p

    def provider_for(self, asset: Asset) -> Optional[MarketDataProvider]:
        if asset.market != MarketType.OTC:
            raise ValueError("Ativo não é OTC — use o provedor normal")
        return self.providers.get(asset.source_id)

    def status(self) -> dict:
        return {"available": bool(self.providers), "providers": list(self.providers),
                "message": "Nenhuma fonte OTC oficial configurada — operações OTC bloqueadas." if not self.providers else "ok"}


def default_assets(twelve_enabled: bool) -> list:
    A = [Asset("BTCUSDT@binance", "BTC/USD", MarketType.NORMAL, "binance", 2, ("USD", "CRYPTO")),
         Asset("ETHUSDT@binance", "ETH/USD", MarketType.NORMAL, "binance", 2, ("USD", "CRYPTO")),
         Asset("SOLUSDT@binance", "SOL/USD", MarketType.NORMAL, "binance", 3, ("USD", "CRYPTO"))]
    if twelve_enabled:
        A += [Asset("EUR/USD@twelvedata", "EUR/USD", MarketType.NORMAL, "twelvedata", 5, ("EUR", "USD")),
              Asset("GBP/USD@twelvedata", "GBP/USD", MarketType.NORMAL, "twelvedata", 5, ("GBP", "USD"))]
    # Ativos OTC listados para transparência — permanecem bloqueados sem provedor OTC
    A += [Asset("EURUSD-OTC@none", "EUR/USD (OTC)", MarketType.OTC, "none", 5, ("EUR", "USD"))]
    return A
