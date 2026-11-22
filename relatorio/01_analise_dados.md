# Etapa 1: análise exploratória dos dados

Fonte: `dados/teams.json` exportado do Firestore por `scripts/exportar_dados.py`. Gerado por `scripts/analise_dados.py`.

## 1. Estrutura e abrangência

| Item | Valor |
| --- | ---: |
| Documentos de equipe | 2346 |
| Entradas jogo-equipe | 4504 |
| Jogos únicos por gid | 2252 |
| Duplicatas entre fontes (mesmo jogo nas duas APIs) | 185 |
| Jogos inválidos (quarto 0 x 0 fora do padrão de tempos: zerados ou truncados) | 5 |
| Jogos únicos válidos (sem duplicatas e sem inválidos) | 2062 |
| Jogos com quartos válidos | 1628 |
| Jogos no formato de tempos (Q1 = Q3 = 0) | 434 |
| Período | 2026-11-14 a 2026-11-22 (9 dias) |
| Competições (após deduplicar) | 135 |
| Competições com 15+ jogos | 21 |
| Jogos da API-Sports / Basketball API | 2055 / 7 |
| Jogos femininos (pelo nome da liga) | 630 |

Campos por jogo de equipe: `gid, date, sortKey, cid, cname, home, oppId, oppName, pts[4], oppPts[4], ot, oppOt`. Não há temporada, posses, arremessos nem linhas de mercado. A temporada é descartada pelo coletor ao gravar a equipe.

## 2. Qualidade e integridade

| Verificação | Resultado |
| --- | ---: |
| Jogos duplicados pelo mesmo gid | 0 (o gid é a chave; cada jogo aparece uma vez por equipe) |
| Mesmo jogo gravado pelas duas fontes | 185 pares (8.2% dos gids) |
| Quartos ausentes ou incompletos | 0 |
| Quartos fora de 0 a 80 | 0 |
| Visões divergentes entre as duas equipes do jogo | 0 |
| Entradas sem a contrapartida no documento do adversário | 0 |
| Adversário sem documento no banco | 0 |
| Jogos inválidos gravados como encerrados | Superettan (Sweden) 2026-11-21: AIK Basket x Wetterbygden Stars [11, 28, 0, 0] / [21, 14, 0, 0]; B League (Japan) 2026-11-15: Shinshu x Ibaraki Robots [0, 0, 0, 0] / [0, 0, 0, 0]; NBA - G League (USA) 2026-11-16: Motor City Cruise x Noblesville Boom [27, 31, 28, 0] / [27, 24, 27, 0]; WBL Women (Netherlands) 2026-11-21: Binnenland W x Den Helder W [1, 8, 0, 0] / [7, 9, 0, 0]; NCAA Women (USA) 2026-11-15: Oklahoma Sooners W x Southern Jaguars W [0, 0, 0, 0] / [0, 0, 0, 0] |
| Jogos em tempos gravados como quartos | 434: NCAA (USA) (434) |

Exemplo do formato em tempos: Illinois x Sam Houston St. (2026-11-14), mandante [0, 45, 0, 63], visitante [0, 40, 0, 46]. O 1º tempo está no 2º quarto e o 2º tempo no 4º. Os totais de tempo e de jogo estão corretos; os de quarto, não.

**Impacto no sistema atual:** esses jogos entravam nas médias e na dispersão de referência de quarto. A dispersão global gravada em `meta/priors` para um quarto era 18,4 pontos, maior até que a do 1º tempo (17,6), o que é matematicamente incoerente para dados corretos. Como a maioria das ligas usa a dispersão global, as chances de Over do painel ficavam achatadas perto de 50%. Para times da NCAA masculina, o painel projetava 0 ponto no 1º e no 3º quarto.

## 3. Distribuição dos totais (soma dos dois times)

Quartos só com jogos de quartos válidos; tempos e jogo com todos os jogos deduplicados. "DP dentro da liga" é o desvio padrão depois de descontar a média de cada competição (só ligas com 15+ jogos): é a incerteza que sobra quando já se sabe a liga, e é a que importa para o modelo.

| Período | Jogos | Média | Mediana | DP bruto | DP dentro da liga | Variância explicada pela liga | P5 | P95 | Assimetria | Curtose |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1º quarto | 1628 | 39,5 | 39,0 | 10,1 | 7,8 | 55% | 24 | 57 | 0,51 | 1,02 |
| 2º quarto | 1628 | 39,2 | 38,0 | 10,3 | 7,7 | 57% | 23 | 58 | 0,46 | 0,43 |
| 3º quarto | 1628 | 39,3 | 39,0 | 9,9 | 7,8 | 53% | 25 | 57 | 0,66 | 1,05 |
| 4º quarto | 1628 | 39,3 | 39,0 | 9,7 | 7,8 | 49% | 25 | 57 | 0,58 | 0,88 |
| 1º tempo | 2062 | 77,2 | 76,0 | 16,9 | 11,8 | 60% | 52 | 108 | 0,55 | 0,67 |
| 2º tempo | 2062 | 78,5 | 77,0 | 15,9 | 11,9 | 54% | 56 | 105 | 0,80 | 1,80 |
| Tempo normal | 2062 | 155,8 | 154,0 | 29,4 | 18,7 | 67% | 114 | 209 | 0,87 | 1,68 |
| Com prorrogação | 2062 | 156,5 | 154,0 | 29,8 | 19,2 | 66% | 114 | 210 | 0,86 | 1,54 |

