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

Informe os placares dos quartos encerrados. Para cada quarto restante, a base é a projeção cruzada (ataque de um time com a defesa do outro, no mesmo quarto). O ritmo do jogo (pontos observados divididos pelos esperados) ajusta essa base com peso de 20% após o 1º quarto, 30% após o 2º e 40% após o 3º. As chances de Over usam curva normal com o desvio padrão histórico de cada quarto. Esses pesos são uma escolha conservadora, ainda não calibrada com os dados coletados; dá para recalibrar quando houver algumas centenas de jogos.

## Testes

    python -m unittest collector.tests.test_collector collector.tests.test_apisports collector.tests.test_model
    node --test tests/stats.test.mjs

## Pré-visualização sem Firebase

Abra o painel com `?demo` no final do endereço: usa dados fictícios, marcados na tela.

## Modelo, validação e backtest

- **Projeção cruzada**: (ataque de A + defesa de B)/2 + (ataque de B + defesa de A)/2, por período, nos últimos N jogos da mesma liga. Opcionalmente com peso maior aos jogos recentes (meia-vida de 8 jogos).
- **Chance estimada**: curva normal centrada na projeção. A dispersão é a das duas equipes, puxada para o padrão da liga (`meta/priors`) quando há poucos jogos. É diferente da frequência histórica, que continua visível ao lado.
- **Validação**: um jogo só entra no histórico se a soma dos quartos (mais prorrogações) bater com o placar final e cada período estiver entre 0 e 80 pontos.
- **Backtest** (`collector/backtest.py`): roda uma vez por dia, na primeira coleta do dia. Para cada jogo armazenado, refaz a projeção usando só informação anterior ao início dele: as médias vêm dos jogos anteriores das duas equipes (mínimo de 3 de cada) e a dispersão de referência da liga é acumulada só com jogos que começaram antes (jogos no mesmo horário não entram um no outro). Mede erro médio (simples e com recência), viés, Brier (modelo e frequência), calibração por faixa e o erro de calibração (ECE), com veredito: amostra insuficiente (menos de 500 casos), calibrado (até 3 p.p.), aceitável (até 6 p.p.) ou descalibrado. Enquanto não houver veredito favorável, o painel avisa que as chances não foram validadas. Um teste automático garante que acrescentar jogos futuros não altera a avaliação de nenhum jogo passado.
- **Pace**: não implementado, porque exige posses de bola (box score), indisponíveis nos planos gratuitos.
- **Prorrogação**: os quartos e o tempo regulamentar nunca incluem prorrogação; só o período "Jogo com prorrogação" inclui.

## App no celular (PWA) e carregamento

- O painel é um app instalável: `manifest.webmanifest`, ícones em `public/icons/` e `sw.js` (guarda a casca do app para abrir na hora). Ao mudar arquivos do painel, aumente `VERSION` em `public/sw.js` para os aparelhos pegarem a versão nova.
- Os dados são lidos pela API REST do Firestore, sem o SDK do Firebase: uma requisição traz todos os documentos gerais. A última versão fica salva no aparelho (`localStorage`), então o app abre na hora e atualiza em segundo plano; sem internet, mostra os dados salvos.
- No iPhone: abra o site no Safari, toque em Compartilhar e em "Adicionar à Tela de Início". Se já existia um atalho antigo, apague-o antes.
