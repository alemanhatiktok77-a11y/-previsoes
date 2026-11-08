# SinaisPro — análise técnica com sinais CALL/PUT (Android)

Arquitetura: app Android (Java + WebView) com o motor de análise rodando no próprio celular.
- assets/engine.js — indicadores (RSI, MACD, EMA 9/21/50, SMA, Bollinger, ATR, ADX, Fibonacci,
  suporte/resistência, rompimentos, falsos rompimentos, padrões de vela, volume, timeframe 5m),
  modelo combinado com votação ponderada e backtest walk-forward sem uso de dados futuros.
- assets/data.js — ativos, fontes de notícias (RSS) e classificação automática por palavras-chave.
- assets/app.js — conexões (Binance WebSocket, Twelve Data, RSS, calendário Forex Factory),
  sincronização de relógio, latência, ciclo de vida dos sinais, paper trading, estatísticas e telas.
- MainActivity.java — rede nativa, notificações, compartilhamento e tela ligada.

Fontes: Binance (cripto, tempo real, grátis), Twelve Data (forex, chave grátis com limites),
Fed/BCE/BoE/CNBC/FXStreet/Investing/CoinDesk (RSS), Forex Factory (calendário).
OTC: não há fonte pública — sinais OTC desativados.
O app não executa operações. Opções binárias são proibidas para pessoa física na UE/Reino Unido e
não autorizadas pela CVM no Brasil.
