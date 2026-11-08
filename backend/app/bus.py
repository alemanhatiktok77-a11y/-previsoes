"""Barramento de eventos em tempo real: Redis Pub/Sub (produção, permite várias instâncias da API)
ou fila em memória (desenvolvimento/testes)."""
from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("bus")
CHANNEL = "bot-events"


class MemoryBus:
    def __init__(self):
        self.subs: set = set()
        self.loop = None

    def bind(self, loop):
        self.loop = loop

    def publish(self, kind: str, data: dict):
        msg = json.dumps({"type": kind, "data": data}, default=str)
        for q in list(self.subs):
            if self.loop and self.loop.is_running():
                self.loop.call_soon_threadsafe(self._put, q, msg)

    @staticmethod
    def _put(q, msg):
        if q.qsize() < 1000:
            q.put_nowait(msg)

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subs.add(q)
        return q

    def unsubscribe(self, q):
        self.subs.discard(q)

    async def start(self):
        pass

    async def close(self):
        pass


class RedisBus(MemoryBus):
    """Publica no Redis e retransmite para os WebSockets conectados nesta instância."""

    def __init__(self, url: str):
        super().__init__()
        import redis
        import redis.asyncio as aredis
        self.sync = redis.Redis.from_url(url)
        self.aio = aredis.Redis.from_url(url)
        self.task = None

    def publish(self, kind, data):
        msg = json.dumps({"type": kind, "data": data}, default=str)
        try:
            self.sync.publish(CHANNEL, msg)
            if kind == "state":
                self.sync.set("bot:state", msg)
        except Exception as e:  # Redis fora do ar: entrega local para não perder o evento
            log.warning("redis indisponível: %s", e)
            super().publish(kind, data)

    async def start(self):
        async def relay():
            ps = self.aio.pubsub()
            await ps.subscribe(CHANNEL)
            async for m in ps.listen():
                if m.get("type") == "message":
                    msg = m["data"].decode() if isinstance(m["data"], bytes) else m["data"]
                    for q in list(self.subs):
                        self._put(q, msg)
        self.task = asyncio.create_task(relay())

    async def close(self):
        if self.task:
            self.task.cancel()
        await self.aio.aclose()
