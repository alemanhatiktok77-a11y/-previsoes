"""Verificação com dados REAIS da Kraken (roda no CI). Não usa conta nem chave.

1. Relógio do servidor
2. Histórico OHLC (15 min e 60 min) de BTC/ETH/SOL em EUR
3. WebSocket v2 ao vivo: mensagens, latência e fechamento de vela
4. Backtest com taxas + walk-forward em dados reais
"""
import asyncio
import json
import sys
import time

sys.path.insert(0, ".")
import httpx  # noqa: E402

from app.data.providers import KrakenProvider, kraken_assets  # noqa: E402
from app.spot import engine as sp  # noqa: E402


def pct(x):
    return "—" if x is None else f"{x * 100:+.2f}%"


async def main():
    out = []
    p = print
    async with httpx.AsyncClient(timeout=20) as cli:
        t0 = time.time()
        j = (await cli.get("https://api.kraken.com/0/public/Time")).json()
        rtt = (time.time() - t0) * 1000
        off = j["result"]["unixtime"] * 1000 - (t0 * 1000 + rtt / 2)
        p(f"## Relógio\nservidor Kraken OK · ida e volta {rtt:.0f} ms · diferença ~{off:.0f} ms (resolução de 1 s)\n")

    p("## Backtest com dados reais (taxa 0,40% por lado, stop 1,5×ATR, alvo 2,5×ATR, máx. 16 velas)\n")
    p("| Ativo | Velas | Período | Operações | Acerto | Média líquida | Média bruta | Soma líquida | Stop/Alvo/Tempo | Walk-forward (fora da amostra) |")
    p("|---|---|---|---|---|---|---|---|---|---|")
    totals = []
    for interval in (15, 60):
        prov = KrakenProvider(interval)
        for a in kraken_assets():
            try:
                C = await prov.history(a, 720)
            except Exception as e:
                p(f"| {a.display} {interval}m | erro: {e} |"); continue
            res = sp.simulate_spot(C, sp.SpotConfig())
            s = sp.summary(res)
            wf = sp.walk_forward_spot(res, min_n=10)
            days = (C[-1].t - C[0].t) / 86_400_000
            totals.append((f"{a.display} {interval}m", s, wf))
            br = s.get("by_reason", {})
            p(f"| {a.display} {interval}m | {len(C)} | {days:.1f} dias | {s['n']} | {pct(s.get('win_rate')) if s['n'] else '—'} | {pct(s.get('mean_pct'))} | {pct(s.get('mean_gross_pct'))} | "
              f"{pct(s.get('total_pct'))} | {br.get('stop', 0)}/{br.get('alvo', 0)}/{br.get('tempo', 0)} | "
              f"{wf['tested']} ops, média {pct(wf['mean_pct'])} |")

    p("\n## WebSocket v2 ao vivo (75 s, velas de 1 min)\n")
    prov = KrakenProvider(1)
    stop = asyncio.Event()
    stats = {"updates": 0, "closed": [], "lat": []}

    async def cb(sym, c, closed, ts):
        stats["updates"] += 1
        if not closed and sym in prov.latency_ms:
            stats["lat"].append(prov.latency_ms[sym])
        if closed:
            stats["closed"].append((sym, c.t, c.c))

    task = asyncio.create_task(prov.stream(kraken_assets(), cb, stop))
    await asyncio.sleep(75)
    stop.set()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    L = sorted(stats["lat"])
    p(f"conectado: {prov.last_error or 'sim'} · reconexões {prov.reconnects} · atualizações recebidas {stats['updates']}")
    if L:
        p(f"latência (horário do evento na Kraken → recebido): mediana {L[len(L) // 2]} ms · p90 {L[int(len(L) * 0.9)]} ms · máx {L[-1]} ms")
    p("(o relógio do runner do GitHub pode ter desvio; a latência é medida entre o horário do negócio na Kraken e a chegada)")
    p(f"velas fechadas detectadas: {len(stats['closed'])} → " + ", ".join(f"{s} {time.strftime('%H:%M', time.gmtime(t / 1000))} {c}" for s, t, c in stats["closed"][:6]))
    ok = stats["updates"] > 0
    p("\nRESULTADO: " + ("OK — API REST e WebSocket da Kraken funcionando com o código do robô" if ok else "FALHA no WebSocket"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
