"""Testes de integração com PostgreSQL e Redis reais (rodam no CI, onde os serviços existem)."""
import asyncio
import os

import pytest

from app.core.models import Decision, Direction, Trade, TradeStatus


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="sem PostgreSQL")
def test_postgres_repository_roundtrip():
    pytest.importorskip("sqlalchemy")
    from app.db.repository import SqlRepo
    r = SqlRepo(os.environ["TEST_DATABASE_URL"])
    t = Trade("ETHUSDT@binance", Direction.PUT, "Reversão à média", 10, 0.85, 5, 1_762_600_000_000)
    r.upsert_trade(t)
    t.status, t.pnl = TradeStatus.LOSS, -10
    r.upsert_trade(t)  # atualização (upsert)
    got = [x for x in r.list_trades(50) if x["id"] == t.id][0]
    assert got["status"] == "LOSS" and got["pnl"] == -10
    d = Decision("ETHUSDT@binance", "risk", False, "teste", {"k": 1})
    r.add_decision(d)
    assert any(x["id"] == d.id for x in r.list_decisions(50, "ETHUSDT@binance"))


@pytest.mark.skipif(not os.getenv("TEST_REDIS_URL"), reason="sem Redis")
def test_redis_bus_pubsub():
    pytest.importorskip("redis")
    from app.bus import RedisBus

    async def run():
        b = RedisBus(os.environ["TEST_REDIS_URL"])
        b.bind(asyncio.get_running_loop())
        q = b.subscribe()
        await b.start()
        await asyncio.sleep(0.3)
        b.publish("trade", {"id": "abc"})
        msg = await asyncio.wait_for(q.get(), timeout=5)
        await b.close()
        return msg
    assert '"abc"' in asyncio.run(run())


def test_memory_bus_thread_safe_publish():
    from app.bus import MemoryBus
    import threading

    async def run():
        b = MemoryBus()
        b.bind(asyncio.get_running_loop())
        q = b.subscribe()
        threading.Thread(target=lambda: [b.publish("price", {"i": i}) for i in range(50)]).start()
        got = [await asyncio.wait_for(q.get(), timeout=3) for _ in range(50)]
        return len(got)
    assert asyncio.run(run()) == 50
