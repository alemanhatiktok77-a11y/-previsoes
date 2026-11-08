/* =====================================================================
   SinaisPro — aplicativo (telas, conexões, ciclo de vida dos sinais)
   ===================================================================== */
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
const pct = (x, d = 1) => x == null ? '—' : (x * 100).toFixed(d).replace('.', ',') + '%';
const hhmm = t => new Date(t).toLocaleTimeString('pt-BR', { hour:'2-digit', minute:'2-digit' });
const hhmmss = t => new Date(t).toLocaleTimeString('pt-BR', { hour:'2-digit', minute:'2-digit', second:'2-digit' });
const dkey = t => { const d = new Date(t); return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate(); };
function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('on'); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('on'), 2600); }

/* ---------------- configurações e banco local ---------------- */
const DEF = { mode:'conservador', minConf:56, allowUncal:false, expPref:'auto', assets:{ BTCUSDT:true, ETHUSDT:true, SOLUSDT:true },
  tdKey:'', notif:true, keepOn:false, newsBlock:15, maxLat:2000, payout:85, stake:10, dailyMaxLoss:50, maxDay:15, paperAuto:true, paperStart:1000 };
function ld(k, d) { try { return JSON.parse(localStorage.getItem(k)) || d; } catch (e) { return d; } }
const CFG = Object.assign({}, DEF, ld('sp_cfg', {}));
const DB = Object.assign({ signals:[], bal:null, log:[] }, ld('sp_db', {}));
if (DB.bal == null) DB.bal = CFG.paperStart;
const saveCfg = () => { try { localStorage.setItem('sp_cfg', JSON.stringify(CFG)); } catch (e) {} };
const saveDb = () => { try { DB.signals = DB.signals.slice(-3000); DB.log = DB.log.slice(-200); localStorage.setItem('sp_db', JSON.stringify(DB)); } catch (e) {} };
function log(m) { DB.log.push({ t: Date.now(), m }); if (DB.log.length % 10 === 0) saveDb(); }

/* ---------------- estado em tempo de execução ---------------- */
const RT = { C:{}, live:{}, lat:{}, lastMsg:{}, conn:{ binance:'off', twelve: 'off', news:'off', cal:'off', clock:'off' }, connMsg:{},
  offset:0, bt:{}, analyzed:0, news:[], cal:[], feeds:{}, credits:0, reasons:{}, wsRetry:1000 };
const now = () => Date.now() + RT.offset; // horário sincronizado com o servidor
const enabled = () => ASSETS.filter(a => CFG.assets[a.id] && (a.src === 'binance' || CFG.tdKey));
const assetOf = id => ASSETS.find(a => a.id === id);

/* ---------------- rede (via Android, sem bloqueio de CORS) ---------------- */
const pend = {}; let rid = 0;
window.__netCb = (id, body, err, ms) => { const p = pend[id]; if (!p) return; delete pend[id]; err ? p.rej(new Error(err)) : p.res(body); };
function net(url, timeout = 20000) {
  if (window.AndroidApp && AndroidApp.get) return new Promise((res, rej) => { const id = 'q' + (++rid); pend[id] = { res, rej };
    setTimeout(() => { if (pend[id]) { delete pend[id]; rej(new Error('tempo esgotado')); } }, timeout); AndroidApp.get(id, url); });
  return fetch(url).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); });
}
const netJson = (u, t) => net(u, t).then(JSON.parse);

/* ---------------- relógio ---------------- */
async function syncClock() {
  for (const u of ['https://api.binance.com/api/v3/time', 'https://data-api.binance.vision/api/v3/time']) {
    try { const t0 = Date.now(); const j = await netJson(u, 8000); const t1 = Date.now();
      RT.offset = j.serverTime - (t0 + t1) / 2; RT.rtt = t1 - t0; RT.conn.clock = 'ok'; RT.connMsg.clock = `ajuste ${Math.round(RT.offset)} ms · ida e volta ${RT.rtt} ms`; return; }
    catch (e) { RT.connMsg.clock = e.message; }
  }
  RT.conn.clock = 'bad';
}

/* ---------------- Binance (cripto, WebSocket) ---------------- */
async function loadBinance() {
  const list = enabled().filter(a => a.src === 'binance'); if (!list.length) { RT.conn.binance = 'off'; return; }
  RT.conn.binance = 'load'; RT.connMsg.binance = 'baixando histórico…'; render();
  for (const a of list) {
    for (const host of ['https://data-api.binance.vision', 'https://api.binance.com']) {
      try { const k = await netJson(`${host}/api/v3/klines?symbol=${a.id}&interval=1m&limit=1000`);
        RT.C[a.id] = k.map(x => ({ t:x[0], o:+x[1], h:+x[2], l:+x[3], c:+x[4], v:+x[5] }));
        if (RT.C[a.id].length && RT.C[a.id][RT.C[a.id].length - 1].t + 60000 > now()) RT.C[a.id].pop(); // remove a vela ainda aberta
        break; } catch (e) { RT.connMsg.binance = 'histórico: ' + e.message; }
    }
  }
  queueBacktests(list); connectWs(list);
}
let ws = null, wsWatch = null;
function connectWs(list) {
  if (ws) { try { ws.onclose = null; ws.close(); } catch (e) {} }
  const streams = list.map(a => a.id.toLowerCase() + '@kline_1m').join('/');
  const hosts = ['wss://data-stream.binance.vision/stream?streams=', 'wss://stream.binance.com:9443/stream?streams='];
  const url = hosts[(RT.wsHost = (RT.wsHost || 0)) % 2] + streams;
  RT.conn.binance = 'load'; RT.connMsg.binance = 'conectando…';
  try { ws = new WebSocket(url); } catch (e) { return retryWs(list); }
  ws.onopen = () => { RT.conn.binance = 'ok'; RT.connMsg.binance = 'tempo real'; RT.wsRetry = 1000; log('WebSocket conectado'); render(); };
  ws.onmessage = ev => { let m; try { m = JSON.parse(ev.data); } catch (e) { return; } const d = m.data; if (!d || !d.k) return; onKline(d); };
  ws.onerror = () => { RT.connMsg.binance = 'erro de conexão'; };
  ws.onclose = () => { RT.conn.binance = 'bad'; RT.connMsg.binance = 'desconectado — reconectando'; retryWs(list); render(); };
  clearInterval(wsWatch);
  wsWatch = setInterval(() => { // vigia: sem mensagens por 20 s = reconecta
    const last = Math.max(0, ...list.map(a => RT.lastMsg[a.id] || 0));
    if (ws && ws.readyState === 1 && last && Date.now() - last > 20000) { log('Sem dados há 20 s — reconectando'); ws.close(); }
  }, 5000);
}
function retryWs(list) { RT.wsHost++; setTimeout(() => connectWs(list), RT.wsRetry); RT.wsRetry = Math.min(30000, RT.wsRetry * 2); }
function onKline(d) {
  const k = d.k, id = k.s, C = RT.C[id]; if (!C) return;
  RT.lastMsg[id] = Date.now(); RT.lat[id] = Math.max(0, Math.round(now() - d.E));
  const c = { t:k.t, o:+k.o, h:+k.h, l:+k.l, c:+k.c, v:+k.v };
  RT.live[id] = { p: c.c, t: d.E, open: c };
  onTick(id, c);
  if (k.x) { const last = C[C.length - 1]; if (!last || last.t < c.t) { C.push(c); if (C.length > 1500) C.shift(); onClose(id, c); } }
}

