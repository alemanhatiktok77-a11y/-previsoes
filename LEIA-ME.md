# Previsões de Jogos (Android)

App de previsões de futebol: jogos **ao vivo** (atualiza a cada 30 s) e **próximos 7 dias**,
com probabilidade de vitória/empate/derrota, placar mais provável, mais de 2,5 gols e ambos marcam.
Ligas: Brasileirão A e B, Libertadores, Sul-Americana, Champions, Premier League, La Liga,
Serie A, Bundesliga, Ligue 1 e Liga Portugal.

## Como gerar o APK (sem instalar nada no PC)
1. Crie uma conta em github.com e um repositório novo.
2. Clique em "uploading an existing file" e arraste TODO o conteúdo desta pasta
   (inclusive a pasta `.github`).
3. Vá na aba **Actions** → "Gerar APK" → aguarde ~5 min.
4. Abra a execução concluída e baixe **Previsoes-APK** (zip com `app-debug.apk`).
5. Passe o APK para o celular e instale (permita "instalar apps de fontes desconhecidas").

## Ou com Android Studio
Abra esta pasta no Android Studio e clique em ▶ Run.

## Como funciona
Dados dos jogos: API pública da ESPN (sem chave). Previsão: modelo de Poisson usando
gols marcados/sofridos da tabela (ou a forma recente nas copas), com vantagem de mando.
Nos jogos ao vivo, o cálculo considera o placar e o minuto atual.
As previsões são estatísticas e não garantem resultado.