Leitura: a liga explica a maior parte da variância dos totais. O desvio que sobra dentro de uma liga, por quarto, fica em torno de 7,8 pontos, bem abaixo dos 18,4 que o sistema usava. Assimetria e curtose próximas de zero sustentam a aproximação normal usada nas chances de Over.

### Quartos: média e variância dentro da liga

| Quarto | Fatia média do total do jogo | IC 95% (±) | DP dentro da liga |
| --- | ---: | ---: | ---: |
| 1º quarto | 25,10% | 0,20 p.p. | 7,79 |
| 2º quarto | 24,87% | 0,19 p.p. | 7,67 |
| 3º quarto | 24,98% | 0,19 p.p. | 7,76 |
| 4º quarto | 25,05% | 0,21 p.p. | 7,85 |

Diferença de cada quarto para a média dos quatro quartos do mesmo jogo (teste pareado, aproximação normal):

| Quarto | Diferença média (pts) | z | p |
| --- | ---: | ---: | ---: |
| 1º quarto | 0,19 | 1,23 | 0.22 |
| 2º quarto | -0,11 | -0,73 | 0.47 |
| 3º quarto | -0,05 | -0,32 | 0.75 |
| 4º quarto | -0,03 | -0,20 | 0.84 |

## 4. Totais por competição (só ligas com 15+ jogos)

| Competição | Jogos | Média por quarto | DP por quarto | Média do jogo | DP do jogo | Saldo médio do mandante | Prorrogação |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NCAA (USA) | 434 | tempos | – | 149,7 | 18,2 | 15,1 | 4% |
| NCAA Women (USA) | 428 | 32,6 | 7,6 | 130,2 | 18,9 | 13,8 | 2% |
| NBA (USA) | 67 | 56,4 | 8,7 | 225,8 | 20,5 | 0,2 | 4% |
| NBA - G League (USA) | 47 | 57,7 | 10,8 | 230,7 | 27,8 | 0,2 | 6% |
| CBA Club Cup (China) | 34 | 42,7 | 8,5 | 170,9 | 21,3 | 1,1 | 0% |
| European Championship Women | 26 | 36,3 | 6,8 | 145,1 | 17,4 | -5,2 | 0% |
| B League (Japan) | 25 | 42,2 | 6,6 | 168,9 | 14,3 | 6,3 | 0% |
| NKL (Lithuania) | 25 | 42,9 | 7,8 | 171,5 | 16,9 | 5,2 | 0% |
| FIBA Europe Cup | 24 | 41,8 | 7,3 | 167,1 | 17,4 | 11,0 | 4% |
| Segunda FEB (Spain) | 23 | 40,6 | 7,8 | 162,4 | 17,6 | 4,5 | 9% |
| Euroleague (Europe) | 20 | 42,3 | 7,4 | 169,3 | 16,5 | 4,9 | 20% |
| Pro B (France) | 19 | 42,7 | 8,3 | 170,7 | 19,7 | 2,3 | 0% |
| TB2L (Turkey) | 18 | 36,2 | 7,8 | 144,9 | 19,1 | 6,1 | 6% |
| WCBA Women (China) | 17 | 38,0 | 7,7 | 151,9 | 13,4 | 5,6 | 0% |
| NBB (Brazil) | 17 | 38,0 | 7,3 | 152,0 | 14,2 | 0,1 | 6% |
| Pro A (Germany) | 17 | 37,4 | 7,5 | 149,6 | 15,0 | 6,6 | 0% |
| Liga Femenina Women (Argentina) | 16 | 33,0 | 6,3 | 131,8 | 14,2 | 2,6 | 0% |
| Eurocup (Europe) | 16 | 42,7 | 8,0 | 170,6 | 18,9 | 1,5 | 0% |
| W League Women (Japan) | 15 | 33,6 | 7,1 | 134,6 | 16,7 | 6,2 | 0% |
| Espoirs U21 (France) | 15 | 38,9 | 6,8 | 155,7 | 18,5 | 3,8 | 13% |
| Proliga (Portugal) | 15 | 38,9 | 7,9 | 155,7 | 13,2 | 7,1 | 0% |

114 competições têm menos de 15 jogos (744 jogos, 36% da base) e 45 têm menos de 5. Nenhuma conclusão é tirada sobre elas individualmente.

Masculino x feminino (quartos válidos): média por quarto 43,1 x 33,5 pontos (diferença 9,6, z = 44,7). Ligas femininas pontuam muito menos; misturá-las numa referência única distorce médias e dispersões.

## 5. Mandante x visitante