/* ---------------- Twelve Data (forex, sondagem por minuto) ---------------- */
let tdTimer = null;
const tdUrl = (sym, n) => `https://api.twelvedata.com/time_series?symbol=${encodeURIComponent(sym)}&interval=1min&outputsize=${n}&timezone=UTC&apikey=${encodeURIComponent(CFG.tdKey)}`;
function tdParse(j) { if (j.status === 'error' || !j.values) throw new Error(j.message || 'sem dados');
  return j.values.map(v => ({ t: Date.parse(v.datetime.replace(' ', 'T') + 'Z'), o:+v.open, h:+v.high, l:+v.low, c:+v.close, v:+(v.volume || 0) })).reverse(); }
function creditsToday() { const k = dkey(Date.now()); if (DB.tdDay !== k) { DB.tdDay = k; DB.tdCred = 0; } return DB.tdCred; }
function spend(n) { creditsToday(); DB.tdCred += n; RT.credits = DB.tdCred; }
async function loadTwelve() {
  const list = enabled().filter(a => a.src === 'twelve'); clearInterval(tdTimer); clearTimeout(RT.tdStart);
  if (!CFG.tdKey || !list.length) { RT.conn.twelve = 'off'; RT.connMsg.twelve = CFG.tdKey ? 'nenhum par ativado' : 'sem chave (Configurações)'; return; }
  RT.conn.twelve = 'load'; RT.connMsg.twelve = 'baixando histórico…';
  let ok = 0;
  for (const a of list) {
    try { RT.C[a.id] = tdParse(await netJson(tdUrl(a.id, 1000))); spend(1);
      const C = RT.C[a.id]; if (C.length && C[C.length - 1].t + 60000 > now()) C.pop(); ok++; }
    catch (e) { RT.connMsg.twelve = a.name + ': ' + e.message; }
    await new Promise(r => setTimeout(r, 8000)); // respeita o limite gratuito (8 req/min)
  }
  if (ok) { RT.conn.twelve = 'ok'; RT.connMsg.twelve = 'atualiza a cada minuto'; queueBacktests(list.filter(a => RT.C[a.id])); }
  else RT.conn.twelve = 'bad';
  const tick = async () => {
    if (!forexOpen()) { RT.connMsg.twelve = 'mercado forex fechado'; return; }
    for (const a of list) { if (!RT.C[a.id]) continue;
      try { const rows = tdParse(await netJson(tdUrl(a.id, 3))); spend(1); RT.lastMsg[a.id] = Date.now();
        const C = RT.C[a.id], last = rows[rows.length - 1];
        RT.live[a.id] = { p: last.c, t: Date.now(), open: last };
        rows.forEach(r => { if (r.t + 60000 > now()) { onTick(a.id, r); return; } // vela ainda em formação
          if (!C.length || r.t > C[C.length - 1].t) { C.push(r); if (C.length > 1500) C.shift(); RT.lat[a.id] = Math.round(now() - (r.t + 60000)); onClose(a.id, r); } });
        RT.conn.twelve = 'ok'; RT.connMsg.twelve = `créditos hoje: ${creditsToday()}/800`;
      } catch (e) { RT.conn.twelve = 'bad'; RT.connMsg.twelve = e.message; }
      await new Promise(r => setTimeout(r, 300));
    }
    saveDb(); render();
  };
  // primeiro ciclo no início do próximo minuto + 3 s
  clearTimeout(RT.tdStart); RT.tdStart = setTimeout(() => { tick(); clearInterval(tdTimer); tdTimer = setInterval(tick, 60000); }, 63000 - (now() % 60000));
}
function forexOpen(t = now()) { const d = new Date(t), wd = d.getUTCDay(), h = d.getUTCHours();
  if (wd === 6) return false; if (wd === 5 && h >= 21) return false; if (wd === 0 && h < 21) return false; return true; }
function marketOpen(a) { return a.src === 'binance' ? true : forexOpen(); }

/* ---------------- backtest walk-forward ---------------- */
function queueBacktests(list) { let i = 0; const step = () => { const a = list[i++]; if (!a) { render(); return; } runBt(a.id); render(); setTimeout(step, 30); }; setTimeout(step, 50); }
function runBt(id) { const C = RT.C[id]; if (!C || C.length < 200) return; Engine.setDec(assetOf(id).dec);
  RT.bt[id] = {}; for (const m of Object.keys(Engine.MODES)) RT.bt[id][m] = Engine.backtest(C, m); }
// taxa histórica calibrada: só resultados ANTERIORES ao momento (backtest + sinais reais já concluídos)
function calib(id, mode, exp, b) {
  const bt = (RT.bt[id] && RT.bt[id][mode]) || [];
  const live = DB.signals.filter(s => s.asset === id && s.mode === mode && s.exp === exp && (s.res === 1 || s.res === -1))
    .map(s => ({ b: s.bucket, out: { [exp]: s.res } }));
  const all = bt.concat(live);
  const same = all.filter(r => r.b === b), use = Engine.summarize(same, exp).n >= 30 ? same : all;
  const s = Engine.summarize(use, exp); s.scope = use === same ? 'mesmo nível de força' : 'todos os sinais do modo'; return s;
}
function bestExpiry(id, mode, b) {
  if (CFG.expPref !== 'auto') return { exp: +CFG.expPref, cal: calib(id, mode, +CFG.expPref, b) };
  let best = null; [1, 2, 5].forEach(e => { const c = calib(id, mode, e, b); if (c.n >= 30 && (!best || c.ci[0] > best.cal.ci[0])) best = { exp: e, cal: c }; });
  return best || { exp: 2, cal: calib(id, mode, 2, b) };
}

/* ---------------- notícias e calendário ---------------- */
async function loadNews() {
  RT.conn.news = 'load'; const out = []; let ok = 0;
  await Promise.all(NEWS_FEEDS.map(async f => {
    try { const x = await net(f.url, 15000); const doc = new DOMParser().parseFromString(x, 'text/xml');
      const items = [...doc.querySelectorAll('item, entry')].slice(0, 25);
      if (!items.length) throw new Error('feed vazio');
      items.forEach(it => { const g = s => (it.querySelector(s) || {}).textContent || '';
        const title = g('title').trim(), link = g('link').trim() || ((it.querySelector('link') || { getAttribute(){ return ''; } }).getAttribute('href')),
          date = Date.parse(g('pubDate') || g('published') || g('updated') || g('dc\\:date')) || null, desc = g('description').replace(/<[^>]+>/g, ' ').slice(0, 300);
        if (!title) return; const cl = NLP.classify(title + ' ' + desc, f.cb);
        out.push({ src: f.name, title, link, date, desc, ...cl }); });
      RT.feeds[f.name] = 'ok'; ok++;
    } catch (e) { RT.feeds[f.name] = e.message; }
  }));
  const seen = new Set(); RT.news = out.filter(n => !seen.has(n.title) && seen.add(n.title)).sort((a, b) => (b.date || 0) - (a.date || 0));
  RT.conn.news = ok ? 'ok' : 'bad'; RT.connMsg.news = `${ok}/${NEWS_FEEDS.length} fontes · ${RT.news.length} notícias`; RT.newsAt = Date.now(); render();
}
async function loadCal() {
  try { const j = await netJson(CALENDAR_URL, 15000);
    RT.cal = j.map(e => ({ title: e.title, ccy: e.country, t: Date.parse(e.date), impact: e.impact, fc: e.forecast, prev: e.previous })).filter(e => e.t).sort((a, b) => a.t - b.t);
    RT.conn.cal = 'ok'; RT.connMsg.cal = RT.cal.length + ' eventos na semana'; }
  catch (e) { RT.conn.cal = 'bad'; RT.connMsg.cal = e.message; }
  render();
}
function riskEvents(a, win) { const w = win * 60000, t = now();
  return RT.cal.filter(e => e.impact === 'High' && a.ccy.includes(e.ccy) && Math.abs(e.t - t) <= w); }
