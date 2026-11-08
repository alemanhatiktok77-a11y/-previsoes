"""NEWS ENGINE — coleta RSS públicos + calendário econômico e classifica cada notícia.

Classificação por regras (PT/EN) — transparente e testável. Não é usada como sinal de
entrada; serve para (1) informar o usuário e (2) bloquear operações perto de eventos de risco.
Reuters, Bloomberg e Financial Times não oferecem feeds gratuitos (exigem licença paga).
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Optional

from app.core.models import Asset, NewsItem

FEEDS = [
    # (nome, url, confiabilidade, moeda do banco central)
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", 1.0, "USD"),
    ("Banco Central Europeu", "https://www.ecb.europa.eu/rss/press.html", 1.0, "EUR"),
    ("Banco da Inglaterra", "https://www.bankofengland.co.uk/rss/news", 1.0, "GBP"),
    ("CNBC Economia", "https://www.cnbc.com/id/20910258/device/rss/rss.html", 0.8, None),
    ("CNBC Mercados", "https://www.cnbc.com/id/15839069/device/rss/rss.html", 0.8, None),
    ("FXStreet", "https://www.fxstreet.com/rss/news", 0.7, None),
    ("Investing.com", "https://www.investing.com/rss/news_1.rss", 0.7, None),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", 0.7, None),
]
CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

CCY = {
    "USD": r"\b(fed|fomc|powell|federal reserve|u\.s\.|united states|treasury|nonfarm|payrolls?|wall street|dollar|d[oó]lar|eua|estados unidos)\b",
    "EUR": r"\b(ecb|bce|lagarde|euro ?zone|euro area|zona do euro|germany|alemanha|france|fran[cç]a|italy|it[aá]lia)\b",
    "GBP": r"\b(boe|bank of england|bailey|britain|british|reino unido|sterling|pound|libra)\b",
    "JPY": r"\b(boj|bank of japan|ueda|japan|jap[aã]o|yen|iene)\b",
    "CRYPTO": r"\b(bitcoin|btc|ether(eum)?|crypto|cripto|solana|stablecoin|crypto etf)\b",
}
TOPICS = {
    "Juros": (r"\b(interest rates?|rate (hike|cut|decision)|raises rates|cuts rates|juros|taxa b[aá]sica|selic)\b", 1.0),
    "Inflação": (r"\b(inflation|infla[cç][aã]o|cpi|pce|consumer prices|pre[cç]os ao consumidor)\b", 0.9),
    "Emprego": (r"\b(payrolls?|jobs report|employment|unemployment|jobless|emprego|desemprego)\b", 0.9),
    "Política monetária": (r"\b(monetary policy|pol[ií]tica monet[aá]ria|fomc|quantitative|balance sheet|minutes|ata)\b", 0.9),
    "Banco central": (r"\b(central bank|banco central|fed|ecb|boe|boj|governor|presidente do bc)\b", 0.7),
    "Geopolítica": (r"\b(war|guerra|sanctions?|san[cç][oõ]es|missile|invasion|invas[aã]o|ceasefire|geopolitic|tariffs?|tarifas?)\b", 0.8),
    "Economia": (r"\b(gdp|pib|recession|recess[aã]o|retail sales|pmi|manufacturing|trade balance|balan[cç]a)\b", 0.6),
}


def classify(text: str, feed_ccy: Optional[str] = None) -> dict:
    t = text.lower()
    ccy = {feed_ccy} if feed_ccy else set()
    ccy |= {k for k, rx in CCY.items() if re.search(rx, t, re.I)}
    topics, rel = [], 0.1
    for name, (rx, w) in TOPICS.items():
        if re.search(rx, t, re.I):
            topics.append(name)
            rel = max(rel, w)
    if ccy:
        rel = min(1.0, rel + 0.1)
    impact = "Alto" if rel >= 0.9 else "Médio" if rel >= 0.6 else "Baixo"
    return {"currencies": sorted(ccy), "topics": topics, "relevance": round(rel, 2), "impact": impact}


def _parse_date(s: str) -> Optional[int]:
    if not s:
        return None
    try:
        return int(parsedate_to_datetime(s).timestamp() * 1000)
    except Exception:
        pass
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:
        return None


def parse_feed(xml_text: str, source: str, reliability: float, feed_ccy: Optional[str]) -> list:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    items = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        get = lambda name: next((c for c in el if c.tag.split("}")[-1] == name), None)
        title = (get("title").text or "").strip() if get("title") is not None else ""
        if not title:
            continue
        link_el = get("link")
        url = (link_el.text or link_el.get("href") or "").strip() if link_el is not None else ""
        first = lambda *names: next((e for e in map(get, names) if e is not None), None)  # Element vazio é "falso": não usar `or`
        date_el = first("pubDate", "published", "updated", "date")
        desc_el = first("description", "summary")
        summary = re.sub(r"<[^>]+>", " ", (desc_el.text or "") if desc_el is not None else "")[:400].strip()
        c = classify(title + " " + summary, feed_ccy)
        items.append(NewsItem(source=source, title=title, url=url, published_ms=_parse_date(date_el.text if date_el is not None else ""),
                              summary=summary, reliability=reliability, **c))
    return items


def impact_on(asset: Asset, item: NewsItem) -> Optional[str]:
    """Impacto potencial de uma notícia sobre um ativo (None = não relacionado)."""
    if not set(item.currencies) & set(asset.currencies):
        return None
    return item.impact


class NewsEngine:
    def __init__(self):
        self.items: list = []
        self.calendar: list = []
        self.feed_status: dict = {}
        self.calendar_status = "não carregado"
        self.updated_ms = 0

    async def refresh(self):
        import httpx
        headers = {"User-Agent": "Mozilla/5.0 BotTraderAI/1.0"}
        found = []
        async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as cli:
            for name, url, rel, cb in FEEDS:
                try:
                    r = await cli.get(url)
                    r.raise_for_status()
                    found += parse_feed(r.text, name, rel, cb)
                    self.feed_status[name] = "ok"
                except Exception as e:
                    self.feed_status[name] = f"{type(e).__name__}: {e}"[:120]
            try:
                r = await cli.get(CALENDAR_URL)
                r.raise_for_status()
                self.calendar = self.parse_calendar(r.json())
                self.calendar_status = "ok"
            except Exception as e:
                self.calendar_status = f"{type(e).__name__}: {e}"[:120]
        seen = set()
        self.items = sorted([n for n in found if not (n.title in seen or seen.add(n.title))],
                            key=lambda n: n.published_ms or 0, reverse=True)[:300]
        self.updated_ms = int(time.time() * 1000)

    @staticmethod
    def parse_calendar(rows: list) -> list:
        from datetime import datetime
        out = []
        for e in rows:
            try:
                t = int(datetime.fromisoformat(e["date"]).timestamp() * 1000)
            except Exception:
                continue
            out.append({"title": e.get("title"), "currency": e.get("country"), "t": t, "impact": e.get("impact"),
                        "forecast": e.get("forecast"), "previous": e.get("previous")})
        return sorted(out, key=lambda x: x["t"])

    def risk_events(self, asset: Asset, now_ms: int, window_min: int) -> list:
        w = window_min * 60_000
        return [e for e in self.calendar if e["impact"] == "High" and e["currency"] in asset.currencies and abs(e["t"] - now_ms) <= w]
