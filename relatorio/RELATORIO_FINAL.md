# Relatório final: auditoria, recalibragem e redesign (22/11/2026)

Detalhes e tabelas completas: `01_analise_dados.md` (dados), `02_auditoria_modelo.md` (modelo original), `03_backtest.md` (backtest e ajustes). Todos os números saem de scripts reexecutáveis (`scripts/analise_dados.py`, `scripts/backtest_completo.py`) sobre `dados/teams.json`.

## 1. Diagnóstico dos dados

| Item | Valor |
| --- | --- |
| Jogos únicos válidos | 2.062 (2.252 registros, menos 185 duplicatas entre fontes e 5 jogos inválidos) |
| Período | 14 a 22/11/2026 (9 dias; o plano gratuito bloqueia datas anteriores) |
| Equipes / competições | 2.346 documentos de equipe / 135 competições (21 com 15+ jogos) |
| Jogos por equipe | máximo 6; 17 equipes com 5+; nenhuma com 10+ |

Principais descobertas:
- **A liga explica de 46% a 57% da variância** do total de um quarto. Dentro da liga, o desvio por quarto é de 7,7 a 8,1 pontos (bruto: 10).
- **Os quatro quartos têm a mesma média** (diferenças abaixo de 0,25 ponto, p > 0,1). Ajuste de média por quarto não se justifica.
- **Mando:** o mandante faz cerca de 1,3 ponto a mais por quarto e vence 63,6% dos jogos, mas isso divide os pontos, não muda o total.
- **Ligas femininas:** 33,5 pontos por quarto, contra 43,1 nas masculinas.
- Distribuições quase normais (assimetria de 0,5 a 0,7), o que sustenta a curva normal das chances.

Problemas encontrados:
1. **434 jogos da NCAA masculina gravados em tempos** (Q1 = Q3 = 0), 21% da base. Inflavam a dispersão global do quarto para 18,4 pontos.
2. **5 jogos zerados ou truncados** gravados como encerrados (ex.: G League [27, 31, 28, 0]).
3. **185 jogos duplicados entre as duas APIs** com IDs diferentes.
4. Bug no `scripts/exportar_dados.py`: ordenava o resumo pelo nome em vez da contagem e quebrava. Corrigido.
5. A temporada não é gravada nos jogos das equipes; não há como comparar temporadas.

## 2. Diagnóstico do modelo original

Funcionava com médias de pontos marcados e sofridos das equipes (sem média da liga), curva normal com dispersão da equipe encolhida para um prior, e mando apenas como filtro. Limitações principais: **nenhuma regressão à média** (com 1 jogo, a projeção era aquele jogo), dispersão contaminada pelos dados ruins, chances superconfiantes nos extremos (previa 90 a 100%, aconteceu 79%) e **veredito de calibração apoiado em casos correlacionados** (22 jogos viravam 770 "casos"). Não havia uso de informação futura nas médias; havia um vazamento pequeno pelas duplicatas entre fontes. Onde mais errava: com amostra pequena (1 jogo de cada lado: 6,80 pontos por quarto) e nas faixas extremas de chance.

## 3. Resultados do backtest (fora da amostra)

Protocolo: walk-forward por horário de início, parâmetros escolhidos só de 15 a 18/11 e avaliados de 19 a 22/11 (708 jogos com quartos; 871 com tempos e jogo). Linhas de Over sintéticas e iguais para todos os modelos (não há linhas de mercado na base).

**Quartos agrupados, período de teste**

| Modelo | Jogos | MAE | Viés | Acerto na linha | Brier | Log loss | ECE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Média global | 708 | 7,87 | +0,25 | 54,3% | 0,262 | 0,755 | 12,4 p.p. |
| Média da liga | 708 | 6,34 | −0,07 | 50,6% | 0,230 | 0,652 | 1,9 p.p. |
| Original (painel) | 465 | 6,84 | +0,04 | 55,0% | 0,240 | 0,681 | 5,1 p.p. |
| Frequência Freq. A/B | 465 | – | – | 57,4% | 0,293 | 1,168 | 18,1 p.p. |
| **v2 (adotado)** | 708 | **6,17** | +0,06 | **56,9%** | **0,223** | **0,637** | 2,4 p.p. |