function newsFor(a) {
  const t = now(), cal = RT.cal.filter(e => (e.impact === 'High' || e.impact === 'Medium') && a.ccy.includes(e.ccy) && e.t > t - 30 * 60000 && e.t < t + 120 * 60000).slice(0, 3)
    .map(e => `${hhmm(e.t)} ${e.ccy} ${e.title} (${e.impact === 'High' ? 'alto' : 'médio'} impacto)`);
  const nw = RT.news.filter(n => n.date && t - n.date < 3 * 3600000 && n.impact !== 'Baixo' && n.ccy.some(c => a.ccy.includes(c))).slice(0, 2).map(n => `${n.src}: ${n.title}`);
  return cal.concat(nw);
}

/* ---------------- ciclo de vida dos sinais ---------------- */
function todaySignals() { const k = dkey(Date.now()); return DB.signals.filter(s => dkey(s.gen) === k); }
function todayLoss() { return todaySignals().reduce((s, x) => s + (x.pnl || 0), 0); }
function gate(a) { // motivos para NÃO gerar sinal agora
  const r = [];
  if (!marketOpen(a)) r.push('mercado fechado');
  const lat = RT.lat[a.id]; if (lat == null) r.push('sem dados ao vivo'); else if (a.src === 'binance' && lat > CFG.maxLat) r.push(`latência alta (${lat} ms)`);
  else if (a.src === 'twelve' && lat > 90000) r.push('dados atrasados');
  if (RT.conn.clock !== 'ok') r.push('relógio não sincronizado');
  if (a.src === 'binance' && RT.conn.binance !== 'ok') r.push('WebSocket desconectado');
  const ev = riskEvents(a, CFG.newsBlock); if (ev.length) r.push(`evento de alto impacto: ${ev[0].ccy} ${ev[0].title} às ${hhmm(ev[0].t)}`);
  if (DB.signals.some(s => s.asset === a.id && (s.st === 'aguardando' || s.st === 'ativo'))) r.push('já existe sinal em andamento neste ativo');
  if (todaySignals().length >= CFG.maxDay) r.push('limite diário de sinais atingido');
  if (-todayLoss() >= CFG.dailyMaxLoss) r.push('limite de perda diária (paper) atingido');
  if (!RT.bt[a.id]) r.push('histórico ainda carregando');
  return r;
}
function onClose(id, c) {
  RT.analyzed++; const a = assetOf(id); resolve(id, c);
  const C = RT.C[id]; Engine.setDec(a.dec);
  const P = Engine.prepare(C), i = C.length - 1, an = Engine.analyze(P, i);
  RT.last = RT.last || {}; RT.last[id] = { an, P, i };
  const block = gate(a); RT.reasons[id] = block;
  if (block.length || !Engine.passes(an, CFG.mode)) return;
  const b = Engine.bucket(an.score), ex = bestExpiry(id, CFG.mode, b), cal = ex.cal, calibrated = cal.n >= 30;
  if (calibrated && cal.rate * 100 < CFG.minConf) { RT.reasons[id] = [`sinal descartado: acerto histórico ${pct(cal.rate)} abaixo do mínimo (${CFG.minConf}%)`]; return; }
  if (!calibrated && !CFG.allowUncal) { RT.reasons[id] = ['sinal descartado: sem histórico suficiente para calibrar']; return; }
  const j = P.idx5[i] - 1, t5 = j >= 0 && P.tf5.e5a[j] != null ? (P.tf5.e5a[j] > P.tf5.e5b[j] ? 'Alta' : 'Baixa') : '—';
  const s = { id: id + '-' + c.t, asset: id, name: a.name, market: 'NORMAL', dir: an.dir > 0 ? 'CALL' : 'PUT', exp: ex.exp, mode: CFG.mode,
    gen: c.t + 60000, recv: now(), candleT: c.t, entryT: c.t + 120000, st: 'aguardando', score: +an.score.toFixed(1), bucket: b,
    conf: calibrated ? cal.rate : null, ci: calibrated ? cal.ci : null, calN: cal.n, calScope: cal.scope,
    trend: an.adx < 20 ? 'Lateral' : (an.dir > 0 ? 'Alta' : 'Baixa'), trend5: t5, adx: Math.round(an.adx), strat: Engine.strategyOf(an),
    why: an.votes.filter(v => v.dir === an.dir).map(v => v.why), against: an.votes.filter(v => v.dir !== an.dir).map(v => v.why),
    news: newsFor(a), price: c.c, lat: RT.lat[id], paper: CFG.paperAuto };
  DB.signals.push(s); saveDb(); log(`Sinal ${s.dir} ${s.name} ${s.exp}m`);
  if (CFG.notif && window.AndroidApp && AndroidApp.notify)
    AndroidApp.notify(`${s.dir === 'CALL' ? '▲' : '▼'} ${s.dir} ${s.name} · ${s.exp} min`, `Entrada ${hhmmss(s.entryT)} · ${s.conf != null ? 'acerto histórico ' + pct(s.conf) : 'não calibrado'} · ${s.strat}`);
  toast(`Novo sinal: ${s.dir} ${s.name} (${s.exp} min)`); render();
}
function onTick(id, c) { // vela em formação: pega o preço de entrada exato
  DB.signals.forEach(s => { if (s.asset === id && s.st === 'aguardando' && c.t === s.entryT && s.entry == null) { s.entry = c.o; s.st = 'ativo'; saveDb(); } });
}
function resolve(id, c) {
  DB.signals.forEach(s => {
    if (s.asset !== id) return;
    if (s.st === 'aguardando' && c.t === s.entryT && s.entry == null) { s.entry = c.o; s.st = 'ativo'; }
    if (s.st === 'ativo' && c.t === s.entryT + (s.exp - 1) * 60000) {
      s.exit = c.c; s.res = s.exit === s.entry ? 0 : ((s.exit > s.entry) === (s.dir === 'CALL') ? 1 : -1); s.st = 'concluído'; s.end = now();
      if (s.paper) { s.pnl = s.res > 0 ? CFG.stake * CFG.payout / 100 : s.res < 0 ? -CFG.stake : 0; DB.bal += s.pnl; }
      if (CFG.notif && window.AndroidApp && AndroidApp.notify) AndroidApp.notify(`${s.res > 0 ? '✅ WIN' : s.res < 0 ? '❌ LOSS' : '➖ EMPATE'} ${s.dir} ${s.name}`, `Entrada ${s.entry} → saída ${s.exit}`);
    }
  });
  saveDb();
}
setInterval(() => { // cancela sinais sem dados no horário de entrada
  const t = now(); let ch = false;
  DB.signals.forEach(s => {
    if (s.st === 'aguardando' && t > s.entryT + 15000 && s.entry == null) { s.st = 'cancelado'; s.cancel = 'sem preço de entrada (dados atrasados ou conexão caiu)'; ch = true; }
    if (s.st === 'ativo' && t > s.entryT + s.exp * 60000 + 120000) { s.st = 'cancelado'; s.cancel = 'sem preço de saída (conexão caiu)'; ch = true; }
  });
  if (ch) { saveDb(); render(); }
  tickUi();
}, 1000);

