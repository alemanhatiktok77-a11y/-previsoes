import random

from app.core.models import Candle


def random_walk(n=1500, seed=1, start=100.0, vol=0.0008, drift=0.0, t0=1_700_000_040_000 // 60_000 * 60_000, volume=True):
    rnd = random.Random(seed)
    p, out = start, []
    for i in range(n):
        o = p
        h = l = o
        for _ in range(6):
            p *= 1 + (rnd.random() - 0.5) * vol + drift
            h, l = max(h, p), min(l, p)
        out.append(Candle(t0 + i * 60_000, o, h, l, p, rnd.uniform(5, 50) if volume else 0.0))
    return out


class FakeProvider:
    source_id = "binance"

    def __init__(self, connected=True):
        self.connected = connected
        self.last_event_ms = {}
        self.latency_ms = {}
        self.last_error = ""
