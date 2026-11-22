# Basketball Analytics

Painel de pontuação por quarto (médias, Over, projeções e modo Ao vivo), com coleta automática na nuvem.

## Como funciona

- **Coletor** (`collector/`, Python): roda no GitHub Actions 4 vezes por dia (02:17, 08:17, 14:17 e 20:17 UTC), sem depender do notebook. Usa duas fontes, cada uma com sua cota:
  - **API-Sports** (`collector/apisports.py`, chave da API-Football): uma chamada por data traz todos os jogos do dia com os quartos. Busca ontem e hoje e usa o restante da cota para voltar no tempo, um dia por chamada.
  - **Basketball API** (`collector/main.py`, basketballapi.net): uma chamada por jogo para obter os quartos.
  - As duas gravam no mesmo formato. Uma liga presente nas duas aparece duas vezes no painel, identificada pela fonte.
- **Banco**: Firestore. Coleções `teams` (últimos 60 jogos de cada equipe, com os quartos) e `meta` (índice, status, cota). `games` é interna do coletor.
- **Painel** (`public/`): página estática no Firebase Hosting. Lê só o Firestore, abre no celular.

## Limites do plano gratuito da API (conferidos na documentação oficial)

- 100 chamadas por dia e 10 por minuto. O coletor usa no máximo 92 por dia e 30 por execução.
- Os placares por quarto só vêm no detalhe de cada jogo (`/games/{id}`): **1 chamada por jogo**. Na prática, cerca de 70 a 80 jogos por dia.
- O plano gratuito promete resultados de ontem e hoje. O coletor tenta automaticamente buscar dias anteriores; se a API bloquear, a aba Cobertura mostra "bloqueado" e o histórico se forma dia a dia.
- Para chegar mais rápido aos 20 jogos, restrinja as ligas em `collector/config.json` (`only_competitions`, por palavra do nome, ex.: `["NBB", "EuroLeague", "ACB"]`). Ligas em `priority_competitions` são processadas primeiro.

## Modo Ao vivo

- A varredura ao vivo (`python -m collector.main run --only live`) é disparada no GitHub Actions a cada 10 min e grava na agenda os placares com os quartos parciais. Só chama a API quando passou o intervalo mínimo do plano: 30 min no gratuito (as execuções do meio terminam sem gastar cota) e 10 min no pago. Usa 1 chamada (2 de madrugada, em UTC) e não grava nas equipes.
- No painel, ao abrir um jogo em andamento, os quartos já encerrados são preenchidos sozinhos e as chances aparecem na hora: restante do jogo (ex.: 2º tempo após o intervalo), jogo inteiro, próximo quarto e chance de vitória. Dá para editar à mão.
- O ritmo do jogo pesa 10%, 20% e 30% após o 1º, 2º e 3º quartos (escolhido no backtest). Ligas em tempos (NCAA masculina) usam o 1º tempo.
- Com o app aberto, os placares são conferidos a cada 3 minutos.

## Plano pago da API-Sports

1. Assine o plano no site da API-Sports. A chave costuma ser a mesma (Secret `APISPORTS_KEY`); se mudar, atualize o Secret.
2. Em `collector/config.json`, troque `"plan": "free"` por `"plan": "pro"` e confira `daily_call_limit` em `apisports.plans.pro` com a cota real do seu plano.
3. Pronto: o agendador já dispara a cada 10 min, e no plano pago cada disparo atualiza os placares.
   O repositório é público, então os minutos do Actions não têm limite. Se ele virar privado, volte `*/10 * * * *` para `*/30 * * * *` nas três ocorrências de `.github/workflows/coletor.yml` (a cada 10 min seriam cerca de 4.300 min/mês, acima dos 2.000 grátis).
4. No plano pago o histórico retroativo volta a andar, limitado a `backfill_days_per_run` dias por coleta completa para respeitar as 20 mil gravações/dia do Firestore.

## Testes

    python -m unittest collector.tests.test_collector collector.tests.test_apisports collector.tests.test_model
    npm test

## Pré-visualização sem Firebase

Abra o painel com `?demo` no final do endereço: usa dados fictícios, marcados na tela.

## Modelo, validação e backtest

Detalhes, números e evidências em `relatorio/` (RELATORIO_FINAL.md, 01 a 03).

- **Modelo v2**: parte da média da liga no período e ajusta pelo histórico das equipes na proporção da amostra (com 4 jogos a equipe pesa 50%; com 20, 83%). A dispersão vem da liga, corrigida pelo que o backtest observou. Validado fora da amostra: erra 0,72 ponto a menos por quarto que o modelo original e tem chances calibradas (ECE de 1,9 p.p.).
- **Qualidade dos dados**: jogos da NCAA masculina chegam em tempos (Q1 = Q3 = 0) e entram só em tempos e jogo; jogos com quarto 0 x 0 são recusados; o mesmo jogo gravado pelas duas APIs conta uma vez só.
- **Backtest diário** (`collector/backtest.py`): avalia o v2, o modelo original e a média da liga, jogo a jogo, só com jogos anteriores. O veredito conta jogos distintos (mínimo 300), não casos correlacionados. Resultado na aba Modelo.
- **Backtest completo local**: `python scripts/backtest_completo.py` (referências, variantes testadas, intervalos de confiança, pesos ao vivo).
- **Pace**: não implementado, porque exige posses de bola (box score), indisponíveis nos planos gratuitos.
- **Prorrogação**: os quartos e o tempo regulamentar nunca incluem prorrogação; só o período "Jogo com prorrogação" inclui.

## App no celular (PWA) e carregamento

- O painel é um app instalável: `manifest.webmanifest`, ícones em `public/icons/` e `sw.js` (guarda a casca do app para abrir na hora). Ao mudar arquivos do painel, aumente `VERSION` em `public/sw.js` para os aparelhos pegarem a versão nova.
- Os dados são lidos pela API REST do Firestore, sem o SDK do Firebase: uma requisição traz todos os documentos gerais. A última versão fica salva no aparelho (`localStorage`), então o app abre na hora e atualiza em segundo plano; sem internet, mostra os dados salvos.
- No iPhone: abra o site no Safari, toque em Compartilhar e em "Adicionar à Tela de Início". Se já existia um atalho antigo, apague-o antes.