/* ---------------- estatísticas ---------------- */
const done = () => DB.signals.filter(s => s.st === 'concluído' && s.res !== 0);
function rate(list) { const w = list.filter(s => s.res > 0).length, n = list.length; return { n, w, rate: n ? w / n : null, ci: Engine.wilson(w, n) }; }
function groupBy(list, f) { const m = {}; list.forEach(s => { const k = f(s); (m[k] = m[k] || []).push(s); }); return Object.entries(m).map(([k, v]) => ({ k, ...rate(v) })).sort((a, b) => b.n - a.n); }
const breakeven = () => 1 / (1 + CFG.payout / 100);
function deterioration() { const d = done(); if (d.length < 60) return null; const recent = rate(d.slice(-30)), before = rate(d.slice(0, -30));
  return { recent, before, bad: recent.rate < before.rate - 0.1 && recent.rate < breakeven() }; }
function walkForward(id, mode, exp, folds = 5) { // calibra no passado, testa no bloco seguinte
  const L = (RT.bt[id] && RT.bt[id][mode]) || []; if (L.length < 60) return null;
  const size = Math.floor(L.length / folds), tested = [];
  for (let k = 1; k < folds; k++) { const past = L.slice(0, k * size), test = L.slice(k * size, (k + 1) * size);
    const byB = {}; past.forEach(r => { (byB[r.b] = byB[r.b] || []).push(r); });
    test.forEach(r => { const ref = Engine.summarize(byB[r.b] || [], exp); if (ref.n >= 20 && ref.rate * 100 >= CFG.minConf) tested.push(r); }); }
  const s = Engine.summarize(tested, exp), all = Engine.summarize(L, exp); return { oos: s, all };
}

/* ---------------- interface ---------------- */
let tab = 'dash', sub = null, hFilter = 'todos', nFilter = 'Todas', cFilter = 'High';
const NAV = [['dash','📊','Painel'],['sig','⚡','Sinais'],['ast','💱','Ativos'],['news','📰','Notícias'],['more','☰','Mais']];
const MORE = [['otc','🏦','Área OTC','Status das fontes OTC'],['cal','📅','Calendário','Eventos econômicos'],['hist','🗂️','Histórico','Todos os sinais'],
  ['stats','📈','Estatísticas','Desempenho e backtest'],['risk','🛡️','Gestão de risco','Paper trading e limites'],['cfg','⚙️','Configurações','Filtros, ativos e chaves']];
function go(t) { tab = t; render(); window.scrollTo(0, 0); }
function renderNav() { const act = DB.signals.filter(s => s.st === 'aguardando' || s.st === 'ativo').length;
  $('#nav').innerHTML = NAV.map(([k, i, l]) => `<button class="${tab === k || (k === 'more' && MORE.some(m => m[0] === tab)) ? 'on' : ''}" onclick="go('${k}')"><i>${i}</i><span>${l}${k === 'sig' && act ? `<span class="badge">${act}</span>` : ''}</span></button>`).join(''); }
const dot = s => `<span class="dot ${s === 'ok' ? 'd-ok' : s === 'bad' ? 'd-bad' : s === 'load' ? 'd-warn' : 'd-off'}"></span>`;
function header(t, back) { return `<div class="hd">${back ? `<button class="back" onclick="go('more')">‹</button>` : ''}<h1>${t}</h1><div class="r">${latBadge()}</div></div>`; }
function latBadge() { const l = Object.entries(RT.lat).filter(([k]) => assetOf(k).src === 'binance').map(([, v]) => v); if (!l.length) return '<span class="tag t-mut">sem dados</span>';
  const m = Math.round(l.reduce((a, b) => a + b, 0) / l.length); return `<span class="tag ${m > CFG.maxLat ? 't-put' : m > 800 ? 't-warn' : 't-call'}" id="latb">⚡ ${m} ms</span>`; }
function render() { renderNav(); const f = { dash, sig, ast, news, more, otc, cal, hist, stats, risk, cfg }[tab]; $('#app').innerHTML = f(); bindAfter(); }
function tickUi() { // atualiza contadores sem redesenhar a tela inteira
  document.querySelectorAll('[data-cd]').forEach(el => { const t = +el.dataset.cd - now(); el.textContent = t > 0 ? `em ${Math.ceil(t / 1000)} s` : 'agora'; });
  const lb = $('#latb'); if (lb) lb.outerHTML = latBadge();
  if (['dash', 'sig', 'ast'].includes(tab) && Date.now() % 5000 < 1000) render();
}

function sigCard(s) {
  const st = { aguardando:['t-warn','AGUARDANDO ENTRADA'], ativo:['t-acc','ATIVO'], concluído: s.res > 0 ? ['t-call','WIN'] : s.res < 0 ? ['t-put','LOSS'] : ['t-mut','EMPATE'], cancelado:['t-mut','CANCELADO'] }[s.st];
  return `<div class="sig ${s.dir === 'CALL' ? 'call' : 'put'}">
    <div class="row btw"><div class="row"><span class="dir ${s.dir === 'CALL' ? 'up' : 'dn'}">${s.dir === 'CALL' ? '▲' : '▼'} ${s.dir}</span><b style="font-size:16px">${esc(s.name)}</b></div><span class="tag ${st[0]}">${st[1]}</span></div>
    <table>
      <tr><td>Mercado</td><td>${s.market} <span class="mut xs">(cotação real)</span></td></tr>
      <tr><td>Expiração</td><td><b>${s.exp} min</b></td></tr>
      <tr><td>Entrada</td><td><b class="mono">${hhmmss(s.entryT)}</b> ${s.st === 'aguardando' ? `<span class="tag t-warn" data-cd="${s.entryT}"></span>` : ''}${s.entry != null ? ` <span class="mut mono">@ ${s.entry}</span>` : ''}</td></tr>
      ${s.st === 'concluído' ? `<tr><td>Saída</td><td class="mono">${hhmmss(s.entryT + s.exp * 60000)} @ ${s.exit}${s.pnl != null ? ` · <b class="${s.pnl >= 0 ? 'up' : 'dn'}">${s.pnl >= 0 ? '+' : ''}${s.pnl.toFixed(2)}</b> (paper)` : ''}</td></tr>` : ''}
      ${s.st === 'cancelado' ? `<tr><td>Motivo</td><td class="mut">${esc(s.cancel)}</td></tr>` : ''}
      <tr><td>Confiança</td><td>${s.conf != null ? `<b>${pct(s.conf)}</b> <span class="mut xs">acerto histórico · IC 95% ${pct(s.ci[0], 0)}–${pct(s.ci[1], 0)} · ${s.calN} sinais (${s.calScope})</span>` : '<span class="tag t-warn">não calibrado</span> <span class="mut xs">histórico insuficiente</span>'}
        <div class="xs mut" style="margin-top:2px">Força do modelo: ${s.score} (nível ${s.bucket}) — não é probabilidade de vitória</div></td></tr>
      <tr><td>Tendência</td><td>${s.trend} <span class="mut xs">· 5m: ${s.trend5} · ADX ${s.adx}</span></td></tr>
      <tr><td>Estratégia</td><td>${s.strat}</td></tr>
      <tr><td>Indicadores</td><td>${s.why.map(w => `<div class="why">✓ ${esc(w)}</div>`).join('')}${s.against.length ? s.against.map(w => `<div class="why mut">✗ ${esc(w)}</div>`).join('') : ''}</td></tr>
      <tr><td>Notícias</td><td>${s.news.length ? s.news.map(n => `<div class="why">• ${esc(n)}</div>`).join('') : '<span class="mut">nenhum evento relevante próximo</span>'}</td></tr>
      <tr><td>Registro</td><td class="xs mut mono">gerado ${hhmmss(s.gen)} · recebido ${hhmmss(s.recv)} · latência dos dados ${s.lat} ms</td></tr>
    </table></div>`;
}

