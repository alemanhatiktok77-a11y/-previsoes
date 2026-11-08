/* ===== Fontes de dados, notícias e calendário ===== */
const ASSETS = [
  // Criptomoedas — Binance (WebSocket em tempo real, gratuito, sem chave)
  { id:'BTCUSDT', name:'BTC/USD', src:'binance', dec:2, ccy:['USD','CRYPTO'] },
  { id:'ETHUSDT', name:'ETH/USD', src:'binance', dec:2, ccy:['USD','CRYPTO'] },
  { id:'SOLUSDT', name:'SOL/USD', src:'binance', dec:3, ccy:['USD','CRYPTO'] },
  { id:'XRPUSDT', name:'XRP/USD', src:'binance', dec:4, ccy:['USD','CRYPTO'] },
  { id:'BNBUSDT', name:'BNB/USD', src:'binance', dec:2, ccy:['USD','CRYPTO'] },
  // Forex / metais — Twelve Data (precisa de chave gratuita)
  { id:'EUR/USD', name:'EUR/USD', src:'twelve', dec:5, ccy:['EUR','USD'] },
  { id:'GBP/USD', name:'GBP/USD', src:'twelve', dec:5, ccy:['GBP','USD'] },
  { id:'USD/JPY', name:'USD/JPY', src:'twelve', dec:3, ccy:['USD','JPY'] },
  { id:'AUD/USD', name:'AUD/USD', src:'twelve', dec:5, ccy:['AUD','USD'] },
  { id:'USD/CAD', name:'USD/CAD', src:'twelve', dec:5, ccy:['USD','CAD'] },
  { id:'EUR/JPY', name:'EUR/JPY', src:'twelve', dec:3, ccy:['EUR','JPY'] },
  { id:'EUR/GBP', name:'EUR/GBP', src:'twelve', dec:5, ccy:['EUR','GBP'] },
  { id:'XAU/USD', name:'Ouro (XAU/USD)', src:'twelve', dec:2, ccy:['USD','XAU'] },
];

const NEWS_FEEDS = [
  { name:'Federal Reserve', url:'https://www.federalreserve.gov/feeds/press_all.xml', cb:'USD' },
  { name:'Banco Central Europeu', url:'https://www.ecb.europa.eu/rss/press.html', cb:'EUR' },
  { name:'Banco da Inglaterra', url:'https://www.bankofengland.co.uk/rss/news', cb:'GBP' },
  { name:'CNBC Economia', url:'https://www.cnbc.com/id/20910258/device/rss/rss.html' },
  { name:'CNBC Mercados', url:'https://www.cnbc.com/id/15839069/device/rss/rss.html' },
  { name:'FXStreet', url:'https://www.fxstreet.com/rss/news' },
  { name:'Investing.com Forex', url:'https://www.investing.com/rss/news_1.rss' },
  { name:'Investing.com Economia', url:'https://www.investing.com/rss/news_14.rss' },
  { name:'CoinDesk', url:'https://www.coindesk.com/arc/outboundfeeds/rss/' },
];
const CALENDAR_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'; // dados do calendário do Forex Factory

/* Classificação automática das notícias (regras de palavras-chave, PT/EN).
   Não é uma "previsão": só indica quais moedas a notícia toca e o peso do tema. */
const NLP = {
  ccy: {
    USD:[/\b(fed|fomc|powell|federal reserve|u\.?s\.?|united states|america|treasury|nonfarm|payrolls?|wall street|dollar|d[oó]lar|eua|estados unidos)\b/i],
    EUR:[/\b(ecb|bce|lagarde|euro ?zone|eurozone|euro area|zona do euro|germany|alemanha|france|fran[cç]a|italy|it[aá]lia|\beuro\b)/i],
    GBP:[/\b(boe|bank of england|bailey|uk|britain|british|reino unido|sterling|pound|libra)\b/i],
    JPY:[/\b(boj|bank of japan|ueda|japan|jap[aã]o|yen|iene)\b/i],
    AUD:[/\b(rba|australia|austr[aá]lia|aussie)\b/i],
    CAD:[/\b(boc|bank of canada|canada|canad[aá]|loonie)\b/i],
    XAU:[/\b(gold|ouro|bullion)\b/i],
    CRYPTO:[/\b(bitcoin|btc|ether(eum)?|crypto|cripto|solana|xrp|ripple|binance|stablecoin|etf)\b/i],
  },
  high:/\b(rate decision|interest rate|raises rates|cuts rates|rate (hike|cut)|juros|taxa b[aá]sica|cpi|inflation|infla[cç][aã]o|nonfarm|payrolls|unemployment|desemprego|gdp|pib|fomc|monetary policy|pol[ií]tica monet[aá]ria|emergency|war|guerra|invasion|default|sanctions|san[cç][oõ]es|tariffs?|tarifas?)\b/i,
  medium:/\b(pmi|retail sales|vendas no varejo|jobless claims|ism|minutes|ata|speech|discurso|testimony|consumer confidence|housing|trade balance|balan[cç]a comercial|earnings|oil|petr[oó]leo|opec|opep|election|elei[cç][aã]o|regulation|regula[cç][aã]o|sec)\b/i,
  classify(text, feedCb) {
    const c = new Set(); if (feedCb) c.add(feedCb);
    for (const [k, rs] of Object.entries(this.ccy)) if (rs.some(r => r.test(text))) c.add(k);
    const imp = this.high.test(text) ? 'Alto' : this.medium.test(text) ? 'Médio' : 'Baixo';
    const topics = [];
    if (/juros|interest rate|rate (hike|cut|decision)|monetary/i.test(text)) topics.push('Juros');
    if (/inflation|infla|cpi|pce/i.test(text)) topics.push('Inflação');
    if (/payroll|jobs|employment|emprego|unemployment/i.test(text)) topics.push('Emprego');
    if (/gdp|pib|recession|recess/i.test(text)) topics.push('Crescimento');
    if (/war|guerra|sanction|geopolit|missile|attack|ataque/i.test(text)) topics.push('Geopolítica');
    return { ccy: [...c], impact: imp, topics };
  }
};
