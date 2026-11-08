# Arquitetura — BOT TRADER AI

```
 Android (Compose) ──HTTPS/WSS──▶ Caddy ──▶ FastAPI ──┬─▶ PostgreSQL (usuários, decisões, operações, notícias)
                                                      ├─▶ Redis (pub/sub de eventos em tempo real)
                                                      └─▶ Bot (asyncio)
                                                            ├─ Data providers ─ Binance WS / Twelve Data REST
                                                            ├─ OTC registry (vazio → bloqueia OTC)
                                                            ├─ AI ENGINE (regime + 3 estratégias + calibração)
                                                            ├─ NEWS ENGINE (RSS + calendário)
                                                            ├─ RISK MANAGER
                                                            └─ EXECUTION ENGINE ─▶ BrokerAdapter (PaperBroker)
```

## Módulos (backend/app)

| Módulo | Arquivo | Função |
|---|---|---|
| Modelos | `core/models.py` | Asset (com `market` NORMAL/OTC e `source_id`), Candle, Opportunity, Decision, Trade, NewsItem |
| Indicadores | `engine/indicators.py` | EMA, SMA, RSI, MACD, Bollinger, ATR, ADX, pivôs de suporte/resistência, Fibonacci, padrões de vela, agregação 1m→5m. Todos causais |
| AI ENGINE | `engine/ai_engine.py` | Regime (TENDÊNCIA / LATERAL / VOLÁTIL), estratégias independentes (Seguidor de tendência, Reversão à média, Rompimento), calibrador estatístico, backtest e walk-forward |
| Dados | `data/providers.py` | `MarketDataProvider` (interface), Binance (WebSocket + REST, reconexão com backoff), Twelve Data (REST por minuto), `OTCRegistry` |
| Validação | `data/guard.py` | Bloqueia por latência, silêncio da fonte, desconexão, histórico curto, mercado fechado, fonte divergente, OTC sem fonte |
| Notícias | `news/engine.py` | RSS (Fed, BCE, BoE, CNBC, FXStreet, Investing, CoinDesk) + calendário Forex Factory; classifica moedas, temas, relevância, impacto e confiabilidade |
| Corretoras | `brokers/base.py`, `brokers/paper.py` | `BrokerAdapter` + `BrokerRegistry` (recusa adaptador real sem documentação oficial, aprovação legal e validação de segurança) + `PaperBroker` |
| Risco | `risk/manager.py` | Stake fixo (sem martingale), perda diária, exposição máxima, operações por dia e simultâneas, pausa por perdas seguidas, confiança mínima, STOP de emergência |
| Execução | `execution/engine.py` | Pipeline: oportunidade → dados → estratégia/expiração → risco → registro → entrada simulada → resultado; cancela por falta de preço |
| Orquestração | `bot.py` | Estados STOPPED / RUNNING / PAUSED / EMERGENCY, monitoramento contínuo, sincronização de relógio |
| API | `api/main.py`, `api/security.py` | REST + WebSocket, JWT HS256, senha com scrypt, limite de tentativas de login |
| Persistência | `db/repository.py` | SQLAlchemy Core (PostgreSQL/SQLite) e versão em memória |
| Eventos | `bus.py` | Redis Pub/Sub ou fila local, seguro entre threads |

## Regras de tempo (sem dados futuros)
- Decisão no **fechamento** da vela *i*; entrada na **abertura** da vela *i+2*; resultado no **fechamento** da vela *i+1+expiração*.
- O timeframe de 5 min usa apenas a vela de 5 min **já fechada**.
- Suportes/resistências usam pivôs até *i−1*.
- Teste `test_no_lookahead_analysis_identical_with_truncated_data` garante que a análise é idêntica com ou sem as velas futuras.
- Teste `test_backtest_on_random_walk_has_no_edge` garante que, em preço aleatório, nenhuma estratégia mostra vantagem.

## Probabilidade calibrada
A "confiança" é a taxa de acerto observada **no passado** de oportunidades da mesma estratégia, faixa de força e expiração,
com encolhimento para 50% (prior de 20 observações) e intervalo de Wilson. Mínimo de 30 observações; abaixo disso, "não calibrada".
O score bruto do modelo **não** é probabilidade.

## API
| Método | Rota | Descrição |
|---|---|---|
| POST | /auth/login | Token JWT |
| GET | /health, /time | Saúde e relógio do servidor |
| GET | /dashboard | Estado, capital, P&L, acerto, latência, conexões, operações |
| POST | /bot/start · /bot/pause · /bot/emergency-stop · /bot/reset-emergency | Controle do robô |
| GET | /assets · /otc · /news · /strategies · /trades · /decisions · /stats · /risk · /settings | Consultas |
| PUT | /risk · /strategies/{nome} | Configuração |
| POST | /paper/reset | Reinicia o capital virtual |
| WS | /ws?token= | Eventos: `price`, `trade`, `decision`, `state`, `ping` |

## O que NÃO existe (e por quê)
- **Fonte OTC**: corretoras de opções binárias não publicam API de cotações OTC. `OTCRegistry` fica vazio e todo ativo OTC é bloqueado.
- **Adaptador de corretora real**: nenhuma integração oficial aprovada. `BrokerRegistry` recusa qualquer adaptador `real_money` sem os três requisitos.
- **Reuters/Bloomberg/FT**: exigem licença paga; não incluídos.
- **Notificação com o app fechado (FCM)**: requer projeto Firebase próprio; o app notifica enquanto está aberto/em segundo plano recente.
- **Modelo de linguagem para notícias**: a classificação é por regras, documentada e testada.