function dash() {
  const act = DB.signals.filter(s => s.st === 'aguardando' || s.st === 'ativo'), d = done(), r = rate(d), td = todaySignals();
  const conns = [['Binance (cripto)', 'binance'], ['Twelve Data (forex)', 'twelve'], ['Notícias', 'news'], ['Calendário', 'cal'], ['Relógio', 'clock']];
  return `<div class="scr">${header('SinaisPro')}
    <div class="g4" style="margin-bottom:10px">
      <div class="kv"><span>Ativos</span><b>${act.length}</b></div><div class="kv"><span>Hoje</span><b>${td.length}</b></div>
      <div class="kv"><span>Acerto real</span><b class="${r.rate != null && r.rate >= breakeven() ? 'up' : ''}">${r.n ? pct(r.rate, 0) : '—'}</b></div><div class="kv"><span>Analisadas</span><b>${RT.analyzed}</b></div></div>
    <div class="card"><h2>Conexões <small>modo ${CFG.mode}</small></h2>
      ${conns.map(([n, k]) => `<div class="row btw" style="padding:4px 0"><span class="row">${dot(RT.conn[k])} ${n}</span><span class="sm mut">${esc(RT.connMsg[k] || (RT.conn[k] === 'off' ? 'desativado' : ''))}</span></div>`).join('')}
      <div class="row btw" style="padding:4px 0"><span class="row">${dot('off')} OTC</span><span class="sm mut">indisponível (ver Área OTC)</span></div></div>
    <div class="card"><h2>Sinais em andamento</h2>${act.length ? act.map(sigCard).join('') : `<div class="empty">Nenhum sinal agora. O app só avisa quando os critérios do modo <b>${CFG.mode}</b> são atingidos.</div>`}</div>
    <div class="card"><h2>Últimos sinais <small><a onclick="go('hist')" style="color:var(--acc)">ver todos</a></small></h2>${miniList(DB.signals.slice(-6).reverse())}</div>
    <div class="card"><h2>Paper trading <small>simulação, sem dinheiro real</small></h2><div class="g3">
      <div class="kv"><span>Saldo</span><b>${DB.bal.toFixed(2)}</b></div><div class="kv"><span>Resultado hoje</span><b class="${todayLoss() >= 0 ? 'up' : 'dn'}">${todayLoss().toFixed(2)}</b></div>
      <div class="kv"><span>Ponto de equilíbrio</span><b>${pct(breakeven())}</b></div></div></div>
    <div class="card"><h2>Desempenho por ativo</h2>${perfTable(groupBy(d, s => s.name))}</div>
    <div class="card"><h2>Desempenho por expiração</h2>${perfTable(groupBy(d, s => s.exp + ' min'))}</div>
    ${disclaimer()}</div>`;
}
function miniList(l) { return l.length ? l.map(s => `<div class="row btw" style="padding:7px 0;border-top:1px solid var(--line)"><span class="row"><b class="${s.dir === 'CALL' ? 'up' : 'dn'}">${s.dir === 'CALL' ? '▲' : '▼'}</b> ${esc(s.name)} <span class="mut sm">${s.exp}m · ${hhmm(s.entryT)}</span></span>
  <span class="tag ${s.st === 'concluído' ? (s.res > 0 ? 't-call' : s.res < 0 ? 't-put' : 't-mut') : s.st === 'cancelado' ? 't-mut' : 't-acc'}">${s.st === 'concluído' ? (s.res > 0 ? 'WIN' : s.res < 0 ? 'LOSS' : 'EMPATE') : s.st.toUpperCase()}</span></div>`).join('') : '<div class="empty">Nenhum sinal ainda.</div>'; }
function perfTable(g) { if (!g.length) return '<div class="empty">Sem sinais concluídos ainda.</div>'; const be = breakeven();
  return `<table class="t"><tr><th>Grupo</th><th>Sinais</th><th>Acerto</th><th>IC 95%</th></tr>${g.map(x => `<tr><td>${esc(x.k)}</td><td>${x.n}</td><td class="${x.rate >= be ? 'up' : 'dn'}">${pct(x.rate)}</td><td class="mut">${pct(x.ci[0], 0)}–${pct(x.ci[1], 0)}</td></tr>`).join('')}</table>`; }

function sig() {
  const act = DB.signals.filter(s => s.st === 'aguardando' || s.st === 'ativo'), recent = DB.signals.filter(s => s.st === 'concluído' || s.st === 'cancelado').slice(-10).reverse();
  return `<div class="scr">${header('Sinais ao vivo')}
    <div class="card"><h2>Em andamento <small>${act.length}</small></h2>${act.length ? act.map(sigCard).join('') : '<div class="empty">Nenhum sinal agora.</div>'}</div>
    <div class="card"><h2>Por que não há sinal?</h2>${enabled().map(a => { const r = RT.reasons[a.id]; return `<div class="row btw" style="padding:6px 0;border-top:1px solid var(--line);align-items:flex-start"><b style="flex:none">${a.name}</b><span class="sm mut" style="text-align:right">${r && r.length ? esc(r.join(' · ')) : 'monitorando — critérios ainda não atingidos'}</span></div>`; }).join('') || '<div class="empty">Nenhum ativo ativado.</div>'}</div>
    <div class="card"><h2>Concluídos recentemente</h2>${recent.length ? recent.map(sigCard).join('') : '<div class="empty">Nada ainda.</div>'}</div></div>`;
}