| Período | Jogos | Mandante | Visitante | Diferença | z | p |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1º quarto | 1628 | 20,6 | 18,9 | 1,71 | 8,09 | 6e-16 |
| 2º quarto | 1628 | 20,3 | 19,0 | 1,33 | 6,20 | 5.7e-10 |
| 3º quarto | 1628 | 20,3 | 19,0 | 1,39 | 6,50 | 8.2e-11 |
| 4º quarto | 1628 | 20,1 | 19,3 | 0,81 | 4,01 | 6.2e-05 |
| Tempo normal | 2062 | 81,5 | 74,2 | 7,31 | 15,13 | 1.1e-51 |

O mandante venceu 1311 de 2062 jogos (63.6%). Atenção: jogos em quadra neutra (copas, torneios) não são identificados pela API e entram como mando normal.

A vantagem do mandante desloca o **placar de cada time**, mas não necessariamente o **total**. Para Over/Under, o que interessa é se o total muda com o mando, o que é testado no backtest (Etapa 3).

## 6. Tamanho da amostra por equipe

| Jogos armazenados | Equipes |
| --- | ---: |
| 1 | 749 |
| 2 | 938 |
| 3 | 396 |
| 4 | 56 |
| 5 | 15 |
| 6 | 2 |

Nenhuma equipe tem 10 jogos ou mais (equipes com 10+: 0). Só 17 têm 5 ou mais. Com no máximo 6 jogos por equipe, **nenhuma amostra de equipe é confiável** para uma média própria: o erro padrão da média de um quarto com 4 jogos é cerca de 4 pontos. Isso define a estratégia de modelagem: partir da média da liga e ajustar pela equipe só na medida da evidência.

Equipes com mais jogos: New Orleans Pelicans (6); Memphis Grizzlies (6); New York Knicks (5); Milwaukee Bucks (5); Atenas (5); Chicago Bulls (5); Cleveland Cavaliers (5); SE Missouri State W (5); Houston Rockets (5); Utah Jazz (5).

## 7. Valores atípicos

Jogos com total do tempo normal a 3 desvios ou mais da média da própria liga: 3 (numa normal, o esperado seria cerca de 4).

| Jogo | Liga | Data | Total | z |
| --- | ---: | ---: | ---: | ---: |
| Washington State x Northwest | NCAA (USA) | 2026-11-14 | 210 | 3,3 |
| Notre Dame W x DePaul W | NCAA Women (USA) | 2026-11-14 | 192 | 3,3 |
| Gardner Webb W x East Tennessee St W | NCAA Women (USA) | 2026-11-18 | 73 | -3,0 |

Quartos com total abaixo de 10 pontos entre os jogos com quartos válidos: 2. Depois de excluir os jogos inválidos, os atípicos restantes são placares plausíveis (vitórias largas, ligas femininas de nível baixo) e foram mantidos.

## 8. Vieses temporais e temporadas

| Data | Jogos | Em tempos | Total menos média da liga |
| --- | ---: | ---: | ---: |
| 2026-11-14 | 420 | 98 | -0,10 |
| 2026-11-15 | 311 | 59 | -2,01 |
| 2026-11-16 | 65 | 12 | 0,80 |
| 2026-11-17 | 173 | 37 | 3,12 |
| 2026-11-18 | 222 | 65 | -1,14 |
| 2026-11-19 | 202 | 65 | 0,02 |
| 2026-11-20 | 214 | 52 | 0,89 |
| 2026-11-21 | 418 | 43 | 0,68 |
| 2026-11-22 | 37 | 3 | -4,52 |

A coleta começou em 2026-11-14: o plano gratuito bloqueia datas anteriores (backfill "blocked" nas duas fontes). O volume diário oscila com o calendário (NCAA concentra jogos em alguns dias). A coluna da direita não mostra deriva sistemática ao longo dos dias. **Temporadas:** todos os jogos são do início da temporada 2026-27; não há como comparar temporadas, e o início de temporada costuma ter mais variação (elencos novos), o que pode não se repetir adiante.

## 9. Conclusões objetivas

1. Base pequena e curta: 2062 jogos únicos em 9 dias, no máximo 6 jogos por equipe.
2. Defeitos graves de integridade: 5 jogos zerados ou truncados gravados como encerrados (excluídos) e 434 jogos da NCAA masculina estão em tempos, não em quartos. Eles contaminavam médias e dispersões de quarto. Corrigido no modelo (ver Etapa 4).
3. 185 jogos aparecem nas duas fontes com IDs diferentes. Não geram vazamento entre equipes (cada fonte tem seus próprios IDs), mas inflavam contagens e a dispersão global.
4. A liga explica a maior parte da variância dos totais; o desvio que sobra dentro da liga é de 7 a 8 pontos por quarto.
5. Ligas femininas pontuam bem menos por quarto; referência única global mistura populações diferentes.
6. Os quatro quartos têm médias estatisticamente iguais (diferenças abaixo de 0,25 ponto, p > 0,1) e dispersões parecidas dentro da liga (7,7 a 8,1; o 4º quarto é o mais disperso). Ajuste de média específico por quarto não se justifica.
8. O mando muda o placar de cada time (cerca de 1,3 ponto por quarto), o que importa para a divisão de pontos, não para o total.
7. Não há amostra de equipe confiável. Qualquer modelo precisa regredir à média da liga.
