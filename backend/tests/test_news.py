from app.core.models import Asset, MarketType
from app.news.engine import NewsEngine, classify, impact_on, parse_feed

RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Fed raises interest rates by 25 basis points</title><link>https://ex.com/1</link>
<pubDate>Wed, 05 Nov 2025 19:00:00 GMT</pubDate><description>Powell says inflation remains elevated</description></item>
<item><title>Bitcoin climbs as crypto ETF inflows grow</title><link>https://ex.com/2</link><pubDate>Wed, 05 Nov 2025 18:00:00 GMT</pubDate></item>
<item><title>Local sports team wins</title><link>https://ex.com/3</link></item>
</channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>ECB keeps rates unchanged, Lagarde speaks</title>
<link href="https://ex.com/ecb"/><updated>2025-11-06T13:15:00Z</updated><summary>Euro area inflation</summary></entry></feed>"""

EURUSD = Asset("EUR/USD@twelvedata", "EUR/USD", MarketType.NORMAL, "twelvedata", 5, ("EUR", "USD"))
BTC = Asset("BTCUSDT@binance", "BTC/USD", MarketType.NORMAL, "binance", 2, ("USD", "CRYPTO"))


def test_classify_topics_and_impact():
    c = classify("Fed raises interest rates as inflation persists")
    assert "USD" in c["currencies"] and "Juros" in c["topics"] and c["impact"] == "Alto"
    assert classify("Weather is nice today")["impact"] == "Baixo"
    g = classify("Sanctions and war escalate tensions")
    assert "Geopolítica" in g["topics"]


def test_parse_rss_and_atom():
    items = parse_feed(RSS, "Teste", 0.8, None)
    assert len(items) == 3 and items[0].published_ms and items[0].reliability == 0.8
    assert items[0].impact == "Alto" and "USD" in items[0].currencies
    a = parse_feed(ATOM, "BCE", 1.0, "EUR")
    assert a[0].url == "https://ex.com/ecb" and "EUR" in a[0].currencies and a[0].published_ms


def test_impact_on_asset():
    items = parse_feed(RSS, "Teste", 0.8, None)
    assert impact_on(EURUSD, items[0]) == "Alto"
    assert impact_on(BTC, items[1]) is not None
    assert impact_on(EURUSD, items[2]) is None


def test_calendar_risk_window():
    ne = NewsEngine()
    ne.calendar = NewsEngine.parse_calendar([
        {"title": "CPI m/m", "country": "USD", "date": "2025-11-12T08:30:00-05:00", "impact": "High"},
        {"title": "German PMI", "country": "EUR", "date": "2025-11-12T03:30:00-05:00", "impact": "Medium"},
    ])
    cpi = ne.calendar[1]["t"]
    assert ne.risk_events(EURUSD, cpi + 5 * 60_000, 15)[0]["title"] == "CPI m/m"
    assert ne.risk_events(EURUSD, cpi + 60 * 60_000, 15) == []
    assert ne.risk_events(BTC, cpi, 15)  # cripto cotada em USD também é afetada
