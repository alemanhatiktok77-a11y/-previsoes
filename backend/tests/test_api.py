"""Testes de integração da API (FastAPI TestClient + banco SQLite ou PostgreSQL + Redis quando disponíveis)."""
import os
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.core.models import Direction, Trade, TradeStatus  # noqa: E402

PW = "senha-muito-forte-123"


@pytest.fixture()
def client(tmp_path):
    db = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/t.db"
    s = Settings(database_url=db, redis_url=os.getenv("TEST_REDIS_URL", ""), jwt_secret="x" * 40, admin_user="admin",
                 admin_password=PW, market_data=False)
    app = create_app(s)
    with TestClient(app) as c:
        c.app_ref = app
        yield c


def auth(c):
    r = c.post("/auth/login", json={"username": "admin", "password": PW})
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_requires_strong_admin_password(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url=f"sqlite:///{tmp_path}/a.db", admin_password="123", market_data=False))


def test_login_and_protection(client):
    assert client.get("/health").json()["ok"]
    assert client.get("/dashboard").status_code == 401
    assert client.post("/auth/login", json={"username": "admin", "password": "errada"}).status_code == 401
    h = auth(client)
    d = client.get("/dashboard", headers=h).json()
    assert d["state"] == "STOPPED" and d["capital"] == 1000
    assert client.get("/dashboard", headers={"Authorization": "Bearer lixo"}).status_code == 401


def test_login_rate_limit(client):
    for _ in range(5):
        client.post("/auth/login", json={"username": "admin", "password": "x"})
    assert client.post("/auth/login", json={"username": "admin", "password": PW}).status_code == 429


def test_bot_controls_and_emergency(client):
    h = auth(client)
    assert client.post("/bot/start", headers=h).json()["state"] == "RUNNING"
    assert client.post("/bot/pause", headers=h).json()["state"] == "PAUSED"
    assert client.post("/bot/emergency-stop", headers=h).json()["state"] == "EMERGENCY"
    assert client.post("/bot/start", headers=h).status_code == 409   # bloqueado até reset
    assert client.post("/bot/reset-emergency", headers=h).json()["state"] == "STOPPED"
    assert client.post("/bot/start", headers=h).json()["state"] == "RUNNING"
    decs = client.get("/decisions", headers=h).json()
    assert any("EMERGÊNCIA" in d["reason"] for d in decs)  # registrado no banco


def test_risk_validation_and_update(client):
    h = auth(client)
    body = {"stake": 5, "payout": 0.8, "daily_loss_limit": 20, "max_exposure": 15, "max_trades_day": 10,
            "max_open_trades": 2, "max_consecutive_losses": 3, "min_confidence": 0.58, "allow_uncalibrated": False}
    r = client.put("/risk", headers=h, json=body)
    assert r.status_code == 200 and r.json()["config"]["stake"] == 5
    assert client.put("/risk", headers=h, json={**body, "stake": 50}).status_code == 422       # stake > exposição
    assert client.put("/risk", headers=h, json={**body, "min_confidence": 0.3}).status_code == 422


def test_otc_blocked_and_settings(client):
    h = auth(client)
    o = client.get("/otc", headers=h).json()
    assert o["available"] is False and all(a["blocked"] for a in o["assets"])
    s = client.get("/settings", headers=h).json()
    assert s["real_execution"] is False and s["brokers"] == [{"name": "paper", "real_money": False}]


def test_strategies_toggle(client):
    h = auth(client)
    names = [s["name"] for s in client.get("/strategies", headers=h).json()]
    assert len(names) == 3
    r = client.put(f"/strategies/{names[0]}", headers=h, json={"enabled": False}).json()
    assert names[0] not in r["enabled"]
    assert client.put("/strategies/inexistente", headers=h, json={"enabled": True}).status_code == 404


def test_trade_persistence_and_stats(client):
    h = auth(client)
    bot = client.app_ref.state.bot
    for k, st in enumerate([TradeStatus.WIN, TradeStatus.LOSS, TradeStatus.WIN]):
        t = Trade("BTCUSDT@binance", Direction.CALL, "Rompimento", 10, 0.85, 2, 1_762_600_000_000 + k * 60_000)
        t.status, t.pnl, t.closed_ms = st, (8.5 if st == TradeStatus.WIN else -10), t.entry_t + 120_000
        bot._on_trade(t)
    s = client.get("/stats", headers=h).json()
    assert s["n"] == 3 and s["wins"] == 2 and s["by_strategy"][0]["key"] == "Rompimento"
    assert s["equity"][-1]["equity"] == pytest.approx(1007.0)
    assert len(client.get("/trades", headers=h).json()) == 3


def test_websocket_auth_and_events(client):
    h = auth(client)
    tok = h["Authorization"].split()[1]
    with pytest.raises(Exception):
        with client.websocket_connect("/ws?token=errado") as ws:
            ws.receive_json()
    with client.websocket_connect(f"/ws?token={tok}") as ws:
        assert ws.receive_json()["type"] == "state"
        client.post("/bot/start", headers=h)
        got = set()
        t0 = time.time()
        while time.time() - t0 < 5 and not {"decision", "state"} <= got:
            got.add(ws.receive_json()["type"])
        assert {"decision", "state"} <= got
