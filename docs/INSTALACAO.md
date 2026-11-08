# Instalação

## 1. Servidor (obrigatório — o app depende dele)

Precisa de um computador ou VPS com Docker (Linux recomendado; Windows/Mac com Docker Desktop também funcionam).

```bash
git clone -b bot-trader-ai https://github.com/alemanhatiktok77-a11y/-previsoes.git bot-trader-ai
cd bot-trader-ai
cp .env.example .env
# edite .env: ADMIN_PASSWORD (mín. 10 caracteres), JWT_SECRET, POSTGRES_PASSWORD, SITE_ADDRESS
docker compose up -d --build
docker compose logs -f api      # acompanhe a conexão com a Binance e as notícias
```

**HTTPS**
- Com domínio próprio apontando para o servidor: `SITE_ADDRESS=bot.seudominio.com` → certificado automático (Let's Encrypt). Portas 80 e 443 abertas.
- Só na rede local: `SITE_ADDRESS=https://192.168.0.10` e descomente `tls internal` em `deploy/Caddyfile`
  (o Android não confia nesse certificado por padrão; para testes locais você pode usar `http://192.168.0.10:8000`
  publicando a porta 8000 do serviço `api` — o app avisa que a conexão não é criptografada).

**Forex (opcional)**: crie uma chave em twelvedata.com e coloque em `TWELVEDATA_API_KEY`. O plano gratuito tem limite de créditos por minuto e por dia.

## 2. App Android
Baixe e instale: https://github.com/alemanhatiktok77-a11y/-previsoes/releases/download/bot-trader-ai-latest/BotTraderAI.apk
Abra, informe o endereço do servidor, usuário e senha do `.env`.

## 3. Desenvolvimento
```bash
cd backend && pip install -r requirements-dev.txt && python -m pytest -v
# PostgreSQL/Redis reais nos testes: export TEST_DATABASE_URL=... TEST_REDIS_URL=...
uvicorn app.api.main:create_app --factory --reload     # exige ADMIN_PASSWORD no ambiente
cd android && gradle testDebugUnitTest assembleDebug
```
Cada push roda o CI (`.github/workflows/ci.yml`): testes do backend com PostgreSQL e Redis, build da imagem Docker, testes do Android e publicação do APK.

## Avisos
- Paper trading apenas. Nenhuma ordem real é enviada.
- Opções binárias são proibidas para pessoa física na UE (incl. França) e no Reino Unido; no Brasil não há corretora autorizada pela CVM.
