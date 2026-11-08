// Modelo de previsão (Poisson) — funciona no navegador e no Node (para testes)
(function (root) {
  function pois(k, l) {
    let p = Math.exp(-l);
    for (let i = 1; i <= k; i++) p *= l / i;
    return p;
  }

  // Força de ataque/defesa a partir da tabela de classificação
  function buildStrengths(rows) {
    // rows: [{id, gp, gf, ga}]
    let tg = 0, tp = 0;
    rows.forEach(r => { tg += r.gf; tp += r.gp; });
    const avg = tp > 0 ? tg / tp : 1.3;
    const K = 5; // encolhe para a média quando há poucos jogos
    const map = {};
    rows.forEach(r => {
      map[r.id] = {
        att: (r.gf + avg * K) / (r.gp + K) / avg,
        def: (r.ga + avg * K) / (r.gp + K) / avg,
      };
    });
    return { avg, map };
  }

  // Força aproximada pela sequência de forma (ex.: "VVEDV" ou "WWDLW")
  function formFactor(form) {
    if (!form) return 1;
    let pts = 0, n = 0;
    for (const c of String(form).toUpperCase()) {
      if (c === 'W' || c === 'V') { pts += 3; n++; }
      else if (c === 'D' || c === 'E') { pts += 1; n++; }
      else if (c === 'L') { n++; }
    }
    if (!n) return 1;
    return 0.75 + 0.5 * (pts / (3 * n)); // 0.75 a 1.25
  }

  function expectedGoals(home, away, strengths) {
    const HOME = 1.12, AWAY = 0.9;
    let avg = 1.3, h = null, a = null;
    if (strengths) { avg = strengths.avg; h = strengths.map[home.id]; a = strengths.map[away.id]; }
    let lh, la;
    if (h && a) {
      lh = avg * h.att * a.def * HOME;
      la = avg * a.att * h.def * AWAY;
    } else {
      const fh = formFactor(home.form), fa = formFactor(away.form);
      lh = avg * HOME * fh / fa;
      la = avg * AWAY * fa / fh;
    }
    return { lh: Math.min(Math.max(lh, 0.2), 4), la: Math.min(Math.max(la, 0.2), 4) };
  }

  // lh/la = gols esperados no jogo inteiro; minute = minuto atual (0 se não começou)
  function predict(lh, la, scoreH = 0, scoreA = 0, minute = 0) {
    const rem = Math.max(0, 90 - minute) / 90;
    const rh = lh * rem, ra = la * rem;
    let H = 0, D = 0, A = 0, O25 = 0, BTTS = 0, best = { p: -1, h: 0, a: 0 };
    for (let i = 0; i <= 10; i++) {
      for (let j = 0; j <= 10; j++) {
        const p = pois(i, rh) * pois(j, ra);
        const fh = scoreH + i, fa = scoreA + j;
        if (fh > fa) H += p; else if (fh === fa) D += p; else A += p;
        if (fh + fa > 2.5) O25 += p;
        if (fh > 0 && fa > 0) BTTS += p;
        if (p > best.p) best = { p, h: fh, a: fa };
      }
    }
    const t = H + D + A;
    return {
      home: H / t, draw: D / t, away: A / t,
      over25: O25 / t, btts: BTTS / t,
      score: best.h + ' x ' + best.a, scoreProb: best.p / t,
      xgH: lh, xgA: la,
    };
  }

  const api = { pois, buildStrengths, formFactor, expectedGoals, predict };
  if (typeof module !== 'undefined') module.exports = api; else root.Model = api;
})(this);
