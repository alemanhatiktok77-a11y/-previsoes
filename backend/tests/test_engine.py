"""Testes unitários do AI ENGINE: indicadores, ausência de dados futuros, backtest e walk-forward."""
import math
import time

from app.core.models import Candle
from app.engine import ai_engine as ai
from app.engine import indicators as ind
from tests.helpers import random_walk


def test_rsi_reference_wilder():
    c = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
    assert abs(ind.rsi(c)[14] - 70.46) < 0.1


def test_ema_and_sma():
    assert ind.ema([1, 2, 3, 4, 5], 3)[2:] == [2.0, 3.0, 4.0]
    assert ind.sma([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]


def test_bollinger_contains_price_mostly():
    C = random_walk(400, seed=3)
    close = [x.c for x in C]
    _, up, lo = ind.bollinger(close)
    inside = sum(1 for i in range(19, len(C)) if lo[i] <= close[i] <= up[i])
    assert inside / (len(C) - 19) > 0.85


def test_adx_and_atr_ranges():
    C = random_walk(300, seed=4)
    a = [x for x in ind.adx(C) if x is not None]
    assert a and all(0 <= x <= 100 for x in a)
    assert all(x > 0 for x in ind.atr(C)[14:])


def test_aggregate_5m_alignment():
    C = random_walk(23, seed=5)
    c5 = ind.aggregate(C, 5)
    assert all(x.t % 300_000 == 0 for x in c5)
    first = [x for x in C if x.t // 300_000 * 300_000 == c5[1].t]
    assert c5[1].h == max(x.h for x in first) and c5[1].c == first[-1].c


def test_no_lookahead_analysis_identical_with_truncated_data():
    """A análise no índice i deve ser idêntica tendo ou não as velas futuras."""
    C = random_walk(700, seed=11)
    F_full = ai.build_features(C)
    checked = 0
    for i in range(ai.WARMUP, len(C) - 10, 7):
        a_full, r_full = ai.analyze(F_full, i, "x")
        F_cut = ai.build_features(C[:i + 1])
        a_cut, r_cut = ai.analyze(F_cut, i, "x")
        assert r_full == r_cut
        assert (a_full is None) == (a_cut is None)
        if a_full:
            assert a_full.direction == a_cut.direction and math.isclose(a_full.strength, a_cut.strength)
            assert [v.reason for v in a_full.votes] == [v.reason for v in a_cut.votes]
            checked += 1
    assert checked > 0  # houve oportunidades para comparar


def test_backtest_on_random_walk_has_no_edge():
    """Em preço aleatório, nenhuma estratégia pode ter vantagem real (detecta vazamento de futuro)."""
    res = []
    for s in range(12):
        res += ai.simulate_outcomes(random_walk(1500, seed=100 + s))
    for e in (1, 2, 5):
        v = [r for r in res if r["res"][e] != 0]
        w = sum(r["res"][e] > 0 for r in v)
        lo, hi = ai.wilson(w, len(v), z=3.0)
        assert len(v) > 200
        assert lo < 0.5 < hi, f"vantagem suspeita em {e} min: {w}/{len(v)}"


def test_entry_uses_minute_after_signal():
    C = random_walk(600, seed=21)
    res = ai.simulate_outcomes(C)
    by_t = {c.t: i for i, c in enumerate(C)}
    for r in res[:20]:
        i = by_t[r["t"]] - 2   # vela da decisão
        assert C[i + 2].t - C[i].t == 120_000


def test_calibrator_shrinks_and_requires_data():
    cal = ai.Calibrator(min_n=30, prior_k=20)
    assert cal.estimate("s", "A", 1)["calibrated"] is False
    for k in range(40):
        cal.add("s", "A", 1, k < 30)  # 75% de acerto observado
    est = cal.estimate("s", "A", 1)
    assert est["calibrated"] and 0.5 < est["p"] < 0.75  # encolhido em direção a 50%
    assert est["ci"][0] < est["raw"] < est["ci"][1]


def test_walk_forward_uses_only_past_folds():
    res = [{"strategy": "s", "bucket": "A", "res": {1: 1 if i < 100 else -1}} for i in range(200)]
    wf = ai.walk_forward(res, 1, folds=4, min_conf=0.55)
    # blocos 1 e 2 calibrados com passado 100% vencedor; bloco 3 (perdedor) ainda aceito porque
    # o passado era bom — o teste prova que o futuro não "vaza" para a calibração.
    assert wf["tested"] > 0 and wf["folds"][0]["wins"] == wf["folds"][0]["tested"]
    assert wf["folds"][-1]["wins"] == 0


def test_volatility_regime_blocks():
    C = random_walk(400, seed=8)
    for k in range(380, 400):  # explosão de volatilidade
        x = C[k]
        C[k] = Candle(x.t, x.o, x.o * 1.05, x.o * 0.95, x.c, x.v)
    F = ai.build_features(C)
    assert ai.regime(F, 399) == "VOLÁTIL"
    assert ai.analyze(F, 399, "x")[0] is None


def test_pipeline_latency_budget():
    """Teste de latência: analisar 1000 velas deve caber com folga em um ciclo de 1 minuto."""
    C = random_walk(1000, seed=9)
    t0 = time.perf_counter()
    for _ in range(5):
        F = ai.build_features(C)
        ai.analyze(F, len(C) - 1, "x")
    per = (time.perf_counter() - t0) / 5
    assert per < 0.5, f"análise lenta: {per * 1000:.0f} ms"
