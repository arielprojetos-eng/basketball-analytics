# Etapa 2: auditoria do modelo original

Código auditado: `collector/model.py`, `collector/backtest.py`, `public/js/stats.js`, `public/js/app.js` (versão anterior a esta revisão).
Os números citados foram medidos sobre `dados/teams.json` (exportado em 22/11/2026).

## Como o modelo original funcionava

| Aspecto | Implementação original |
| --- | --- |
| Variáveis | Só os pontos por quarto marcados e sofridos de cada equipe. Sem posses, sem média da liga, sem mando como variável. |
| Médias | Média simples (ou com meia-vida de 8 jogos) dos últimos N jogos da equipe na mesma liga. N = 5, 10 ou 20 no painel; 10 no backtest. |
| Projeção do total | Cruzada: (ataque A + defesa B)/2 + (ataque B + defesa A)/2. Para o **total**, isso é algebricamente igual à média dos totais das duas equipes; a divisão ataque/defesa só importa para os pontos de cada time. |
| Probabilidade | Normal centrada na projeção. Desvio = desvio dos totais das duas equipes, encolhido (K = 6) para um "prior" da liga (liga com 15+ jogos) ou global. |
| Mandante/visitante | Só como filtro de amostra (corta a amostra pela metade), nunca como ajuste. |
| Competição | Só como filtro de amostra e como prior de dispersão. A média da liga não entrava na projeção. |
| Amostra pequena | A média **não** era encolhida: com 1 jogo, a projeção era o total daquele único jogo. Só a dispersão era encolhida. |
| Parâmetros fixos | K = 6, meia-vida 8, desvios padrão de partida, pesos ao vivo 20/30/40% (o próprio LEIA-ME dizia "não calibrados"), mínimo de 3 jogos no backtest. |

## Limitações e problemas encontrados

1. **Dados contaminados na dispersão.** 434 jogos da NCAA masculina estão gravados em tempos (Q1 = Q3 = 0) e 5 jogos zerados ou truncados foram gravados como encerrados. Isso inflou a dispersão global de um quarto para 18,4 pontos (a real, dentro da liga, é 7,7 a 8,1), achatando as chances perto de 50% em todas as ligas que usavam o prior global.
2. **Projeção absurda para a NCAA masculina.** Para esses times, o painel projetava 0 ponto no 1º e no 3º quarto e o dobro no 2º e no 4º.
3. **Sem regressão à média.** Com no máximo 6 jogos por equipe na base, a média própria é dominada por ruído. No backtest, com 1 jogo de cada lado, o original errou 6,80 pontos por quarto contra 5,92 do v2; com 0 jogo, não projetava nada.
4. **Chances superconfiantes nos extremos.** Quando o original previa 90 a 100% de Over, aconteceu 79%; quando previa 0 a 10%, aconteceu 30%.
5. **Frequência histórica exibida ao lado da chance.** Com amostras de 1 a 5 jogos, ela vale 0% ou 100% com frequência. No backtest teve Brier 0,29 e log loss 1,17, pior que chutar 50% (0,25 e 0,69).
6. **Dispersão do jogo com prorrogação** caía sempre no valor fixo de 15,5, porque os priors não tinham o período "total"; a dispersão real dentro da liga é 20,1.

## Vazamento de dados e resultados artificialmente melhores

| Verificação | Resultado |
| --- | --- |
| Uso de jogos futuros nas médias | **Não há.** `prior_rows` usa só jogos com início anterior; há teste automático para isso. |
| Jogos simultâneos | Tratados corretamente: o mesmo horário não entra na estatística do outro. |
| Prior de dispersão no backtest | Acumulado só com jogos anteriores (correto). O `meta/priors` com todo o histórico é usado só no painel, para previsões de agora (correto). |
| Mesmo jogo nas duas fontes | **Problema.** 185 jogos existem nas duas APIs com IDs diferentes. No backtest original, 8 dos 39 jogos avaliados eram a mesma partida contada duas vezes (NBA e "NBA (USA)"). A cópia também entrava duas vezes na dispersão global; em casos raros (horários diferentes entre as fontes) uma cópia entrava antes da avaliação da outra. Efeito pequeno, mas é vazamento. |
| Veredito de calibração | **Superestimado.** Contava "casos" = jogos × 7 períodos × 5 linhas, fortemente correlacionados. Com 22 jogos, declarava 770 casos e "aceitável" (mínimo 500). Com 39 jogos, o mesmo código passou a dizer "descalibrado". O veredito não tinha estabilidade estatística. |
| Viés de seleção | O backtest original só avaliava jogos em que as duas equipes tinham 3+ jogos na liga: 39 jogos (2% da base), 76% deles da NBA. Não representava o uso real do painel, que projeta com qualquer amostra. |
| Projeções triviais | Para jogos em tempos, uma previsão de 0 contra um real de 0 no Q1/Q3 seria um acerto artificial. Na base atual nenhum desses jogos entrou no backtest original (as equipes da NCAA não chegaram a 3 jogos), mas entraria com o tempo. |

## Conclusão da auditoria

Não havia uso de informação futura nas médias. Os problemas que tornavam os resultados enganosos eram a **contaminação dos dados** (tempos gravados como quartos, jogos zerados, duplicatas entre fontes) e um **veredito de calibração baseado em casos correlacionados**. A estrutura do modelo também não tinha regressão à média, decisiva numa base com no máximo 6 jogos por equipe. Correções e evidências: `relatorio/03_backtest.md`.
