# BOT TRADER AI

Plataforma de análise de mercado com robô em **paper trading** (simulação com preços reais).
Execução financeira real **desativada** por desenho.

| Parte | Tecnologia | Pasta |
|---|---|---|
| App Android | Kotlin, Jetpack Compose, Material 3, OkHttp (REST + WebSocket) | `android/` |
| Servidor | Python 3.12, FastAPI, SQLAlchemy, PostgreSQL, Redis, WebSocket | `backend/` |
| Infra | Docker Compose + Caddy (HTTPS automático) | `docker-compose.yml`, `deploy/` |
| Testes/CI | pytest (48 testes), JUnit (4 testes), GitHub Actions | `backend/tests`, `android/app/src/test` |

- Documentação técnica: [docs/ARQUITETURA.md](docs/ARQUITETURA.md)
- Instalação: [docs/INSTALACAO.md](docs/INSTALACAO.md)