Nos mesmos 465 jogos em que o original projetava: v2 com MAE 6,12 contra 6,84 e Brier 0,222 contra 0,240.

Intervalos de confiança (bootstrap por jogo): v2 − original: MAE −0,72 [−0,88; −0,56], Brier −0,018 [−0,022; −0,013], **melhora comprovada**. v2 − média da liga: MAE −0,17 [−0,23; −0,12], **melhora comprovada**.

**Por período (teste, MAE v2 / média da liga / original nos mesmos jogos):** Q1 6,38 / 6,55 / 7,08; Q2 6,09 / 6,28 / 6,39; Q3 5,96 / 6,10 / 6,94; Q4 6,24 / 6,42 / 6,94; 1º tempo 9,26 / 9,59; 2º tempo 9,06 / 9,25; jogo 14,47 / 15,08.

**Por competição (teste, 15+ jogos, MAE por quarto):** NCAA feminina 5,52; NKL 5,83; CBA Club Cup 6,66; NBA 7,39; G League 8,13 (maior erro). Em todas o v2 erra menos que a média da liga.

**Por equipe:** 38 equipes têm 4 a 5 jogos avaliados; nenhuma tem amostra para conclusão individual.

**Calibração do v2 (teste, quartos):** ECE de 2,4 p.p.; com a escala de dispersão, 1,8 p.p. e cobertura da faixa de 80% exatamente em 80%. No backtest de produção, sobre toda a base: ECE de 1,9 p.p. em 1.306 jogos, veredito "calibrado".

**Pioras:** a amostra separada por mando piorou o MAE (+0,04 [+0,01; +0,07]) e foi rejeitada.

## 4. Alterações realizadas

Modelo e coleta:
- `collector/model.py`: funções originais intactas (referência e reversão) e modelo **v2**: média da liga encolhida para a média global do gênero (k_comp = 3), desvio da equipe encolhido por n/(n + 4), dispersão da liga encolhida (k_sd = 40) com a incerteza das médias e a escala aprendida no backtest. Também a detecção de formato (`shape`: quartos, tempos ou inválido), o período com prorrogação e a projeção ao vivo v2 com chance de vitória.
- `collector/walkforward.py` (novo): motor walk-forward compartilhado, com deduplicação entre fontes e exclusão de jogos inválidos.
- `collector/backtest.py`: backtest v2 diário com o original e a média da liga lado a lado; veredito por **jogos** (mínimo 300); `meta/priors.v2` com média, dispersão, vantagem de mando e dispersão do saldo por liga. Campos antigos preservados.
- `collector/main.py`: recusa jogos zerados ou truncados na entrada; novo comando `run --only live`.
- `collector/apisports.py`: quartos parciais na agenda, varredura ao vivo (só agenda, sem gravar nas equipes), troca de plano por configuração, retroativo limitado por execução no plano pago.
- `collector/config.json`: `apisports.plan` ("free" ou "pro") com os limites de cada plano.
- `.github/workflows/coletor.yml`: job de ao vivo disparado a cada 10 min (repositório público), separado da coleta completa; a API só é chamada a cada 30 min no plano gratuito e a cada 10 min no pago. `publicar.yml` passa a rodar todos os testes JS.
- `public/js/stats.js`: espelho exato do v2 (paridade zero em 400 confrontos reais).

