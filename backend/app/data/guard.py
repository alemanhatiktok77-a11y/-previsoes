"""DataGuard — valida os dados antes de qualquer decisão."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.models import Asset, MarketType


@dataclass
class GuardConfig:
    max_latency_ms: int = 2000          # fontes em tempo real (WebSocket)
    max_bar_delay_ms: int = 90_000      # fontes por sondagem (vela fechada há no máximo 90 s)
    max_silence_ms: int = 20_000        # sem eventos por mais que isso = conexão suspeita
    min_history: int = 200


def forex_open(ts_ms: int) -> bool:
    import datetime as dt
    d = dt.datetime.fromtimestamp(ts_ms / 1000, dt.timezone.utc)
    wd, h = d.weekday(), d.hour   # segunda=0 … domingo=6
    if wd == 5:
        return False
    if wd == 4 and h >= 21:
        return False
    if wd == 6 and h < 21:
        return False
    return True


class DataGuard:
    def __init__(self, cfg: GuardConfig | None = None):
        self.cfg = cfg or GuardConfig()

    def check(self, asset: Asset, provider, history_len: int, now_ms: int, otc_registry=None) -> list:
        """Retorna a lista de motivos de bloqueio (vazia = dados válidos)."""
        r = []
        if asset.market == MarketType.OTC:
            if otc_registry is None or otc_registry.provider_for(asset) is None:
                return ["sem fonte OTC confiável — operação bloqueada"]
        if provider is None:
            return ["provedor de dados não configurado"]
        if provider.source_id != asset.source_id:
            return [f"fonte divergente ({provider.source_id} ≠ {asset.source_id})"]
        if not provider.connected:
            r.append("conexão com a fonte indisponível")
        last = provider.last_event_ms.get(asset.symbol)
        if last is None:
            r.append("nenhum dado ao vivo recebido")
        elif now_ms - last > self.cfg.max_silence_ms and provider.source_id in ("binance", "kraken"):
            r.append(f"sem dados há {(now_ms - last) // 1000} s")
        lat = provider.latency_ms.get(asset.symbol)
        limit = self.cfg.max_latency_ms if provider.source_id in ("binance", "kraken") else self.cfg.max_bar_delay_ms
        if lat is not None and lat > limit:
            r.append(f"dados atrasados ({lat} ms)")
        if history_len < self.cfg.min_history:
            r.append(f"histórico insuficiente ({history_len} velas)")
        if "CRYPTO" not in asset.currencies and not forex_open(now_ms):
            r.append("mercado fechado")
        return r
