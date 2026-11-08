"""AI ENGINE — detecção de regime, estratégias independentes e calibração estatística.

O motor é determinístico e auditável: cada oportunidade carrega a lista de votos que a
gerou. A "probabilidade" exibida vem SOMENTE do desempenho passado de oportunidades do
mesmo tipo (calibração), nunca do score bruto.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.core.models import Candle, Direction, Opportunity, Vote
from app.engine import indicators as ind


@dataclass
class Features:
    C: list
    close: list
    e9: list
    e21: list
    e50: list
    rsi: list
    macd_hist: list
    bb_mid: list
    bb_up: list
    bb_lo: list
    atr: list
    adx: list
    vol_ma: list
    has_volume: bool
    c5: list            # velas de 5 min
    e5_fast: list
    e5_slow: list
    idx5: list          # índice da vela de 5 min que contém cada vela de 1 min


def build_features(C: Sequence[Candle]) -> Features:
    C = list(C)
    close = [x.c for x in C]
    _, _, hist = ind.macd(close)
    mid, up, lo = ind.bollinger(close)
    c5 = ind.aggregate(C, 5)
    pos5 = {x.t: i for i, x in enumerate(c5)}
    vols = [x.v for x in C]
    c5close = [x.c for x in c5]
    return Features(
        C=C, close=close, e9=ind.ema(close, 9), e21=ind.ema(close, 21), e50=ind.ema(close, 50),
        rsi=ind.rsi(close), macd_hist=hist, bb_mid=mid, bb_up=up, bb_lo=lo,
        atr=ind.atr(C), adx=ind.adx(C), vol_ma=ind.sma(vols, 20), has_volume=any(v > 0 for v in vols),
        c5=c5, e5_fast=ind.ema(c5close, 9), e5_slow=ind.ema(c5close, 21),
        idx5=[pos5[x.t // 300_000 * 300_000] for x in C],
    )


# ---------------------------------------------------------------- regime
def regime(F: Features, i: int) -> str:
    """TENDÊNCIA, LATERAL ou VOLÁTIL (volatilidade extrema bloqueia operações)."""
    a, atr_now = F.adx[i], F.atr[i]
    window = [x for x in F.atr[max(0, i - 240):i] if x]
    if atr_now and len(window) >= 60:
        rank = sum(1 for x in window if x < atr_now) / len(window)
        if rank > 0.97:
            return "VOLÁTIL"
    if a is not None and a >= 23:
        return "TENDÊNCIA"
    return "LATERAL"


def tf5_direction(F: Features, i: int) -> int:
    j = F.idx5[i] - 1  # só a vela de 5 min já FECHADA
    if j < 21 or F.e5_fast[j] is None or F.e5_slow[j] is None:
        return 0
    return 1 if F.e5_fast[j] > F.e5_slow[j] else -1


# ---------------------------------------------------------------- estratégias
class Strategy:
    name = "base"
    regimes: tuple = ()
    min_votes = 3
    min_strength = 3.5

    def evaluate(self, F: Features, i: int) -> list:
        raise NotImplementedError

    def run(self, F: Features, i: int, asset: str) -> Optional[Opportunity]:
        votes = self.evaluate(F, i)
        if not votes:
            return None
        score = sum(v.direction * v.weight for v in votes)
        d = 1 if score > 0 else -1 if score < 0 else 0
        if d == 0:
            return None
        pro = {v.component for v in votes if v.direction == d}
        against = [v for v in votes if v.direction != d]
        if len(pro) < self.min_votes or abs(score) < self.min_strength or len(against) > 1:
            return None
        return Opportunity(asset=asset, strategy=self.name, regime=regime(F, i),
                           direction=Direction.CALL if d > 0 else Direction.PUT, strength=round(abs(score), 2),
                           votes=votes, candle_t=F.C[i].t, price=F.C[i].c)


class TrendFollowing(Strategy):
    """Segue a tendência em pullbacks: EMAs alinhadas + timeframe de 5 min + momentum."""
    name = "Seguidor de tendência"
    regimes = ("TENDÊNCIA",)

    def evaluate(self, F, i):
        x, v = F.C[i], []
        up = F.e9[i] > F.e21[i] > F.e50[i] and x.c > F.e50[i]
        dn = F.e9[i] < F.e21[i] < F.e50[i] and x.c < F.e50[i]
        if not (up or dn):
            return []
        d = 1 if up else -1
        v.append(Vote("EMAs 9/21/50", d, 2.0, f"EMAs alinhadas {'para cima' if up else 'para baixo'} · ADX {F.adx[i]:.0f}"))
        t5 = tf5_direction(F, i)
        if t5:
            v.append(Vote("Timeframe 5m", t5, 1.0, f"EMA 9 {'acima' if t5 > 0 else 'abaixo'} da EMA 21 no 5 min"))
        h, hp = F.macd_hist[i], F.macd_hist[i - 1]
        if h is not None and hp is not None and (h > 0) == (d > 0) and abs(h) >= abs(hp):
            v.append(Vote("MACD", d, 1.0, "Histograma do MACD a favor e crescendo"))
        r = F.rsi[i]
        if r is not None and ((d > 0 and 50 < r < 70) or (d < 0 and 30 < r < 50)):
            v.append(Vote("RSI", d, 0.75, f"RSI {r:.0f} confirma força sem exaustão"))
        a = F.atr[i] or 1e-12
        if abs(F.C[i - 1].l - F.e21[i - 1]) < 0.5 * a if d > 0 else abs(F.C[i - 1].h - F.e21[i - 1]) < 0.5 * a:
            if (x.c > x.o) == (d > 0):
                v.append(Vote("Pullback", d, 1.25, "Correção até a EMA 21 seguida de vela a favor"))
        return v


class MeanReversion(Strategy):
    """Reversão em mercado lateral: extremos de Bollinger/RSI + reação em suporte/resistência."""
    name = "Reversão à média"
    regimes = ("LATERAL",)

    def evaluate(self, F, i):
        x, v = F.C[i], []
        a = F.atr[i] or 1e-12
        if F.bb_lo[i] is not None:
            if x.l < F.bb_lo[i] and x.c > F.bb_lo[i]:
                v.append(Vote("Bollinger", 1, 1.5, "Rejeição abaixo da banda inferior"))
            elif x.h > F.bb_up[i] and x.c < F.bb_up[i]:
                v.append(Vote("Bollinger", -1, 1.5, "Rejeição acima da banda superior"))
        r = F.rsi[i]
        if r is not None and r <= 30:
            v.append(Vote("RSI", 1, 1.25, f"RSI {r:.0f} sobrevendido"))
        elif r is not None and r >= 70:
            v.append(Vote("RSI", -1, 1.25, f"RSI {r:.0f} sobrecomprado"))
        for p, n in ind.pivot_levels(F.C, i - 1, tol=0.5 * a):
            if abs(x.l - p) < 0.3 * a and x.c > x.o:
                v.append(Vote("Suporte", 1, 1.25, f"Reação compradora no suporte {p:.6g} ({n} toques)"))
                break
            if abs(x.h - p) < 0.3 * a and x.c < x.o:
                v.append(Vote("Resistência", -1, 1.25, f"Reação vendedora na resistência {p:.6g} ({n} toques)"))
                break
        cp = ind.candle_pattern(F.C, i)
        if cp and cp[0]:
            v.append(Vote("Vela", cp[0], 1.0, cp[1]))
        for f, p, up_leg in ind.fibonacci(F.C, i - 1):
            if x.l <= p <= x.h:
                d = 1 if x.c > x.o else -1 if x.c < x.o else 0
                if d and (d > 0) == up_leg:
                    v.append(Vote("Fibonacci", d, 0.5, f"Reação na retração de {f * 100:.1f}%"))
                break
        return v


class Breakout(Strategy):
    """Rompimento de zona com expansão de volatilidade (e volume, quando houver); também falsos rompimentos."""
    name = "Rompimento"
    regimes = ("TENDÊNCIA", "LATERAL")

    def evaluate(self, F, i):
        x, prev, v = F.C[i], F.C[i - 1], []
        a = F.atr[i] or 1e-12
        for p, n in ind.pivot_levels(F.C, i - 1, tol=0.5 * a):
            if prev.c <= p and x.c > p + 0.25 * a and x.c > x.o:
                v.append(Vote("Rompimento", 1, 2.0, f"Fechou acima da resistência {p:.6g} ({n} toques)"))
                break
            if prev.c >= p and x.c < p - 0.25 * a and x.c < x.o:
                v.append(Vote("Rompimento", -1, 2.0, f"Fechou abaixo do suporte {p:.6g} ({n} toques)"))
                break
            if x.h > p + 0.1 * a and x.c < p and prev.c < p:
                v.append(Vote("Falso rompimento", -1, 2.0, f"Pavio acima de {p:.6g} e fechamento abaixo"))
                break
            if x.l < p - 0.1 * a and x.c > p and prev.c > p:
                v.append(Vote("Falso rompimento", 1, 2.0, f"Pavio abaixo de {p:.6g} e fechamento acima"))
                break
        if not v:
            return []
        d = v[0].direction
        if (x.h - x.l) > 1.3 * a:
            v.append(Vote("Expansão", d, 1.0, f"Vela {((x.h - x.l) / a):.1f}× o ATR"))
        if F.has_volume and F.vol_ma[i] and x.v > 1.5 * F.vol_ma[i]:
            v.append(Vote("Volume", d, 1.0, f"Volume {x.v / F.vol_ma[i]:.1f}× a média"))
        t5 = tf5_direction(F, i)
        if t5:
            v.append(Vote("Timeframe 5m", t5, 0.75, "Direção do 5 min"))
        return v


STRATEGIES = [TrendFollowing(), MeanReversion(), Breakout()]
WARMUP = 80


def analyze(F: Features, i: int, asset: str, enabled: Optional[set] = None) -> tuple:
    """Retorna (oportunidade ou None, regime). Só usa dados até o índice i."""
    if i < WARMUP or F.adx[i] is None or F.e50[i] is None or F.atr[i] is None:
        return None, "AQUECENDO"
    reg = regime(F, i)
    if reg == "VOLÁTIL":
        return None, reg
    best = None
    for s in STRATEGIES:
        if enabled is not None and s.name not in enabled:
            continue
        if reg not in s.regimes:
            continue
        op = s.run(F, i, asset)
        if op and (best is None or op.strength > best.strength):
            best = op
    return best, reg


def strength_bucket(s: float) -> str:
    return "A" if s >= 6 else "B" if s >= 4.5 else "C"


# ---------------------------------------------------------------- calibração
def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d, (c + m) / d


@dataclass
class Calibrator:
    """Mapeia (estratégia, faixa de força, expiração) → taxa de acerto observada no PASSADO.
    Usa encolhimento bayesiano para 50% quando há poucos dados."""
    prior_k: int = 20
    min_n: int = 30
    table: dict = field(default_factory=dict)

    def add(self, strategy: str, bucket: str, expiry: int, win: bool):
        k = (strategy, bucket, expiry)
        w, n = self.table.get(k, (0, 0))
        self.table[k] = (w + int(win), n + 1)

    def estimate(self, strategy: str, bucket: str, expiry: int) -> dict:
        w, n = self.table.get((strategy, bucket, expiry), (0, 0))
        if n < self.min_n:  # tenta o nível acima: mesma estratégia, todas as forças
            w = sum(v[0] for k, v in self.table.items() if k[0] == strategy and k[2] == expiry)
            n = sum(v[1] for k, v in self.table.items() if k[0] == strategy and k[2] == expiry)
            scope = "estratégia"
        else:
            scope = "estratégia+força"
        if n < self.min_n:
            return {"calibrated": False, "p": None, "n": n, "ci": None, "scope": "insuficiente"}
        p = (w + 0.5 * self.prior_k) / (n + self.prior_k)
        return {"calibrated": True, "p": p, "raw": w / n, "n": n, "ci": wilson(w, n), "scope": scope}


# ---------------------------------------------------------------- backtest / walk-forward
def simulate_outcomes(C: Sequence[Candle], asset: str = "bt", expiries=(1, 2, 5)) -> list:
    """Percorre o histórico vela a vela. Decisão no fechamento da vela i; entrada na ABERTURA
    da vela i+2 (minuto seguinte ao aviso); saída no FECHAMENTO da vela i+1+exp."""
    F = build_features(C)
    out, last = [], -10
    for i in range(WARMUP, len(C) - 7):
        op, reg = analyze(F, i, asset)
        if not op or i - last < 3:
            continue
        if C[i + 2].t - C[i].t != 120_000:
            continue
        last = i
        entry = C[i + 2].o
        res = {}
        for e in expiries:
            ex = C[i + 1 + e].c
            res[e] = 0 if ex == entry else (1 if (ex > entry) == (op.direction == Direction.CALL) else -1)
        out.append({"t": C[i + 2].t, "strategy": op.strategy, "bucket": strength_bucket(op.strength),
                    "regime": reg, "direction": op.direction.value, "res": res})
    return out


def walk_forward(results: list, expiry: int, folds: int = 5, min_conf: float = 0.55) -> dict:
    """Calibra com blocos anteriores e testa no bloco seguinte (sem olhar o futuro)."""
    if len(results) < folds * 5:
        return {"tested": 0, "wins": 0, "rate": None, "ci": None, "folds": []}
    size = len(results) // folds
    tested = wins = 0
    fold_stats = []
    for k in range(1, folds):
        cal = Calibrator()
        for r in results[:k * size]:
            if r["res"][expiry] != 0:
                cal.add(r["strategy"], r["bucket"], expiry, r["res"][expiry] > 0)
        ft = fw = 0
        for r in results[k * size:(k + 1) * size]:
            est = cal.estimate(r["strategy"], r["bucket"], expiry)
            if est["calibrated"] and est["p"] >= min_conf and r["res"][expiry] != 0:
                ft += 1
                fw += r["res"][expiry] > 0
        fold_stats.append({"fold": k, "tested": ft, "wins": fw})
        tested += ft
        wins += fw
    return {"tested": tested, "wins": wins, "rate": wins / tested if tested else None,
            "ci": wilson(wins, tested) if tested else None, "folds": fold_stats}