Painel (redesign completo, `public/`):
- Tema claro com uma família tipográfica (Archivo) em duas larguras; acento verde quadra, ocre para a equipe B, vermelho só para ao vivo.
- Navegação com cinco abas: Jogos, Confronto, **Ao vivo** (ação central), **Modelo** (nova; backtest com diagrama de calibração) e Dados. No desktop, barra lateral.
- Jogos em listas agrupadas por liga, com quartos parciais nos jogos ao vivo e encerrados.
- Confronto: projeção com régua de distribuição (faixa de 80% e linha central), escada de chances com barras, histórico e gráficos.
- Ao vivo: lista dos jogos em andamento, **preenchimento automático dos quartos encerrados** pela coleta, chances do restante (ex.: 2º tempo), do jogo e do próximo quarto, chance de vitória; edição manual continua disponível. Ligas em tempos tratadas.
- Atualização automática dos placares a cada 3 min com o app aberto; o cache de dados passou a mesclar atualizações parciais.
- Mobile: sem rolagem horizontal em 320, 375 e 768 px; tabelas largas rolam dentro do próprio bloco; colunas secundárias somem abaixo de 520 px.

Figma: não há integração com o Figma nesta sessão. O redesign foi especificado e implementado direto no código.

## 5. Validação

- Python: 52 testes aprovados, 0 reprovados (eram 31). Novos: formatos de placar, valores de referência do v2, encolhimento, ausência de vazamento no backtest v2, duplicatas, jogos inválidos, veredito por jogos, ao vivo, varredura ao vivo, intervalo mínimo e troca de plano, reserva de cota.
- JavaScript: 22 testes aprovados, 0 reprovados (eram 16), com os mesmos valores de referência do Python.
- Paridade Python x painel em 400 confrontos reais: diferença máxima zero.
- Navegador: dados reais e modo demonstração em 320, 375, 768 e 1280 px; nenhum erro de console; fluxo ao vivo testado com 50 x 40 no intervalo.
- Workflows validados como YAML.

Pendências e riscos:
- **Nada foi publicado.** O Firestore continua com `priors` no formato antigo até a próxima coleta completa com o código novo. Até lá o painel usa o modelo original como reserva, avisando na tela.
- O ao vivo depende da varredura nova. Com a agenda atual (sem quartos parciais) o preenchimento é manual.
- **Minutos do GitHub Actions:** o repositório é público, então o disparo a cada 10 min não tem custo. Se ele virar privado, volte para 30 min (a cada 10 min seriam cerca de 4.300 min/mês, acima dos 2.000 grátis).
- O agendador do GitHub pode atrasar alguns minutos em horários de pico; o intervalo real fica entre 10 e cerca de 15 min.
- Base de 9 dias e início de temporada: os parâmetros podem mudar com mais dados. O backtest diário mostra isso na aba Modelo.
- O formato ao vivo da NCAA masculina na API (quartos ou tempos durante o jogo) não pôde ser observado; o painel trata os dois casos, mas isso precisa ser conferido num jogo real.
- A cota diária do plano pago foi configurada em 7.000 chamadas por cautela; confira no painel da API-Sports.

## 6. Conclusão

- **O modelo está calibrado?** O v2 sim, dentro do que a base permite: ECE de 1,9 p.p. em 1.306 jogos e 2,4 p.p. fora da amostra. O original não estava (5,1 p.p. e superconfiante nos extremos).
- **Confiabilidade:** moderada. A melhora sobre o original e sobre a média da liga é estatisticamente comprovada, mas o ganho sobre a média da liga é pequeno (0,17 ponto por quarto), porque ainda não há histórico de equipe. O erro típico é de 6 pontos por quarto e 14,5 no jogo.
- **Melhores quartos:** 3º (MAE 5,96) e 2º (6,09, melhor Brier). O 4º é o mais disperso e o menos calibrado (ECE 4,5 p.p.).
- **Maior erro:** G League (8,13 por quarto) e NBA (7,39), ligas de pontuação alta.
- **Equipes com amostra confiável:** nenhuma. O máximo é 6 jogos; o modelo dá peso de 50% à equipe com 4 jogos e 83% com 20.
- **Ajustes com melhora comprovada:** limpeza dos dados, ancoragem na média da liga com encolhimento da equipe, dispersão da liga com escala calibrada e pesos ao vivo de 10/20/30%.
- **Ainda a desenvolver:** histórico mais longo (o plano pago permite o retroativo), gravar a temporada nos jogos, identificar quadra neutra, recalibrar k_team quando houver equipes com 20+ jogos e avaliar contra linhas reais de mercado, que hoje não existem na base.
