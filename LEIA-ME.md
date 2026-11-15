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

    python -m unittest collector.tests.test_collector collector.tests.test_apisports
    node --test tests/stats.test.mjs

## Pré-visualização sem Firebase

Abra o painel com `?demo` no final do endereço: usa dados fictícios, marcados na tela.