function ast() {
  return `<div class="scr">${header('Ativos')}
    ${ASSETS.map(a => { const on = CFG.assets[a.id], C = RT.C[a.id], L = RT.live[a.id], lr = RT.last && RT.last[a.id];
      const need = a.src === 'twelve' && !CFG.tdKey;
      let body = '';
      if (on && C && C.length > 60) { Engine.setDec(a.dec); const P = lr ? lr.P : Engine.prepare(C), i = C.length - 1, p = L ? L.p : C[i].c, ch = (p / C[Math.max(0, i - 60)].c - 1) * 100;
        const e9 = P.e9[i], e21 = P.e21[i], e50 = P.e50[i], tr = P.adx.adx[i] < 20 ? 'Lateral' : e9 > e21 && e21 > e50 ? 'Alta' : e9 < e21 && e21 < e50 ? 'Baixa' : 'Indefinida';
        const wf = RT.bt[a.id] ? walkForward(a.id, CFG.mode, 2) : null;
        body = `<div class="g4" style="margin-top:9px"><div class="kv"><span>Preço</span><b class="mono" style="font-size:14px">${p.toFixed(a.dec)}</b></div><div class="kv"><span>1 hora</span><b class="${ch >= 0 ? 'up' : 'dn'}" style="font-size:14px">${ch >= 0 ? '+' : ''}${ch.toFixed(2)}%</b></div>
          <div class="kv"><span>RSI</span><b style="font-size:14px">${P.rsi[i] ? P.rsi[i].toFixed(0) : '—'}</b></div><div class="kv"><span>ADX</span><b style="font-size:14px">${P.adx.adx[i] ? P.adx.adx[i].toFixed(0) : '—'}</b></div></div>
          <div class="row wrap" style="margin-top:8px;gap:6px"><span class="tag ${tr === 'Alta' ? 't-call' : tr === 'Baixa' ? 't-put' : 't-mut'}">Tendência: ${tr}</span>
          <span class="tag t-mut">${RT.lat[a.id] != null ? (a.src === 'binance' ? RT.lat[a.id] + ' ms' : 'vela +' + Math.round(RT.lat[a.id] / 1000) + ' s') : 'aguardando dados'}</span>
          ${wf ? `<span class="tag t-acc">walk-forward 2m: ${wf.oos.n ? pct(wf.oos.rate) + ' (' + wf.oos.n + ')' : 'sem sinais qualificados'}</span>` : ''}</div>`; }
      else if (on && need) body = `<div class="sm mut" style="margin-top:8px">Adicione a chave da Twelve Data em Configurações.</div>`;
      else if (on) body = `<div class="sm mut" style="margin-top:8px">Carregando dados…</div>`;
      return `<div class="card"><div class="row btw"><div><b style="font-size:15px">${a.name}</b> <span class="tag t-mut">${a.src === 'binance' ? 'Cripto · Binance' : 'Forex · Twelve Data'}</span>
        ${!marketOpen(a) ? '<span class="tag t-warn">fechado</span>' : ''}</div><button class="tog ${on ? 'on' : ''}" onclick="toggleAsset('${a.id}')"></button></div>${body}</div>`; }).join('')}
  </div>`;
}
function toggleAsset(id) { CFG.assets[id] = !CFG.assets[id]; saveCfg(); render(); restartData(); }

