"""Indicadores técnicos em Python puro. Todos são causais: o valor no índice i usa apenas dados até i."""
from __future__ import annotations

import math
from typing import Optional, Sequence

from app.core.models import Candle

Series = list  # list[Optional[float]]


def sma(a: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(a)
    s = 0.0
    for i, x in enumerate(a):
        s += x
        if i >= n:
            s -= a[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(a: Sequence[Optional[float]], n: int) -> Series:
    out: Series = [None] * len(a)
    k = 2 / (n + 1)
    start = next((i for i, x in enumerate(a) if x is not None), None)
    if start is None or len(a) - start < n:
        return out
    e = sum(a[start:start + n]) / n
    out[start + n - 1] = e
    for i in range(start + n, len(a)):
        e = a[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi(c: Sequence[float], n: int = 14) -> Series:
    out: Series = [None] * len(c)
    if len(c) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0.0)
        l += max(-d, 0.0)
    g /= n
    l /= n
    out[n] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0.0)) / n
        l = (l * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def macd(c: Sequence[float], fast: int = 12, slow: int = 26, sig: int = 9):
    ef, es = ema(c, fast), ema(c, slow)
    line = [f - s if f is not None and s is not None else None for f, s in zip(ef, es)]
    signal = ema(line, sig)
    hist = [m - s if m is not None and s is not None else None for m, s in zip(line, signal)]
    return line, signal, hist


def bollinger(c: Sequence[float], n: int = 20, k: float = 2.0):
    mid = sma(c, n)
    up: Series = [None] * len(c)
    lo: Series = [None] * len(c)
    for i in range(n - 1, len(c)):
        m = mid[i]
        sd = math.sqrt(sum((x - m) ** 2 for x in c[i - n + 1:i + 1]) / n)
        up[i], lo[i] = m + k * sd, m - k * sd
    return mid, up, lo


def true_range(C: Sequence[Candle]) -> list:
    return [C[0].h - C[0].l] + [max(x.h - x.l, abs(x.h - C[i].c), abs(x.l - C[i].c)) for i, x in enumerate(C[1:])]


def wilder(a: Sequence[float], n: int) -> Series:
    out: Series = [None] * len(a)
    if len(a) < n:
        return out
    out[n - 1] = sum(a[:n]) / n
    for i in range(n, len(a)):
        out[i] = (out[i - 1] * (n - 1) + a[i]) / n
    return out


def atr(C: Sequence[Candle], n: int = 14) -> Series:
    return wilder(true_range(C), n)


def adx(C: Sequence[Candle], n: int = 14) -> Series:
    if len(C) < 2 * n + 1:
        return [None] * len(C)
    tr = true_range(C)
    pdm, ndm = [0.0], [0.0]
    for i in range(1, len(C)):
        up, dn = C[i].h - C[i - 1].h, C[i - 1].l - C[i].l
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)
    s_tr, s_p, s_n = wilder(tr, n), wilder(pdm, n), wilder(ndm, n)
    dx = [0.0] * len(C)
    for i in range(len(C)):
        if s_tr[i]:
            p, m = 100 * s_p[i] / s_tr[i], 100 * s_n[i] / s_tr[i]
            dx[i] = 0.0 if p + m == 0 else 100 * abs(p - m) / (p + m)
    out: Series = [None] * len(C)
    first = 2 * n - 1
    out[first] = sum(dx[n:first + 1]) / n
    for i in range(first + 1, len(C)):
        out[i] = (out[i - 1] * (n - 1) + dx[i]) / n
    return out


def aggregate(C: Sequence[Candle], minutes: int) -> list:
    """Agrupa velas de 1 min em velas de N min alinhadas ao relógio."""
    out: list = []
    span = minutes * 60_000
    for x in C:
        b = x.t // span * span
        if out and out[-1].t == b:
            cur = out[-1]
            cur.h, cur.l, cur.c, cur.v = max(cur.h, x.h), min(cur.l, x.l), x.c, cur.v + x.v
        else:
            out.append(Candle(b, x.o, x.h, x.l, x.c, x.v))
    return out


def pivot_levels(C: Sequence[Candle], end: int, tol: float, look: int = 120, w: int = 3) -> list:
    """Zonas de suporte/resistência com ≥2 toques, usando apenas velas até `end`."""
    piv = []
    for i in range(max(w, end - look), end - w + 1):
        if all(C[i].h > C[i - j].h and C[i].h >= C[i + j].h for j in range(1, w + 1)):
            piv.append(C[i].h)
        if all(C[i].l < C[i - j].l and C[i].l <= C[i + j].l for j in range(1, w + 1)):
            piv.append(C[i].l)
    piv.sort()
    zones: list = []
    for p in piv:
        if zones and p - zones[-1][0] <= tol:
            z = zones[-1]
            z[0] = (z[0] * z[1] + p) / (z[1] + 1)
            z[1] += 1
        else:
            zones.append([p, 1])
    return [(p, n) for p, n in zones if n >= 2]


def fibonacci(C: Sequence[Candle], end: int, look: int = 60) -> list:
    seg = C[max(0, end - look):end + 1]
    hi_i = max(range(len(seg)), key=lambda i: seg[i].h)
    lo_i = min(range(len(seg)), key=lambda i: seg[i].l)
    hi, lo = seg[hi_i].h, seg[lo_i].l
    up_leg = lo_i < hi_i
    r = hi - lo
    return [(f, hi - r * f if up_leg else lo + r * f, up_leg) for f in (0.382, 0.5, 0.618)]


def candle_pattern(C: Sequence[Candle], i: int):
    x, p = C[i], C[i - 1]
    body, rng = abs(x.c - x.o), (x.h - x.l) or 1e-12
    up_w, lo_w, pb = x.h - max(x.o, x.c), min(x.o, x.c) - x.l, abs(p.c - p.o)
    if x.c > x.o and p.c < p.o and x.c >= p.o and x.o <= p.c and body > pb:
        return 1, "Engolfo de alta"
    if x.c < x.o and p.c > p.o and x.o >= p.c and x.c <= p.o and body > pb:
        return -1, "Engolfo de baixa"
    if lo_w >= 2 * body and up_w <= body * 0.6 and body / rng < 0.4:
        return 1, "Martelo / pin bar de alta"
    if up_w >= 2 * body and lo_w <= body * 0.6 and body / rng < 0.4:
        return -1, "Estrela cadente / pin bar de baixa"
    if body / rng < 0.1:
        return 0, "Doji"
    return None
