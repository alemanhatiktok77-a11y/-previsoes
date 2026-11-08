"""Persistência: SQLAlchemy Core (PostgreSQL em produção, SQLite em testes) + versão em memória."""
from __future__ import annotations

import json
import threading
from dataclasses import asdict

from app.core.models import Decision, NewsItem, Trade


class MemoryRepo:
    def __init__(self):
        self.decisions, self.trades, self.news, self.users = [], {}, {}, {}

    def add_decision(self, d: Decision): self.decisions.append(asdict(d))
    def upsert_trade(self, t: Trade): self.trades[t.id] = t.to_dict()
    def upsert_news(self, n: NewsItem): self.news[n.url or n.title] = asdict(n)
    def list_decisions(self, limit=200, asset=None):
        rows = [d for d in self.decisions if not asset or d["asset"] == asset]
        return rows[-limit:][::-1]
    def list_trades(self, limit=500):
        return sorted(self.trades.values(), key=lambda t: t["created_ms"], reverse=True)[:limit]
    def get_user(self, name): return self.users.get(name)
    def create_user(self, name, pw_hash): self.users[name] = {"username": name, "password_hash": pw_hash}


class SqlRepo:
    def __init__(self, url: str):
        from sqlalchemy import (JSON, BigInteger, Boolean, Column, Float, Integer, MetaData, String, Table, Text, create_engine)
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.eng = create_engine(url, pool_pre_ping=True, future=True)
        md = MetaData()
        self.users = Table("users", md, Column("username", String(64), primary_key=True), Column("password_hash", String(200), nullable=False))
        self.dec = Table("decisions", md, Column("id", String(32), primary_key=True), Column("ts", BigInteger, index=True),
                         Column("asset", String(64), index=True), Column("stage", String(20)), Column("accepted", Boolean),
                         Column("reason", Text), Column("payload", JSON))
        self.tr = Table("trades", md, Column("id", String(32), primary_key=True), Column("created_ms", BigInteger, index=True),
                        Column("asset", String(64), index=True), Column("status", String(12), index=True), Column("data", JSON))
        self.nw = Table("news", md, Column("key", String(500), primary_key=True), Column("published_ms", BigInteger, index=True), Column("data", JSON))
        md.create_all(self.eng)
        self.lock = threading.Lock()

    def _upsert(self, table, key_col, values):
        from sqlalchemy import select
        with self.lock, self.eng.begin() as cx:
            k = values[key_col]
            if cx.execute(select(table.c[key_col]).where(table.c[key_col] == k)).first():
                cx.execute(table.update().where(table.c[key_col] == k).values(**values))
            else:
                cx.execute(table.insert().values(**values))

    def add_decision(self, d: Decision):
        with self.lock, self.eng.begin() as cx:
            cx.execute(self.dec.insert().values(id=d.id, ts=d.ts, asset=d.asset, stage=d.stage, accepted=d.accepted,
                                                reason=d.reason, payload=json.loads(json.dumps(d.payload, default=str))))

    def upsert_trade(self, t: Trade):
        self._upsert(self.tr, "id", {"id": t.id, "created_ms": t.created_ms, "asset": t.asset, "status": t.status.value,
                                     "data": json.loads(json.dumps(t.to_dict(), default=str))})

    def upsert_news(self, n: NewsItem):
        self._upsert(self.nw, "key", {"key": (n.url or n.title)[:500], "published_ms": n.published_ms or 0, "data": asdict(n)})

    def list_decisions(self, limit=200, asset=None):
        from sqlalchemy import select
        q = select(self.dec).order_by(self.dec.c.ts.desc()).limit(limit)
        if asset:
            q = q.where(self.dec.c.asset == asset)
        with self.eng.connect() as cx:
            return [dict(r._mapping) for r in cx.execute(q)]

    def list_trades(self, limit=500):
        from sqlalchemy import select
        with self.eng.connect() as cx:
            return [r.data for r in cx.execute(select(self.tr).order_by(self.tr.c.created_ms.desc()).limit(limit))]

    def get_user(self, name):
        from sqlalchemy import select
        with self.eng.connect() as cx:
            r = cx.execute(select(self.users).where(self.users.c.username == name)).first()
            return dict(r._mapping) if r else None

    def create_user(self, name, pw_hash):
        self._upsert(self.users, "username", {"username": name, "password_hash": pw_hash})


def make_repo(url: str):
    return MemoryRepo() if url == "memory" else SqlRepo(url)
