"""API do BOT TRADER AI — FastAPI (REST + WebSocket)."""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.api.security import LoginLimiter, hash_password, make_token, read_token, verify_password
from app.bot import Bot
from app.bus import MemoryBus, RedisBus
from app.config import Settings
from app.db.repository import make_repo
from app.engine import ai_engine as ai
from app.news.engine import impact_on

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    S = settings or Settings()
    if not S.admin_password or len(S.admin_password) < 10:
        raise RuntimeError("Defina ADMIN_PASSWORD com pelo menos 10 caracteres")
    repo = make_repo(S.database_url)
    bus = RedisBus(S.redis_url) if S.redis_url else MemoryBus()
    bot = Bot(S, repo, bus)
    limiter = LoginLimiter()
    if not repo.get_user(S.admin_user):
        repo.create_user(S.admin_user, hash_password(S.admin_password))

    @asynccontextmanager
    async def lifespan(app):
        bus.bind(asyncio.get_running_loop())
        await bus.start()
        if S.market_data:
            asyncio.create_task(bot.start_monitoring())
        yield
        await bot.shutdown()
        await bus.close()

    app = FastAPI(title="BOT TRADER AI", version="1.0.0", lifespan=lifespan)
    app.state.bot, app.state.repo, app.state.settings = bot, repo, S
    bearer = HTTPBearer(auto_error=False)

    def user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
        if not cred:
            raise HTTPException(401, "token ausente")
        try:
            return read_token(cred.credentials, S.jwt_secret)
        except Exception:
            raise HTTPException(401, "token inválido ou expirado")

    # ------------------------------------------------ autenticação
    class Login(BaseModel):
        username: str = Field(max_length=64)
        password: str = Field(max_length=200)

    @app.post("/auth/login")
    def login(body: Login, request: Request):
        key = f"{body.username}|{request.client.host if request.client else '-'}"
        if not limiter.allowed(key):
            raise HTTPException(429, "muitas tentativas — aguarde 10 minutos")
        u = repo.get_user(body.username)
        if not u or not verify_password(body.password, u["password_hash"]):
            limiter.fail(key)
            raise HTTPException(401, "usuário ou senha incorretos")
        return {"access_token": make_token(body.username, S.jwt_secret, S.jwt_minutes), "token_type": "bearer", "expires_min": S.jwt_minutes}

    @app.get("/health")
    def health():
        return {"ok": True, "server_time": bot.now()}

    @app.get("/time")
    def server_time():
        return {"server_time": bot.now(), "clock_offset_ms": bot.offset_ms}

    # ------------------------------------------------ robô
    @app.get("/dashboard")
    def dashboard(_: str = Depends(user)):
        trades = repo.list_trades(1000)
        closed = [t for t in trades if t["status"] in ("WIN", "LOSS")]
        wins = sum(t["status"] == "WIN" for t in closed)
        lat = [v for p in bot.providers.values() for v in p.latency_ms.values() if p.source_id == "binance"]
        return {**bot.status(), "capital": bot.paper.balance(), "initial_capital": bot.paper.initial,
                "pnl": round(sum(t["pnl"] for t in trades), 2), "trades_total": len(closed),
                "open_trades": [t for t in trades if t["status"] in ("PENDING", "OPEN")],
                "win_rate": wins / len(closed) if closed else None, "breakeven": 1 / (1 + bot.risk.cfg.payout),
                "assets_monitored": sum(1 for a in bot.assets.values() if a.symbol in bot.candles),
                "latency_ms": round(sum(lat) / len(lat)) if lat else None,
                "last_trades": trades[:8], "connections": bot.connections(), "risk": bot.risk.snapshot()["state"]}

    @app.post("/bot/start")
    def bot_start(_: str = Depends(user)):
        try:
            bot.start()
        except PermissionError as e:
            raise HTTPException(409, str(e))
        return bot.status()

    @app.post("/bot/pause")
    def bot_pause(_: str = Depends(user)):
        bot.pause()
        return bot.status()

    @app.post("/bot/emergency-stop")
    def bot_emergency(_: str = Depends(user)):
        bot.emergency()
        return bot.status()

    @app.post("/bot/reset-emergency")
    def bot_reset(_: str = Depends(user)):
        bot.reset_emergency()
        return bot.status()

    # ------------------------------------------------ mercado
    @app.get("/assets")
    def assets(_: str = Depends(user)):
        return bot.asset_view()

    @app.get("/otc")
    def otc(_: str = Depends(user)):
        return {**bot.otc.status(), "assets": [r for r in bot.asset_view() if r["market"] == "OTC"],
                "explanation": "Cotações OTC são geradas por cada corretora e não há API pública oficial. Sem fonte OTC confiável, operações OTC permanecem bloqueadas."}

    @app.get("/news")
    def news(currency: Optional[str] = None, limit: int = 100, _: str = Depends(user)):
        sel = [n for n in bot.news.items if not currency or currency in n.currencies][:limit]
        items = []
        for n in sel:
            it = asdict(n)
            it["asset_impact"] = {a.display: impact_on(a, n) for a in bot.assets.values() if impact_on(a, n)}
            items.append(it)
        return {"items": items, "feeds": bot.news.feed_status, "updated_ms": bot.news.updated_ms,
                "calendar_status": bot.news.calendar_status, "calendar": bot.news.calendar}

    # ------------------------------------------------ estratégias
    @app.get("/strategies")
    def strategies(_: str = Depends(user)):
        en = bot.engine.enabled_strategies
        return [{"name": s.name, "regimes": list(s.regimes), "doc": (s.__doc__ or "").strip(), "enabled": en is None or s.name in en,
                 "calibration": {sym: {f"{k[1]}|{k[2]}m": {"wins": v[0], "n": v[1]} for k, v in cal.table.items() if k[0] == s.name}
                                 for sym, cal in bot.engine.calibrators.items()}} for s in ai.STRATEGIES]

    class Toggle(BaseModel):
        enabled: bool

    @app.put("/strategies/{name}")
    def toggle_strategy(name: str, body: Toggle, _: str = Depends(user)):
        names = {s.name for s in ai.STRATEGIES}
        if name not in names:
            raise HTTPException(404, "estratégia inexistente")
        en = set(bot.engine.enabled_strategies or names)
        en.add(name) if body.enabled else en.discard(name)
        bot.engine.enabled_strategies = en
        return {"enabled": sorted(en)}

    # ------------------------------------------------ histórico e estatísticas
    @app.get("/trades")
    def trades(limit: int = 300, _: str = Depends(user)):
        return repo.list_trades(min(limit, 2000))

    @app.get("/decisions")
    def decisions(limit: int = 200, asset: Optional[str] = None, _: str = Depends(user)):
        return repo.list_decisions(min(limit, 2000), asset)

    @app.get("/stats")
    def stats(_: str = Depends(user)):
        closed = [t for t in repo.list_trades(5000) if t["status"] in ("WIN", "LOSS")][::-1]

        def group(f):
            g = defaultdict(lambda: [0, 0])
            for t in closed:
                k = f(t)
                g[k][1] += 1
                g[k][0] += t["status"] == "WIN"
            return [{"key": k, "wins": w, "n": n, "rate": w / n, "ci": ai.wilson(w, n)} for k, (w, n) in sorted(g.items(), key=lambda x: -x[1][1])]

        w = sum(t["status"] == "WIN" for t in closed)
        eq, run = [], bot.paper.initial
        for t in closed:
            run += t["pnl"]
            eq.append({"t": t["closed_ms"], "equity": round(run, 2)})
        recent, before = closed[-30:], closed[:-30]
        rr = lambda L: (sum(t["status"] == "WIN" for t in L) / len(L)) if L else None
        det = None
        if len(closed) >= 60:
            det = {"recent": rr(recent), "before": rr(before), "degraded": rr(recent) < rr(before) - 0.1 and rr(recent) < 1 / (1 + bot.risk.cfg.payout)}
        return {"n": len(closed), "wins": w, "rate": w / len(closed) if closed else None, "ci": ai.wilson(w, len(closed)) if closed else None,
                "breakeven": 1 / (1 + bot.risk.cfg.payout),
                "by_asset": group(lambda t: t["asset"]), "by_strategy": group(lambda t: t["strategy"]),
                "by_expiry": group(lambda t: f"{t['expiry_min']} min"),
                "by_hour": group(lambda t: time.strftime("%H", time.gmtime(t["entry_t"] / 1000)) + "h UTC"),
                "equity": eq, "deterioration": det,
                "backtest": {sym: {"signals": r["signals"], "walk_forward": {str(k): {kk: vv for kk, vv in v.items() if kk != "folds"} for k, v in r["walk_forward"].items()}}
                             for sym, r in bot.calibration_report.items()}}

    # ------------------------------------------------ risco
    @app.get("/risk")
    def risk(_: str = Depends(user)):
        return bot.risk.snapshot()

    class RiskBody(BaseModel):
        stake: float = Field(gt=0, le=10000)
        payout: float = Field(gt=0, le=1)
        daily_loss_limit: float = Field(gt=0)
        max_exposure: float = Field(gt=0)
        max_trades_day: int = Field(gt=0, le=500)
        max_open_trades: int = Field(gt=0, le=20)
        max_consecutive_losses: int = Field(gt=0, le=50)
        min_confidence: float = Field(ge=0.5, le=0.9)
        allow_uncalibrated: bool = False

    @app.put("/risk")
    def set_risk(body: RiskBody, _: str = Depends(user)):
        from app.risk.manager import RiskConfig
        try:
            bot.risk.cfg = RiskConfig(**body.model_dump())
        except ValueError as e:
            raise HTTPException(422, str(e))
        return bot.risk.snapshot()

    @app.post("/paper/reset")
    def paper_reset(_: str = Depends(user)):
        if any(t.status.value in ("PENDING", "OPEN") for t in bot.engine.trades):
            raise HTTPException(409, "há operações em andamento")
        bot.paper.reset()
        return {"capital": bot.paper.balance()}

    @app.get("/settings")
    def get_settings(_: str = Depends(user)):
        return {"twelvedata_configured": bool(S.twelvedata_key), "redis": bool(S.redis_url), "database": S.database_url.split(":")[0],
                "max_latency_ms": S.max_latency_ms, "news_block_min": S.news_block_min, "brokers": bot.brokers.list(),
                "real_execution": False, "real_execution_note": "Execução real desativada: nenhum adaptador oficial aprovado."}

    # ------------------------------------------------ tempo real
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        token = sock.query_params.get("token", "")
        try:
            read_token(token, S.jwt_secret)
        except Exception:
            await sock.close(code=4401)
            return
        await sock.accept()
        q = bus.subscribe()
        try:
            await sock.send_json({"type": "state", "data": bot.status()})
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    await sock.send_text(msg)
                except asyncio.TimeoutError:
                    await sock.send_json({"type": "ping", "data": {"server_time": bot.now()}})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            bus.unsubscribe(q)

    return app

# Execução: uvicorn app.api.main:create_app --factory --host 0.0.0.0 --port 8000
