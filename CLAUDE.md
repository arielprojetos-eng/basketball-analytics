# Basketball Analytics — contexto para o Claude Code

Painel pessoal de estatísticas de basquete por quarto, para análise de Over/Under (totais por quarto, tempo e jogo).
Dono: Ariel Carvalho (Recife/PE). Responda sempre em português do Brasil, tom formal e direto, sem travessões.

## Arquitetura

- **Coleta (Python, `collector/`)**: roda no GitHub Actions (`.github/workflows/coletor.yml`). Três jobs:
  coleta completa + backtest (cron `17 2,8,14,20 * * *` UTC) e ao vivo (cron `*/10 * * * *`, `run --only live`:
  só atualiza placares com quartos parciais em `meta/agenda`, 1 a 2 chamadas, sem gravar nas equipes).
  e odds (cron `40 15 * * *` e a cada push em `collector/odds.py`: `run --only live --force --max-calls 1` e `run --only odds`).
  Antes de coletar, roda os testes; se algum falhar, a coleta é cancelada.
  - Plano da API-Sports em `collector/config.json` (`apisports.plan`: "free" ou "pro"; limites em `apisports.plans`).
    O coletor só chama a API quando passou o intervalo mínimo do plano (gratuito 30 min, pago 10 min).
    O repositório é público (minutos do Actions ilimitados); se virar privado, volte o cron ao vivo para `*/30`.
  - `apisports.py`: API-Sports Basketball (`v1.basketball.api-sports.io`, header `x-apisports-key`). Busca ontem até depois de amanhã (4 chamadas), grava jogos encerrados com quartos e a agenda do dia em `meta/agenda`. Plano gratuito: 100 chamadas/dia, sem datas antes de ontem (backfill fica "blocked").
  - `api.py` + `main.py`: Basketball API (`api.basketballapi.net/v1`, Bearer). Gratuito: 100/dia, 10/min, só ontem/hoje; quartos só em `/games/{id}`.
  - `store.py`: `FirestoreStore` (firebase-admin), `BufferedStore` (agrupa gravações para caber na cota grátis de 20 mil gravações/dia), `MemoryStore` (testes).
  - `model.py`: fórmulas do modelo (espelho exato de `public/js/stats.js`; mudou uma, mude a outra). Modelo original intacto (referência) e modelo v2 (em uso).
  - `odds.py`: odds de Over/Under (fase 1, só grava; o painel ainda não mostra). A API atualiza odds 1 vez por dia, de 1 a 7 dias antes do jogo; 1 chamada por liga e temporada. Grava `meta/odds` e `odds_hist/{data}` (linha de consenso entre casas e chance de Over sem margem, por período q1..q4, h1, h2, total). Gratuito: 4 chamadas/dia.
  - `walkforward.py`: motor walk-forward compartilhado (só jogos anteriores; jogos simultâneos não se enxergam; duplicatas entre fontes e jogos inválidos fora).
  - `backtest.py`: backtest diário do v2 com o original e a média da liga lado a lado; grava `meta/backtest` e `meta/priors.v2`. Veredito de calibração por ECE com mínimo de 300 JOGOS distintos (não casos).
- **Banco (Firestore, projeto `basketball-analytics-233f9`, região southamerica-east1)**
  - `teams/{id}`: `{id, name, n, updatedAt, games: [...]}` com até 60 jogos por equipe, do mais recente ao mais antigo. Cada jogo: `gid, date, sortKey, cid, cname, home, oppId, oppName, pts[4], oppPts[4], ot, oppOt`.
  - `meta/index` (competições e equipes), `meta/priors` (dispersão por liga), `meta/backtest`, `meta/agenda`, `meta/status*`, `meta/quota*`, `meta/backfill*`.
  - `odds_hist/{AAAA-MM-DD}`: retratos diários das odds por jogo (o último antes do jogo é o fechamento). Leitura pública.
  - IDs com prefixo `as_` vêm da API-Sports; os demais, da Basketball API (os mesmos times podem existir nas duas fontes com IDs diferentes).
  - Leitura de `teams` e `meta` é pública; gravação só pela conta de serviço.
- **Painel (`public/`)**: PWA estático no Firebase Hosting (https://basketball-analytics-233f9.web.app). Lê o Firestore por REST (`js/data.js`), cache em localStorage, service worker `sw.js` (suba `VERSION` a cada mudança no painel). Abas: Jogos, Confronto, Ao vivo (preenche os quartos sozinho pela agenda), Modelo (backtest), Dados. Tema claro, fonte Archivo (condensada nos números). Sem `priors.v2` no Firestore, cai no modelo original e avisa.
- **Publicação**: `.github/workflows/publicar.yml` (manual, `firebase deploy` hosting + firestore).

## Modelo (v2, validado em relatorio/03_backtest.md)

- Qualidade: `shape()` classifica o placar em quartos, tempos (Q1 = Q3 = 0, NCAA masculina: vale só para tempos e jogo) ou inválido (quarto 0 x 0: fora de tudo).
- Média da liga no período, encolhida para a média global do mesmo gênero (k_comp = 3).
- Total = liga + metade da soma dos desvios das equipes, cada um encolhido por n/(n + 4) (k_team = 4). Mesma liga, até 20 jogos.
- Dispersão: desvio da liga encolhido para o agrupado (k_sd = 40), mais a incerteza das médias, vezes a escala aprendida no backtest (`sdScale`).
- Probabilidade de Over pela normal; linha central `floor(média) + 0,5`.
- Ao vivo: ritmo pesa 10/20/30% após Q1/Q2/Q3 (escolhido no backtest); ligas em tempos usam 20% após o 1º tempo. Chance de vitória pela dispersão do saldo da liga.
- Testados e rejeitados: recência, amostra por mando, correção de viés, vantagem de mando no total.
- O modelo original (projeção cruzada, K = 6) continua no código para comparação e reversão.

## Dados para análise

Rode `python scripts/exportar_dados.py` (só biblioteca padrão; nenhuma chave secreta necessária). Gera em `dados/`:
`teams.json`, `meta.json`, `jogos.csv` (um jogo por linha com os 4 quartos de cada lado, prorrogação e totais) e `RESUMO.txt`.
A pasta `dados/` está no `.gitignore`.

## Ícones

`python scripts/gerar_icones.py` (Pillow) gera `public/icons/`. Ao trocar ícones, suba o `?v=` em `index.html` e no manifest e o `VERSION` do `sw.js`.

## Análise e backtest local

- `python scripts/analise_dados.py` grava `relatorio/01_analise_dados.md`.
- `python scripts/backtest_completo.py` (cerca de 3 min) grava `relatorio/03_backtest.md` e `relatorio/backtest_resultados.json`: referências, original, v2, variantes, bootstrap e pesos ao vivo. Ajuste até 18/11/2026, teste depois.

## Testes

- Python: `python -m unittest collector.tests.test_collector collector.tests.test_apisports collector.tests.test_model`
- JavaScript: `npm test` (node, sem dependências)
- Os testes passam `today=` fixo; não use a data real do relógio dentro de funções testadas.

## Regras

- Nunca gravar chaves de API em arquivos. Elas ficam só nos Secrets do GitHub: `BASKETBALL_API_KEY`, `APISPORTS_KEY`, `FIREBASE_SERVICE_ACCOUNT`.
- Não alterar a matemática do modelo sem rodar o backtest e comparar o antes e o depois.
- Respeitar as cotas: 100 chamadas/dia em cada API e 20 mil gravações/dia no Firestore.
- O histórico só cresce dia a dia (os planos grátis não permitem buscar datas antigas).