function news() {
  const cs = ['Todas', 'USD', 'EUR', 'GBP', 'JPY', 'CRYPTO', 'XAU', 'Alto impacto'];
  const L = RT.news.filter(n => nFilter === 'Todas' || (nFilter === 'Alto impacto' ? n.impact === 'Alto' : n.ccy.includes(nFilter))).slice(0, 80);
  return `<div class="scr">${header('Notícias mundiais')}
    <div class="chips">${cs.map(c => `<button class="chip ${c === nFilter ? 'on' : ''}" onclick="nFilter='${c}';render()">${c}</button>`).join('')}</div>
    <div class="card note" style="padding:10px 12px">Classificação automática por palavras-chave (moedas afetadas e peso do tema). Notícia <b>não</b> é usada como confirmação de entrada — só para bloquear sinais perto de eventos de risco.</div>
    <div class="card">${L.length ? L.map(n => `<div class="news"><a href="${esc(n.link)}">${esc(n.title)}</a>
      <div class="row wrap" style="gap:5px;margin-top:5px"><span class="xs mut">${esc(n.src)} · ${n.date ? new Date(n.date).toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' }) : 'sem data'}</span>
      <span class="tag ${n.impact === 'Alto' ? 't-put' : n.impact === 'Médio' ? 't-warn' : 't-mut'}">impacto ${n.impact.toLowerCase()}</span>${n.ccy.map(c => `<span class="tag t-acc">${c}</span>`).join('')}${n.topics.map(c => `<span class="tag t-mut">${c}</span>`).join('')}</div></div>`).join('')
      : `<div class="empty">${RT.conn.news === 'load' ? 'Carregando…' : 'Nenhuma notícia.'}</div>`}</div>
    <div class="card"><h2>Fontes</h2>${NEWS_FEEDS.map(f => `<div class="row btw sm" style="padding:3px 0"><span class="row">${dot(RT.feeds[f.name] === 'ok' ? 'ok' : RT.feeds[f.name] ? 'bad' : 'off')} ${f.name}</span><span class="mut xs">${RT.feeds[f.name] === 'ok' ? 'ok' : esc(RT.feeds[f.name] || '')}</span></div>`).join('')}
      <p class="xs mut" style="margin-top:8px">Reuters, Bloomberg e Financial Times não oferecem feed gratuito (licença paga).</p>
      <button class="btn s" style="margin-top:8px" onclick="loadNews()">Atualizar</button></div></div>`;
}
function more() { return `<div class="scr">${header('Mais')}<div class="menu">${MORE.map(([k, i, t, d]) => `<button onclick="go('${k}')"><i>${i}</i><b>${t}</b><span>${d}</span></button>`).join('')}</div>${disclaimer()}</div>`; }
function otc() {
  return `<div class="scr">${header('Área OTC', 1)}
    <div class="errbox"><b>Fonte OTC indisponível — sinais OTC desativados.</b></div><div style="height:10px"></div>
    <div class="card note">As cotações OTC (fins de semana e fora do horário) são <b>geradas pela própria corretora</b> e não seguem o mercado interbancário. Nenhuma corretora de opções binárias oferece API pública ou fonte de dados independente para esses preços.<br><br>
      Usar cotações do Forex real como se fossem OTC daria sinais falsos, então este app <b>não gera sinais OTC</b>. Se no futuro uma corretora disponibilizar uma API oficial com histórico OTC, ela pode ser conectada aqui.</div>
    <div class="card"><h2>Status</h2><div class="row btw"><span class="row">${dot('off')} Fonte de dados OTC</span><span class="sm mut">nenhuma disponível</span></div>
      <div class="row btw" style="margin-top:6px"><span class="row">${dot(forexOpen() ? 'ok' : 'bad')} Mercado forex normal</span><span class="sm mut">${forexOpen() ? 'aberto' : 'fechado (corretoras costumam oferecer só OTC agora)'}</span></div></div></div>`;
}
function cal() {
  const L = RT.cal.filter(e => cFilter === 'Todos' || e.impact === cFilter), t = now();
  return `<div class="scr">${header('Calendário econômico', 1)}
    <div class="chips">${[['High','Alto impacto'],['Medium','Médio'],['Todos','Todos']].map(([k, l]) => `<button class="chip ${k === cFilter ? 'on' : ''}" onclick="cFilter='${k}';render()">${l}</button>`).join('')}</div>
    <div class="card note" style="padding:10px 12px">Sinais ficam bloqueados ${CFG.newsBlock} min antes e depois de eventos de <b>alto impacto</b> das moedas do ativo.</div>
    <div class="card">${L.length ? L.map(e => `<div class="row btw" style="padding:8px 0;border-top:1px solid var(--line);opacity:${e.t < t - 3600000 ? .5 : 1}">
      <div style="min-width:0"><div class="b sm">${esc(e.title)}</div><div class="xs mut">${new Date(e.t).toLocaleString('pt-BR', { weekday:'short', day:'2-digit', hour:'2-digit', minute:'2-digit' })} ${e.fc ? '· previsão ' + esc(e.fc) : ''} ${e.prev ? '· anterior ' + esc(e.prev) : ''}</div></div>
      <div class="row" style="flex:none"><span class="tag t-acc">${esc(e.ccy)}</span><span class="tag ${e.impact === 'High' ? 't-put' : e.impact === 'Medium' ? 't-warn' : 't-mut'}">${e.impact === 'High' ? 'Alto' : e.impact === 'Medium' ? 'Médio' : e.impact === 'Low' ? 'Baixo' : esc(e.impact)}</span></div></div>`).join('')
      : `<div class="empty">${RT.conn.cal === 'bad' ? 'Calendário indisponível: ' + esc(RT.connMsg.cal) : 'Carregando…'}</div>`}</div>
    <p class="xs mut" style="padding:0 4px">Fonte: calendário semanal do Forex Factory.</p></div>`;
}
function hist() {
  const f = { todos: () => true, win: s => s.res > 0, loss: s => s.res < 0, cancel: s => s.st === 'cancelado' }[hFilter];
  const L = DB.signals.filter(f).slice().reverse();
  return `<div class="scr">${header('Histórico', 1)}
    <div class="chips">${[['todos','Todos'],['win','Wins'],['loss','Losses'],['cancel','Cancelados']].map(([k, l]) => `<button class="chip ${k === hFilter ? 'on' : ''}" onclick="hFilter='${k}';render()">${l}</button>`).join('')}</div>
    <div class="card"><h2>${L.length} sinais <button class="btn s" onclick="exportCsv()">Exportar CSV</button></h2>
      ${L.length ? `<table class="t"><tr><th>Data</th><th>Ativo</th><th>Dir</th><th>Exp</th><th>Conf.</th><th>Res.</th></tr>
      ${L.slice(0, 300).map(s => `<tr><td class="xs">${new Date(s.entryT).toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' })}</td><td>${esc(s.name)}</td><td class="${s.dir === 'CALL' ? 'up' : 'dn'}">${s.dir}</td><td>${s.exp}m</td><td>${s.conf != null ? pct(s.conf, 0) : '—'}</td>
        <td><span class="tag ${s.res > 0 ? 't-call' : s.res < 0 ? 't-put' : 't-mut'}">${s.st === 'concluído' ? (s.res > 0 ? 'WIN' : s.res < 0 ? 'LOSS' : '=') : s.st === 'cancelado' ? 'canc.' : '…'}</span></td></tr>`).join('')}</table>` : '<div class="empty">Nenhum sinal.</div>'}</div></div>`;
}
function exportCsv() {
  const rows = [['gerado', 'entrada', 'ativo', 'mercado', 'direcao', 'expiracao_min', 'modo', 'estrategia', 'forca', 'confianca_hist', 'n_calib', 'preco_entrada', 'preco_saida', 'status', 'resultado', 'pnl_paper', 'latencia_ms']]
    .concat(DB.signals.map(s => [new Date(s.gen).toISOString(), new Date(s.entryT).toISOString(), s.name, s.market, s.dir, s.exp, s.mode, s.strat, s.score, s.conf != null ? s.conf.toFixed(4) : '', s.calN, s.entry ?? '', s.exit ?? '', s.st, s.res ?? '', s.pnl ?? '', s.lat]));
  const csv = rows.map(r => r.join(';')).join('\n');
  if (window.AndroidApp && AndroidApp.share) AndroidApp.share('Histórico SinaisPro', csv); else toast('Exportação disponível no app Android');
}
function stats() {
  const d = done(), r = rate(d), be = breakeven(), det = deterioration();
  const sel = RT.statAsset || (enabled()[0] || {}).id;
  const wf = sel && RT.bt[sel] ? [1, 2, 5].map(e => ({ e, ...walkForward(sel, CFG.mode, e) })) : null;
  return `<div class="scr">${header('Estatísticas', 1)}
    <div class="card"><h2>Sinais reais concluídos</h2><div class="g3">
      <div class="kv"><span>Sinais</span><b>${r.n}</b></div><div class="kv"><span>Acerto</span><b class="${r.rate >= be ? 'up' : 'dn'}">${pct(r.rate)}</b></div><div class="kv"><span>Equilíbrio</span><b>${pct(be)}</b></div></div>
      <p class="xs mut" style="margin-top:8px">${r.n ? `Intervalo de confiança 95%: ${pct(r.ci[0])} a ${pct(r.ci[1])}. ` : ''}Com payout de ${CFG.payout}%, é preciso acertar mais de ${pct(be)} só para empatar.${r.n && r.n < 100 ? ' Com menos de 100 sinais o resultado ainda é muito incerto.' : ''}</p>
      ${det ? `<div class="${det.bad ? 'errbox' : 'note'}" style="margin-top:8px">${det.bad ? '⚠️ <b>Deterioração detectada:</b> ' : 'Estabilidade: '}últimos 30 sinais ${pct(det.recent.rate)} × anteriores ${pct(det.before.rate)}.</div>` : ''}</div>
    <div class="card"><h2>Por ativo</h2>${perfTable(groupBy(d, s => s.name))}</div>
    <div class="card"><h2>Por expiração</h2>${perfTable(groupBy(d, s => s.exp + ' min'))}</div>
    <div class="card"><h2>Por estratégia</h2>${perfTable(groupBy(d, s => s.strat))}</div>
    <div class="card"><h2>Por horário</h2>${perfTable(groupBy(d, s => String(new Date(s.entryT).getHours()).padStart(2, '0') + 'h'))}</div>
    <div class="card"><h2>Backtest walk-forward <small>modo ${CFG.mode}</small></h2>
      <div class="chips">${enabled().filter(a => RT.bt[a.id]).map(a => `<button class="chip ${a.id === sel ? 'on' : ''}" onclick="RT.statAsset='${a.id}';render()">${a.name}</button>`).join('')}</div>
      ${wf ? `<table class="t"><tr><th>Expiração</th><th>Todos os sinais</th><th>Fora da amostra*</th></tr>${wf.map(x => `<tr><td>${x.e} min</td><td>${x.all.n ? pct(x.all.rate) + ' <span class="mut xs">(' + x.all.n + ')</span>' : '—'}</td>
        <td class="${x.oos.rate >= be ? 'up' : x.oos.n ? 'dn' : ''}">${x.oos.n ? pct(x.oos.rate) + ' <span class="mut xs">(' + x.oos.n + ')</span>' : 'sem sinais qualificados'}</td></tr>`).join('')}</table>
        <p class="xs mut" style="margin-top:8px">*Walk-forward: o histórico de ~1000 minutos é dividido em 5 blocos; a confiança é calibrada só com os blocos anteriores e testada no bloco seguinte (sem usar dados futuros). Amostras pequenas: use como indicação, não como garantia.</p>`
      : '<div class="empty">Aguardando histórico dos ativos.</div>'}</div></div>`;
}
function risk() {
  return `<div class="scr">${header('Gestão de risco', 1)}
    <div class="card"><h2>Paper trading <small>conta simulada</small></h2><div class="g2">
      <div class="kv"><span>Saldo simulado</span><b>${DB.bal.toFixed(2)}</b></div><div class="kv"><span>Resultado hoje</span><b class="${todayLoss() >= 0 ? 'up' : 'dn'}">${todayLoss().toFixed(2)}</b></div></div>
      <div class="sw" style="margin-top:8px"><span>Registrar todos os sinais no paper trading</span><button class="tog ${CFG.paperAuto ? 'on' : ''}" onclick="CFG.paperAuto=!CFG.paperAuto;saveCfg();render()"></button></div>
      <button class="btn d" style="margin-top:6px" onclick="DB.bal=CFG.paperStart;saveDb();render();toast('Saldo simulado reiniciado')">Reiniciar saldo simulado (${CFG.paperStart})</button></div>
    <div class="card"><h2>Parâmetros</h2>
      <div class="g2"><label class="f"><span>Payout da corretora (%)</span><input id="rPay" inputmode="numeric" value="${CFG.payout}"></label><label class="f"><span>Valor por entrada</span><input id="rStake" inputmode="decimal" value="${CFG.stake}"></label>
      <label class="f"><span>Perda máxima por dia</span><input id="rLoss" inputmode="decimal" value="${CFG.dailyMaxLoss}"></label><label class="f"><span>Máx. sinais por dia</span><input id="rMax" inputmode="numeric" value="${CFG.maxDay}"></label></div>
      <button class="btn p" onclick="saveRisk()">Salvar</button>
      <p class="xs mut" style="margin-top:8px">Ao atingir a perda máxima ou o número máximo de sinais do dia, o app para de gerar sinais até o dia seguinte.</p></div>
    <div class="card"><h2>A conta que importa</h2><p class="note">Com payout de <b>${CFG.payout}%</b>, você ganha ${CFG.payout} a cada 100 apostados quando acerta e perde 100 quando erra. Para não perder dinheiro, a taxa de acerto precisa ficar acima de <b>${pct(breakeven())}</b> por muitas operações seguidas. Acompanhe isso no paper trading por várias semanas antes de arriscar dinheiro real.</p></div>
    <div class="warnbox"><b>Aviso legal:</b> opções binárias são proibidas para investidores pessoa física na União Europeia (inclusive França) e no Reino Unido, e no Brasil nenhuma corretora de opções binárias é autorizada pela CVM. Verifique a lei do seu país. Este app não executa operações nem se conecta a corretoras.</div></div>`;
}
function saveRisk() { const n = id => parseFloat(String($(id).value).replace(',', '.'));
  const p = n('#rPay'), s = n('#rStake'), l = n('#rLoss'), m = n('#rMax');
  if (!(p > 0 && p <= 100 && s > 0 && l > 0 && m > 0)) return toast('Valores inválidos');
  Object.assign(CFG, { payout: p, stake: s, dailyMaxLoss: l, maxDay: Math.round(m) }); saveCfg(); render(); toast('Gestão de risco salva'); }
function cfg() {
  return `<div class="scr">${header('Configurações', 1)}
    <div class="card"><h2>Filtro de qualidade</h2>
      <div class="seg">${Object.keys(Engine.MODES).map(m => `<button class="${CFG.mode === m ? 'on' : ''}" onclick="CFG.mode='${m}';saveCfg();render()">${m[0].toUpperCase() + m.slice(1)}</button>`).join('')}</div>
      <p class="xs mut" style="margin:8px 0 12px">${{ conservador:'Exige força ≥ 5 e pelo menos 4 grupos de indicadores concordando. Poucos sinais.', moderado:'Força ≥ 3,5 e 3 grupos concordando.', agressivo:'Força ≥ 2,5 e 2 grupos. Mais sinais, risco elevado.' }[CFG.mode]}</p>
      <label class="f"><span>Acerto histórico mínimo: <b id="mcv">${CFG.minConf}%</b> (equilíbrio: ${pct(breakeven())})</span><input type="range" min="50" max="70" value="${CFG.minConf}" oninput="$('#mcv').textContent=this.value+'%'" onchange="CFG.minConf=+this.value;saveCfg()"></label>
      <div class="sw"><span class="sm">Permitir sinais ainda não calibrados</span><button class="tog ${CFG.allowUncal ? 'on' : ''}" onclick="CFG.allowUncal=!CFG.allowUncal;saveCfg();render()"></button></div>
      <label class="f" style="margin-top:8px"><span>Expiração</span><div class="seg">${[['auto','Automática'],['1','1 min'],['2','2 min'],['5','5 min']].map(([k, l]) => `<button class="${CFG.expPref === k ? 'on' : ''}" onclick="CFG.expPref='${k}';saveCfg();render()">${l}</button>`).join('')}</div></label>
      <p class="xs mut">Automática: escolhe a expiração com melhor desempenho histórico (limite inferior do intervalo de confiança) para aquele ativo.</p></div>
    <div class="card"><h2>Forex — Twelve Data</h2>
      <p class="note" style="margin-bottom:8px">Crie uma chave gratuita em twelvedata.com (plano Basic: 8 consultas/min, 800/dia). Cada par ativado consome ~1 consulta por minuto, então o gratuito acompanha 1 par por cerca de 13 h/dia. Para mais pares, é preciso um plano pago.</p>
      <label class="f"><span>Chave da API</span><input id="tdk" value="${esc(CFG.tdKey)}" placeholder="cole sua chave aqui" autocomplete="off"></label>
      <button class="btn p" onclick="CFG.tdKey=$('#tdk').value.trim();saveCfg();restartData();toast('Chave salva')">Salvar chave</button></div>
    <div class="card"><h2>Alertas e conexão</h2>
      <div class="sw"><span class="sm">Notificações de sinais</span><button class="tog ${CFG.notif ? 'on' : ''}" onclick="CFG.notif=!CFG.notif;saveCfg();render()"></button></div>
      <div class="sw"><span class="sm">Manter a tela ligada (monitoramento contínuo)</span><button class="tog ${CFG.keepOn ? 'on' : ''}" onclick="CFG.keepOn=!CFG.keepOn;saveCfg();applyKeep();render()"></button></div>
      <div class="g2" style="margin-top:8px"><label class="f"><span>Bloqueio por notícia (min)</span><input id="cNB" inputmode="numeric" value="${CFG.newsBlock}"></label><label class="f"><span>Latência máxima (ms)</span><input id="cML" inputmode="numeric" value="${CFG.maxLat}"></label></div>
      <button class="btn" onclick="CFG.newsBlock=Math.max(0,parseInt($('#cNB').value)||15);CFG.maxLat=Math.max(200,parseInt($('#cML').value)||2000);saveCfg();toast('Salvo')">Salvar</button>
      <p class="xs mut" style="margin-top:8px">O monitoramento roda com o app aberto. Com a tela apagada, o Android pode pausar a conexão.</p></div>
    <div class="card"><h2>Dados</h2><button class="btn d" onclick="if(this.dataset.c){DB.signals=[];DB.bal=CFG.paperStart;saveDb();render();toast('Histórico apagado')}else{this.dataset.c=1;this.textContent='Toque de novo para confirmar'}">Apagar histórico de sinais</button></div>
    <div class="card"><h2>Registro de eventos</h2>${DB.log.slice(-15).reverse().map(l => `<div class="xs mut mono">${hhmmss(l.t)} ${esc(l.m)}</div>`).join('') || '<div class="empty">Vazio.</div>'}</div></div>`;
}
function disclaimer() { return `<p class="xs mut" style="text-align:center;padding:8px 10px;line-height:1.5">Análise estatística, sem garantia de resultado. Confiança do modelo ≠ probabilidade real de vitória. O app não executa operações. Use o paper trading.</p>`; }
function bindAfter() {}
function applyKeep() { if (window.AndroidApp && AndroidApp.keepScreen) AndroidApp.keepScreen(!!CFG.keepOn); }

/* ---------------- inicialização ---------------- */
let started = false;
async function restartData() { await loadBinance(); loadTwelve(); }
window.onBack = () => { if (MORE.some(m => m[0] === tab)) { go('more'); return true; } if (tab !== 'dash') { go('dash'); return true; } return false; };
async function start() {
  render(); applyKeep();
  await syncClock(); setInterval(syncClock, 10 * 60000);
  loadCal(); loadNews(); setInterval(loadNews, 10 * 60000); setInterval(loadCal, 60 * 60000);
  await restartData(); render();
}
start();
