/* =====================================================================
   SinaisPro — motor de análise técnica (roda no celular)
   Candle: {t: ms abertura, o, h, l, c, v}
   Nada aqui inventa preço: tudo é calculado a partir das velas recebidas.
   ===================================================================== */
(function (root) {
  'use strict';

  /* ---------------- indicadores ---------------- */
  function sma(a, n) { const o = Array(a.length).fill(null); let s = 0;
    for (let i = 0; i < a.length; i++) { s += a[i]; if (i >= n) s -= a[i - n]; if (i >= n - 1) o[i] = s / n; } return o; }
  function ema(a, n) { const o = Array(a.length).fill(null), k = 2 / (n + 1); let e = null;
    for (let i = 0; i < a.length; i++) { if (i === n - 1) { let s = 0; for (let j = 0; j < n; j++) s += a[j]; e = s / n; } else if (i >= n) e = a[i] * k + e * (1 - k); o[i] = e; } return o; }
  function rsi(c, n = 14) { const o = Array(c.length).fill(null); let g = 0, l = 0;
    for (let i = 1; i < c.length; i++) { const d = c[i] - c[i - 1], up = Math.max(d, 0), dn = Math.max(-d, 0);
      if (i <= n) { g += up; l += dn; if (i === n) { g /= n; l /= n; o[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l); } }
      else { g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n; o[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l); } } return o; }
  function macd(c, f = 12, s = 26, sig = 9) { const ef = ema(c, f), es = ema(c, s);
    const m = c.map((_, i) => ef[i] != null && es[i] != null ? ef[i] - es[i] : null);
    const start = m.findIndex(x => x != null); const sg = Array(c.length).fill(null);
    if (start >= 0) { const sub = ema(m.slice(start), sig); sub.forEach((v, i) => sg[start + i] = v); }
    return { macd: m, signal: sg, hist: m.map((v, i) => v != null && sg[i] != null ? v - sg[i] : null) }; }
  function bollinger(c, n = 20, k = 2) { const mid = sma(c, n), up = [], lo = [];
    for (let i = 0; i < c.length; i++) { if (mid[i] == null) { up.push(null); lo.push(null); continue; }
      let s = 0; for (let j = i - n + 1; j <= i; j++) s += (c[j] - mid[i]) ** 2; const sd = Math.sqrt(s / n);
      up.push(mid[i] + k * sd); lo.push(mid[i] - k * sd); } return { mid, up, lo }; }
  function trueRange(C) { return C.map((x, i) => i === 0 ? x.h - x.l : Math.max(x.h - x.l, Math.abs(x.h - C[i - 1].c), Math.abs(x.l - C[i - 1].c))); }
  function wilder(a, n) { const o = Array(a.length).fill(null); let s = 0;
    for (let i = 0; i < a.length; i++) { if (i < n) { s += a[i]; if (i === n - 1) o[i] = s / n; } else o[i] = (o[i - 1] * (n - 1) + a[i]) / n; } return o; }
  function atr(C, n = 14) { return wilder(trueRange(C), n); }
  function adx(C, n = 14) {
    const tr = trueRange(C), pdm = [0], ndm = [0];
    for (let i = 1; i < C.length; i++) { const u = C[i].h - C[i - 1].h, d = C[i - 1].l - C[i].l;
      pdm.push(u > d && u > 0 ? u : 0); ndm.push(d > u && d > 0 ? d : 0); }
    const str = wilder(tr, n), sp = wilder(pdm, n), sn = wilder(ndm, n);
    const pdi = [], ndi = [], dx = [];
    for (let i = 0; i < C.length; i++) { if (str[i] == null || str[i] === 0) { pdi.push(null); ndi.push(null); dx.push(0); continue; }
      const p = 100 * sp[i] / str[i], m = 100 * sn[i] / str[i]; pdi.push(p); ndi.push(m); dx.push(p + m === 0 ? 0 : 100 * Math.abs(p - m) / (p + m)); }
    const first = n * 2 - 1, out = Array(C.length).fill(null);
    if (C.length > first) { let s = 0; for (let i = n; i <= first; i++) s += dx[i]; out[first] = s / n;
      for (let i = first + 1; i < C.length; i++) out[i] = (out[i - 1] * (n - 1) + dx[i]) / n; }
    return { adx: out, pdi, ndi };
  }

  /* ---------------- estrutura de preço ---------------- */
  // pivôs (topos e fundos) agrupados em zonas de suporte/resistência
  function levels(C, end, look = 120, w = 3, tol) {
    const s = Math.max(w, end - look), piv = [];
    for (let i = s; i <= end - w; i++) { let hi = true, lo = true;
      for (let j = 1; j <= w; j++) { if (C[i].h <= C[i - j].h || C[i].h < C[i + j].h) hi = false; if (C[i].l >= C[i - j].l || C[i].l > C[i + j].l) lo = false; }
      if (hi) piv.push(C[i].h); if (lo) piv.push(C[i].l); }
    piv.sort((a, b) => a - b); const z = [];
    piv.forEach(p => { const last = z[z.length - 1]; if (last && p - last.p <= tol) { last.p = (last.p * last.n + p) / (last.n + 1); last.n++; } else z.push({ p, n: 1 }); });
    return z.filter(x => x.n >= 2);
  }
  function fibo(C, end, look = 60) { let hi = -Infinity, lo = Infinity, hiI = 0, loI = 0;
    for (let i = Math.max(0, end - look); i <= end; i++) { if (C[i].h > hi) { hi = C[i].h; hiI = i; } if (C[i].l < lo) { lo = C[i].l; loI = i; } }
    const up = loI < hiI, r = hi - lo; // up = perna de alta
    return [0.382, 0.5, 0.618].map(f => ({ f, p: up ? hi - r * f : lo + r * f, up })); }
  function candlePattern(C, i) {
    const x = C[i], p = C[i - 1], body = Math.abs(x.c - x.o), rng = x.h - x.l || 1e-12;
    const upW = x.h - Math.max(x.o, x.c), loW = Math.min(x.o, x.c) - x.l, pb = Math.abs(p.c - p.o);
    if (x.c > x.o && p.c < p.o && x.c >= p.o && x.o <= p.c && body > pb) return { dir: 1, name: 'Engolfo de alta' };
    if (x.c < x.o && p.c > p.o && x.o >= p.c && x.c <= p.o && body > pb) return { dir: -1, name: 'Engolfo de baixa' };
    if (loW >= 2 * body && upW <= body * 0.6 && body / rng < 0.4) return { dir: 1, name: 'Martelo / pin bar de alta' };
    if (upW >= 2 * body && loW <= body * 0.6 && body / rng < 0.4) return { dir: -1, name: 'Estrela cadente / pin bar de baixa' };
    if (body / rng < 0.1) return { dir: 0, name: 'Doji (indecisão)' };
    return null;
  }
  function aggregate(C, m) { // velas de 1 min -> m min (alinhadas ao relógio)
    const out = []; let cur = null;
    C.forEach(x => { const b = Math.floor(x.t / (m * 60000)) * m * 60000;
      if (!cur || cur.t !== b) { cur = { t: b, o: x.o, h: x.h, l: x.l, c: x.c, v: x.v || 0 }; out.push(cur); }
      else { cur.h = Math.max(cur.h, x.h); cur.l = Math.min(cur.l, x.l); cur.c = x.c; cur.v += x.v || 0; } });
    return out;
  }

  /* ---------------- pré-cálculo ---------------- */
  function prepare(C) {
    const c = C.map(x => x.c);
    const P = { C, c, e9: ema(c, 9), e21: ema(c, 21), e50: ema(c, 50), s20: sma(c, 20), rsi: rsi(c), macd: macd(c), bb: bollinger(c), atr: atr(C), adx: adx(C) };
    const vol = C.map(x => x.v || 0); P.hasVol = vol.some(v => v > 0); P.vma = sma(vol, 20);
    const C5 = aggregate(C, 5), c5 = C5.map(x => x.c), e5a = ema(c5, 9), e5b = ema(c5, 21);
    P.tf5 = { C5, e5a, e5b }; P.idx5 = C.map(x => { const b = Math.floor(x.t / 300000) * 300000; return C5.findIndex(y => y.t === b); });
    return P;
  }

  /* ---------------- modelo combinado ----------------
     Cada componente vota +1 (CALL) ou −1 (PUT) com um peso. O sinal só sai
     quando vários componentes independentes concordam (sem indicador único). */
  const MODES = {
    conservador: { minScore: 5.0, minAgree: 4, maxAgainst: 1 },
    moderado:    { minScore: 3.5, minAgree: 3, maxAgainst: 1 },
    agressivo:   { minScore: 2.5, minAgree: 2, maxAgainst: 2 },
  };
  function analyze(P, i) {
    const { C, c } = P; if (i < 60 || P.atr[i] == null || P.adx.adx[i] == null || P.e50[i] == null) return null;
    const x = C[i], A = P.atr[i] || 1e-12, votes = [];
    const vote = (dir, w, name, why) => { if (dir) votes.push({ dir, w, name, why }); };
    const adxV = P.adx.adx[i], trending = adxV >= 22;
    // 1) tendência 1m (EMAs 9/21/50)
    const up = P.e9[i] > P.e21[i] && P.e21[i] > P.e50[i] && x.c > P.e50[i];
    const dn = P.e9[i] < P.e21[i] && P.e21[i] < P.e50[i] && x.c < P.e50[i];
    if (up || dn) vote(up ? 1 : -1, trending ? 2 : 1, 'Tendência', `EMA 9/21/50 alinhadas ${up ? 'para cima' : 'para baixo'} · ADX ${adxV.toFixed(0)}`);
    // 2) múltiplos timeframes (5m)
    const j = P.idx5[i] - 1; // usa somente a vela de 5m já fechada
    if (j >= 21 && P.tf5.e5a[j] != null && P.tf5.e5b[j] != null) { const d5 = P.tf5.e5a[j] > P.tf5.e5b[j] ? 1 : -1; vote(d5, 1, 'Timeframe 5m', `EMA 9 ${d5 > 0 ? 'acima' : 'abaixo'} da EMA 21 no gráfico de 5 min`); }
    // 3) MACD
    const h = P.macd.hist[i], hp = P.macd.hist[i - 1];
    if (h != null && hp != null) { if (hp <= 0 && h > 0) vote(1, 1.5, 'MACD', 'Cruzamento de alta do MACD'); else if (hp >= 0 && h < 0) vote(-1, 1.5, 'MACD', 'Cruzamento de baixa do MACD');
      else if (Math.abs(h) > Math.abs(hp)) vote(Math.sign(h), 0.75, 'MACD', `Histograma ${h > 0 ? 'positivo' : 'negativo'} crescendo`); }
    // 4) RSI
    const r = P.rsi[i];
    if (r != null) { if (!trending && r <= 30) vote(1, 1.5, 'RSI', `RSI ${r.toFixed(0)} sobrevendido em mercado lateral`);
      else if (!trending && r >= 70) vote(-1, 1.5, 'RSI', `RSI ${r.toFixed(0)} sobrecomprado em mercado lateral`);
      else if (trending && r > 52 && r < 68) vote(1, 0.75, 'RSI', `RSI ${r.toFixed(0)} confirma força compradora`);
      else if (trending && r < 48 && r > 32) vote(-1, 0.75, 'RSI', `RSI ${r.toFixed(0)} confirma força vendedora`); }
    // 5) Bollinger (reversão em lateralidade)
    const bu = P.bb.up[i], bl = P.bb.lo[i];
    if (bu != null && !trending) { if (x.l < bl && x.c > bl) vote(1, 1.5, 'Bollinger', 'Rejeição abaixo da banda inferior');
      else if (x.h > bu && x.c < bu) vote(-1, 1.5, 'Bollinger', 'Rejeição acima da banda superior'); }
    // 6) suporte/resistência, rompimentos e falsos rompimentos
    const lv = levels(C, i - 1, 120, 3, A * 0.5);
    for (const z of lv) {
      const prev = C[i - 1];
      if (prev.c <= z.p && x.c > z.p + 0.2 * A && x.c > x.o) { vote(1, 1.5, 'Rompimento', `Fechou acima da resistência ${fmtP(z.p)} (${z.n} toques)`); break; }
      if (prev.c >= z.p && x.c < z.p - 0.2 * A && x.c < x.o) { vote(-1, 1.5, 'Rompimento', `Fechou abaixo do suporte ${fmtP(z.p)} (${z.n} toques)`); break; }
      if (x.h > z.p + 0.1 * A && x.c < z.p && prev.c < z.p) { vote(-1, 1.5, 'Falso rompimento', `Pavio acima de ${fmtP(z.p)} e fechamento abaixo`); break; }
      if (x.l < z.p - 0.1 * A && x.c > z.p && prev.c > z.p) { vote(1, 1.5, 'Falso rompimento', `Pavio abaixo de ${fmtP(z.p)} e fechamento acima`); break; }
      if (Math.abs(x.l - z.p) < 0.3 * A && x.c > x.o) { vote(1, 1, 'Suporte', `Reação compradora no suporte ${fmtP(z.p)}`); break; }
      if (Math.abs(x.h - z.p) < 0.3 * A && x.c < x.o) { vote(-1, 1, 'Resistência', `Reação vendedora na resistência ${fmtP(z.p)}`); break; }
    }
    // 7) padrão de vela (price action)
    const cp = candlePattern(C, i); if (cp && cp.dir) vote(cp.dir, 1, 'Vela', cp.name);
    // 8) Fibonacci
    for (const f of fibo(C, i - 1)) { if (x.l <= f.p && x.h >= f.p) { const d = x.c > x.o ? 1 : x.c < x.o ? -1 : 0;
      if (d && (d > 0) === f.up) vote(d, 0.5, 'Fibonacci', `Reação na retração de ${(f.f * 100).toFixed(1)}%`); break; } }
    // 9) volume (quando houver)
    if (P.hasVol && P.vma[i] && x.v > 1.5 * P.vma[i]) { const d = x.c > x.o ? 1 : x.c < x.o ? -1 : 0; vote(d, 0.5, 'Volume', `Volume ${(x.v / P.vma[i]).toFixed(1)}× a média`); }

    const score = votes.reduce((s, v) => s + v.dir * v.w, 0);
    const dir = Math.sign(score); if (!dir) return null;
    const agree = votes.filter(v => v.dir === dir), against = votes.filter(v => v.dir !== dir);
    const groups = new Set(agree.map(v => v.name));
    return { i, t: x.t, dir, score: Math.abs(score), agree: groups.size, against: against.length, votes, adx: adxV, trending };
  }
  function strategyOf(a) { const n = new Set(a.votes.filter(v => v.dir === a.dir).map(v => v.name));
    if (n.has('Rompimento')) return 'Rompimento'; if (n.has('Falso rompimento') || n.has('Bollinger') || (n.has('RSI') && !a.trending)) return 'Reversão';
    if (n.has('Suporte') || n.has('Resistência')) return 'Suporte/Resistência'; return 'Tendência'; }
  function passes(a, mode) { const m = MODES[mode]; return a && a.score >= m.minScore && a.agree >= m.minAgree && a.against <= m.maxAgainst; }
  const bucket = s => s >= 7 ? 'A' : s >= 5 ? 'B' : s >= 3.5 ? 'C' : 'D';

  /* ---------------- walk-forward / backtest ----------------
     Em cada vela i usa SOMENTE velas 0..i (passado). Entrada no preço de
     abertura da vela i+1; resultado pelo fechamento da vela i+exp. */
  function backtest(C, mode, expiries = [1, 2, 5]) {
    const P = prepare(C), res = []; let last = -99;
    for (let i = 60; i < C.length - 7; i++) {
      const a = analyze(P, i); if (!passes(a, mode)) continue;
      if (i - last < 3) continue; last = i; // evita sinais colados
      // entrada no início do minuto seguinte ao aviso (vela i+2), como no app ao vivo
      if (C[i + 2].t - C[i].t !== 120000) continue; // pula buracos nos dados
      const entry = C[i + 2].o, out = {};
      expiries.forEach(e => { const ex = C[i + 1 + e].c; out[e] = ex === entry ? 0 : (ex > entry) === (a.dir > 0) ? 1 : -1; });
      res.push({ t: C[i + 2].t, dir: a.dir, score: a.score, b: bucket(a.score), strat: strategyOf(a), out });
    }
    return res;
  }
  function wilson(k, n, z = 1.96) { if (!n) return [0, 0]; const p = k / n, d = 1 + z * z / n, c = p + z * z / (2 * n), m = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)); return [(c - m) / d, (c + m) / d]; }
  function summarize(list, exp) { const v = list.filter(r => r.out[exp] !== 0 && r.out[exp] != null); const w = v.filter(r => r.out[exp] > 0).length;
    return { n: v.length, w, rate: v.length ? w / v.length : null, ci: wilson(w, v.length) }; }

  let PRICE_DEC = 5; function fmtP(p) { return p.toFixed(PRICE_DEC); }
  const api = { sma, ema, rsi, macd, bollinger, atr, adx, levels, fibo, candlePattern, aggregate, prepare, analyze, passes, strategyOf, backtest, summarize, wilson, bucket, MODES,
    setDec(d) { PRICE_DEC = d; } };
  if (typeof module !== 'undefined') module.exports = api; else root.Engine = api;
})(this);
