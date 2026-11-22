# Etapas 3 e 4: backtest walk-forward e recalibragem

Gerado por `scripts/backtest_completo.py` a partir de `dados/teams.json`. Nenhum número foi digitado à mão.

## Protocolo

| Item | Valor |
| --- | ---: |
| Jogos na base (registros por gid) | 2252 |
| Duplicatas entre fontes descartadas | 185 |
| Jogos avaliados (a partir de 2026-11-15) | 1642 |
| Período de ajuste (escolha de parâmetros) | 2026-11-15 a 2026-11-18: 771 jogos |
| Período de teste (fora da amostra) | 2026-11-19 a 2026-11-22: 871 jogos |
| Linhas por período | 5 linhas sintéticas comuns a todos os modelos (sem linhas de mercado na base) |
| Reprodução do modelo original | idêntica ao código de produção em 217 previsões (diferença máx. 8.3e-07) |

O jogo de 2026-11-14 não é avaliado porque não havia nenhum jogo anterior. Jogos em tempos (NCAA masculina) entram só nos tempos e no jogo; jogos inválidos ficam de fora.

## Escolha dos parâmetros do v2 (só período de ajuste)

Grade de 84 combinações; critério: log loss médio dos 7 períodos. Melhores:

| Log loss | k_team | k_comp | k_sd |
| --- | ---: | ---: | ---: |
| 0,64101 | 4 | 3 | 40 |
| 0,64104 | 4 | 3 | 15 |
| 0,64105 | 2 | 3 | 40 |
| 0,64107 | 2 | 3 | 15 |
| 0,64122 | 2 | 3 | 5 |
| 0,64124 | 4 | 3 | 5 |

Escolhido: k_team = 4, k_comp = 3, k_sd = 40. O ganho entre as primeiras combinações é pequeno; a escolha é estável.

## Resultado fora da amostra (período de teste), quartos agrupados

MAE, RMSE e viés em pontos do total dos dois times no quarto. Viés positivo = projetou acima do real. "Acerto na linha central": lado (Over/Under) certo na linha da referência da liga. Brier e log loss: quanto menor, melhor (chute de 50% dá 0,25 e 0,693). ECE: distância média entre chance prevista e frequência observada. "DP dos z" perto de 1 e cobertura perto de 80% indicam dispersão bem dimensionada.

### Todos os jogos do teste

| Modelo | Jogos | MAE | RMSE | Viés | Acerto na linha central | Brier | Log loss | ECE (p.p.) | DP dos z | Cobertura 80% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Referência: média global | 708 | 7,87 | 10,10 | 0,25 | 54,3% | 0,2618 | 0,7548 | 12,4 | 1,01 | 81% |
| Referência: média da liga | 708 | 6,34 | 8,07 | -0,07 | 50,6% | 0,2301 | 0,6524 | 1,9 | 0,90 | 85% |
| Original (regra do painel: 1+ jogo, últimos 20) | 465 | 6,84 | 8,65 | 0,04 | 55,0% | 0,2398 | 0,6810 | 5,1 | 0,87 | 87% |
| Original (regra do backtest: 3+ jogos, últimos 10) | 31 | 7,55 | 9,14 | 0,56 | 56,9% | 0,2345 | 0,6596 | 7,2 | 1,06 | 81% |
| Frequência histórica (Freq. A/B do painel) | 465 | – | – | – | 57,4% | 0,2925 | 1,1683 | 18,1 | – | – |
| Original com dados limpos e dispersão correta | 464 | 6,81 | 8,62 | 0,11 | 55,3% | 0,2453 | 0,7000 | 9,5 | 1,13 | 75% |
| v2 só liga (sem ajuste de equipe) | 708 | 6,24 | 7,94 | 0,07 | 54,4% | 0,2253 | 0,6420 | 1,7 | 1,00 | 80% |
| v2 liga + equipe encolhida (escolhido) | 708 | 6,17 | 7,85 | 0,06 | 56,9% | 0,2229 | 0,6367 | 2,4 | 0,94 | 83% |
| v2 + peso de recência | 708 | 6,17 | 7,85 | 0,06 | 56,9% | 0,2229 | 0,6367 | 2,4 | 0,94 | 83% |
| v2 + amostra por mando | 708 | 6,21 | 7,90 | 0,07 | 55,6% | 0,2245 | 0,6403 | 2,2 | 0,94 | 82% |
| v2 + correção de viés | 708 | 6,17 | 7,85 | -0,09 | 58,0% | 0,2226 | 0,6362 | 2,0 | 0,94 | 83% |
| v2 + escala de dispersão | 708 | 6,17 | 7,85 | 0,06 | 56,9% | 0,2226 | 0,6362 | 1,8 | 1,00 | 80% |

### Só jogos em que o original do painel tem projeção (1+ jogo de cada equipe)

| Modelo | Jogos | MAE | RMSE | Viés | Acerto na linha central | Brier | Log loss | ECE (p.p.) | DP dos z | Cobertura 80% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Referência: média global | 465 | 8,28 | 10,71 | -0,50 | 53,2% | 0,2711 | 0,7906 | 13,8 | 1,07 | 79% |
| Referência: média da liga | 465 | 6,29 | 8,03 | 0,08 | 49,9% | 0,2295 | 0,6512 | 2,1 | 0,92 | 84% |
| Original (regra do painel: 1+ jogo, últimos 20) | 465 | 6,84 | 8,65 | 0,04 | 55,0% | 0,2398 | 0,6810 | 5,1 | 0,87 | 87% |
| Original (regra do backtest: 3+ jogos, últimos 10) | 31 | 7,55 | 9,14 | 0,56 | 56,9% | 0,2345 | 0,6596 | 7,2 | 1,06 | 81% |
| Frequência histórica (Freq. A/B do painel) | 465 | – | – | – | 57,4% | 0,2925 | 1,1683 | 18,1 | – | – |
| Original com dados limpos e dispersão correta | 464 | 6,81 | 8,62 | 0,11 | 55,3% | 0,2453 | 0,7000 | 9,5 | 1,13 | 75% |
| v2 só liga (sem ajuste de equipe) | 465 | 6,21 | 7,93 | 0,19 | 53,8% | 0,2255 | 0,6425 | 2,3 | 1,01 | 79% |
| v2 liga + equipe encolhida (escolhido) | 465 | 6,12 | 7,80 | 0,20 | 56,1% | 0,2221 | 0,6351 | 2,8 | 0,95 | 83% |
| v2 + peso de recência | 465 | 6,12 | 7,80 | 0,20 | 56,2% | 0,2221 | 0,6351 | 2,8 | 0,95 | 83% |
| v2 + amostra por mando | 465 | 6,17 | 7,86 | 0,19 | 55,6% | 0,2242 | 0,6397 | 2,5 | 0,95 | 82% |
| v2 + correção de viés | 465 | 6,11 | 7,79 | 0,05 | 57,2% | 0,2218 | 0,6344 | 2,3 | 0,95 | 83% |
| v2 + escala de dispersão | 465 | 6,12 | 7,80 | 0,20 | 56,1% | 0,2219 | 0,6345 | 2,6 | 1,01 | 80% |

### Só jogos em que o original do backtest avalia (3+ jogos de cada equipe)

| Modelo | Jogos | MAE | RMSE | Viés | Acerto na linha central | Brier | Log loss | ECE (p.p.) | DP dos z | Cobertura 80% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Referência: média global | 31 | 14,77 | 17,56 | -12,41 | 52,4% | 0,3686 | 1,2558 | 33,0 | 1,75 | 48% |
| Referência: média da liga | 31 | 7,82 | 9,82 | -0,15 | 50,8% | 0,2391 | 0,6711 | 1,7 | 1,11 | 77% |
| Original (regra do painel: 1+ jogo, últimos 20) | 31 | 7,55 | 9,14 | 0,56 | 56,9% | 0,2345 | 0,6596 | 7,2 | 1,06 | 81% |
| Original (regra do backtest: 3+ jogos, últimos 10) | 31 | 7,55 | 9,14 | 0,56 | 56,9% | 0,2345 | 0,6596 | 7,2 | 1,06 | 81% |
| Frequência histórica (Freq. A/B do painel) | 31 | – | – | – | 62,5% | 0,2537 | 0,7662 | 14,4 | – | – |
| Original com dados limpos e dispersão correta | 31 | 7,55 | 9,14 | 0,56 | 56,9% | 0,2376 | 0,6673 | 9,3 | 1,17 | 73% |
| v2 só liga (sem ajuste de equipe) | 31 | 7,51 | 9,46 | -0,60 | 53,2% | 0,2265 | 0,6428 | 2,9 | 1,16 | 73% |
| v2 liga + equipe encolhida (escolhido) | 31 | 7,24 | 8,98 | -0,08 | 58,1% | 0,2222 | 0,6329 | 2,6 | 1,07 | 80% |
| v2 + peso de recência | 31 | 7,25 | 8,98 | -0,08 | 58,1% | 0,2222 | 0,6328 | 3,2 | 1,07 | 80% |
| v2 + amostra por mando | 31 | 7,27 | 9,00 | -0,31 | 62,1% | 0,2214 | 0,6321 | 2,9 | 1,06 | 78% |
| v2 + correção de viés | 31 | 7,23 | 8,95 | -0,25 | 60,5% | 0,2211 | 0,6303 | 3,8 | 1,07 | 80% |
| v2 + escala de dispersão | 31 | 7,24 | 8,98 | -0,08 | 58,1% | 0,2224 | 0,6331 | 3,3 | 1,13 | 74% |

## Período inteiro avaliado (ajuste + teste), quartos agrupados

### Todos os jogos avaliados

| Modelo | Jogos | MAE | RMSE | Viés | Acerto na linha central | Brier | Log loss | ECE (p.p.) | DP dos z | Cobertura 80% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Referência: média global | 1306 | 7,94 | 10,15 | 0,26 | 53,7% | 0,2655 | 0,7660 | 13,2 | 1,03 | 80% |
| Referência: média da liga | 1306 | 6,35 | 8,04 | 0,10 | 51,1% | 0,2309 | 0,6541 | 2,0 | 0,91 | 85% |
| Original (regra do painel: 1+ jogo, últimos 20) | 580 | 6,92 | 8,80 | 0,15 | 55,2% | 0,2417 | 0,6889 | 6,0 | 0,90 | 86% |
| Original (regra do backtest: 3+ jogos, últimos 10) | 31 | 7,55 | 9,14 | 0,56 | 56,9% | 0,2345 | 0,6596 | 7,2 | 1,06 | 81% |
| Frequência histórica (Freq. A/B do painel) | 580 | – | – | – | 56,8% | 0,2986 | 1,2249 | 19,4 | – | – |
| Original com dados limpos e dispersão correta | 576 | 6,85 | 8,65 | 0,29 | 55,4% | 0,2467 | 0,7035 | 10,0 | 1,14 | 75% |
| v2 só liga (sem ajuste de equipe) | 1306 | 6,24 | 7,91 | 0,12 | 54,8% | 0,2260 | 0,6436 | 1,9 | 0,99 | 80% |
| v2 liga + equipe encolhida (escolhido) | 1306 | 6,19 | 7,85 | 0,14 | 56,4% | 0,2242 | 0,6397 | 2,2 | 0,94 | 83% |
| v2 + peso de recência | 1306 | 6,19 | 7,85 | 0,14 | 56,4% | 0,2242 | 0,6397 | 2,2 | 0,94 | 83% |
| v2 + amostra por mando | 1306 | 6,22 | 7,88 | 0,13 | 55,7% | 0,2254 | 0,6422 | 2,0 | 0,94 | 83% |
| v2 + correção de viés | 1306 | 6,18 | 7,85 | 0,04 | 57,3% | 0,2241 | 0,6394 | 1,8 | 0,94 | 83% |
| v2 + escala de dispersão | 1306 | 6,19 | 7,85 | 0,14 | 56,4% | 0,2241 | 0,6393 | 1,9 | 0,99 | 80% |

## Intervalos de confiança (bootstrap por jogo, 1.000 reamostragens, período de teste)

| Comparação | Métrica | Jogos | Diferença | IC 95% | Conclusão |
| --- | ---: | ---: | ---: | ---: | ---: |
| v2 menos orig | BRIER | 465 | -0,0177 | [-0,0222; -0,0133] | melhora comprovada |
| v2 menos orig | MAE | 465 | -0,7220 | [-0,8831; -0,5632] | melhora comprovada |
| v2 menos liga | BRIER | 708 | -0,0072 | [-0,0094; -0,0052] | melhora comprovada |
| v2 menos liga | MAE | 708 | -0,1697 | [-0,2292; -0,1156] | melhora comprovada |
| v2 menos v2_semequipe | BRIER | 708 | -0,0024 | [-0,0039; -0,0011] | melhora comprovada |
| v2 menos v2_semequipe | MAE | 708 | -0,0719 | [-0,1124; -0,0322] | melhora comprovada |
| v2_escala menos v2 | BRIER | 708 | -0,0002 | [-0,0004; -0,0001] | melhora comprovada |
| v2_vies menos v2 | BRIER | 708 | -0,0002 | [-0,0006; 0,0001] | sem diferença comprovada |
| v2_recencia menos v2 | MAE | 708 | 0,0007 | [-0,0006; 0,0020] | sem diferença comprovada |
| v2_mando menos v2 | MAE | 708 | 0,0379 | [0,0078; 0,0689] | piora comprovada |

Diferença negativa = o primeiro modelo erra menos.

## Por período (teste)

| Período | Jogos | MAE v2 | Viés v2 | Brier v2 | ECE v2 | DP dos z v2 | MAE liga | Brier liga | Original: jogos: MAE orig / MAE v2 | Brier orig / v2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1º quarto | 708 | 6,38 | -0,36 | 0,2258 | 1,4 | 0,97 | 6,55 | 0,2321 | 465: 7,08 / 6,22 | 0,2452 / 0,2255 |
| 2º quarto | 708 | 6,09 | -0,22 | 0,2205 | 2,7 | 0,94 | 6,28 | 0,2297 | 465: 6,39 / 6,00 | 0,2283 / 0,2198 |
| 3º quarto | 708 | 5,96 | 0,22 | 0,2229 | 2,4 | 0,91 | 6,10 | 0,2291 | 465: 6,94 / 6,06 | 0,2475 / 0,2207 |
| 4º quarto | 708 | 6,24 | 0,61 | 0,2223 | 4,5 | 0,94 | 6,42 | 0,2293 | 465: 6,94 / 6,19 | 0,2382 / 0,2225 |
| 1º tempo | 871 | 9,26 | -1,33 | 0,2220 | 3,7 | 0,91 | 9,59 | 0,2308 | 589: 9,59 / 8,81 | 0,2297 / 0,2194 |
| 2º tempo | 871 | 9,06 | 0,33 | 0,2234 | 2,5 | 0,91 | 9,25 | 0,2289 | 589: 10,49 / 9,05 | 0,2505 / 0,2214 |
| Tempo normal | 871 | 14,47 | -1,00 | 0,2103 | 2,6 | 0,91 | 15,08 | 0,2211 | 589: 15,29 / 13,96 | 0,2194 / 0,2086 |

## Por competição (teste, quartos; ligas com 15+ jogos avaliados)

| Competição | Jogos | MAE v2 | Viés v2 | Brier v2 | MAE liga | Brier liga | Original: jogos / MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NCAA Women (USA) | 177 | 5,52 | 0,26 | 0,2195 | 5,65 | 0,2242 | 144 / 6,30 |
| NBA (USA) | 31 | 7,39 | 0,95 | 0,2332 | 7,55 | 0,2391 | 31 / 7,65 |
| CBA Club Cup (China) | 26 | 6,66 | -0,59 | 0,2214 | 7,07 | 0,2380 | 18 / 7,29 |
| NBA - G League (USA) | 22 | 8,13 | -1,44 | 0,2239 | 8,26 | 0,2284 | 21 / 9,42 |
| NKL (Lithuania) | 17 | 5,83 | 0,23 | 0,2172 | 5,89 | 0,2241 | 15 / 6,49 |

## Por equipe (período inteiro, quartos; equipes com 4+ jogos avaliados)

| Equipe | Liga | Jogos | MAE v2 | Viés v2 | MAE liga |
| --- | ---: | ---: | ---: | ---: | ---: |
| New Orleans Pelicans | NBA (USA) | 5 | 5,47 | 0,27 | 5,91 |
| Dallas Mavericks | NBA (USA) | 5 | 6,39 | -0,69 | 7,30 |
| Memphis Grizzlies | NBA (USA) | 5 | 8,09 | -1,20 | 7,83 |
| Minnesota Timberwolves | NBA (USA) | 5 | 6,80 | 3,51 | 6,86 |
| Vienna Basket | Super Cup (Austria) | 5 | 6,32 | -0,81 | 6,32 |
| Philadelphia 76ers | NBA (USA) | 5 | 9,48 | -7,78 | 11,02 |
| Boston Celtics | NBA (USA) | 5 | 5,96 | 3,25 | 7,25 |
| Toronto Raptors | NBA (USA) | 5 | 5,48 | 3,30 | 7,28 |
| Washington Wizards | NBA (USA) | 5 | 8,44 | -0,61 | 8,58 |
| Milwaukee Bucks | NBA (USA) | 5 | 8,36 | -6,64 | 10,94 |
| Sacramento Kings | NBA (USA) | 5 | 4,66 | 2,47 | 5,53 |
| Capital City Go-Go | NBA - G League (USA) | 4 | 7,05 | 0,07 | 6,16 |
| Denver Nuggets | NBA (USA) | 4 | 5,54 | -0,76 | 5,35 |
| Cleveland Cavaliers | NBA (USA) | 4 | 8,07 | -4,17 | 7,84 |
| Brooklyn Nets | NBA (USA) | 4 | 5,50 | -3,57 | 5,35 |
| Detroit Pistons | NBA (USA) | 4 | 7,26 | 0,12 | 8,19 |
| Chicago Bulls | NBA (USA) | 4 | 6,79 | 0,24 | 6,15 |
| Panathinaikos | Basket League (Greece) | 4 | 4,53 | 2,91 | 4,50 |
| SE Missouri State W | NCAA Women (USA) | 4 | 5,36 | -2,13 | 5,33 |
| Windy City Bulls | NBA - G League (USA) | 4 | 7,89 | -1,78 | 8,73 |
| Valley Suns | NBA - G League (USA) | 4 | 9,94 | -4,46 | 8,26 |
| Rio Grande Valley Vipers | NBA - G League (USA) | 4 | 11,08 | -1,43 | 11,24 |
| Phoenix Suns | NBA (USA) | 4 | 6,44 | -1,13 | 5,68 |
| Los Angeles Lakers | NBA (USA) | 4 | 7,87 | 0,70 | 7,32 |
| Los Angeles Clippers | NBA (USA) | 4 | 7,45 | -0,47 | 6,76 |

38 equipes têm 4 ou mais jogos avaliados; nenhuma tem amostra suficiente para conclusão individual (com 4 jogos x 4 quartos, o erro padrão do MAE de uma equipe passa de 1 ponto).

## Por tamanho da amostra (teste, quartos): menor número de jogos anteriores entre as duas equipes

| Jogos anteriores | Jogos | MAE v2 | Brier v2 | MAE liga | Brier liga | MAE original | Brier original |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 244 | 6,26 | 0,2241 | 6,43 | 0,2310 | 11,50 | 0,4826 |
| 1 | 349 | 5,92 | 0,2222 | 6,04 | 0,2282 | 6,80 | 0,2417 |
| 2 | 84 | 6,56 | 0,2222 | 6,79 | 0,2318 | 6,67 | 0,2312 |
| 3 ou mais | 31 | 7,24 | 0,2222 | 7,82 | 0,2391 | 7,55 | 0,2345 |

## Por faixa de total previsto (teste, quartos)

Faixa medida em desvios da média da liga: o v2 projeta abaixo, perto ou acima da liga.

| Faixa | Jogos | MAE v2 | Viés v2 | Brier v2 | Viés original (mesma faixa) |
| --- | ---: | ---: | ---: | ---: | ---: |
| abaixo da liga | 221 | 6,15 | 0,39 | 0,2149 | -5,18 |
| perto da liga | 697 | 6,15 | 0,05 | 0,2252 | 0,17 |
| acima da liga | 203 | 6,33 | -0,19 | 0,2138 | 4,90 |

## Masculino x feminino (teste, quartos)

| Gênero | Jogos | MAE v2 | Viés v2 | Brier v2 | MAE liga |
| --- | ---: | ---: | ---: | ---: | ---: |
| Masculino | 410 | 6,37 | 0,41 | 0,2238 | 6,55 |
| Feminino | 298 | 5,90 | -0,42 | 0,2216 | 6,06 |

## Mandante x visitante: pontos de cada time (teste, quartos)

Para o total o mando quase não importa; para a divisão dos pontos, sim. Comparação da projeção de pontos de cada time com e sem a vantagem média do mandante na liga (aprendida só com jogos anteriores).

| Projeção de pontos | Casos | MAE mandante | MAE visitante |
| --- | ---: | ---: | ---: |
| sem vantagem do mandante | 2832 | 4,61 | 4,65 |
| com vantagem do mandante | 2832 | 4,62 | 4,58 |

## Calibração das probabilidades (teste, quartos, todas as linhas)

**v2 liga + equipe encolhida (escolhido)** (2832 previsões, 708 jogos; ECE 2,4 p.p.)

| Faixa prevista | Casos | Média prevista | Aconteceu | Diferença (p.p.) |
| --- | ---: | ---: | ---: | ---: |
| 0–10% | 2 | 9,4% | 50,0% | 40,6 |
| 10–20% | 76 | 17,2% | 18,4% | 1,2 |
| 20–30% | 1081 | 26,7% | 22,5% | -4,2 |
| 30–40% | 2778 | 35,0% | 30,7% | -4,3 |
| 40–50% | 2973 | 44,8% | 42,4% | -2,4 |
| 50–60% | 3024 | 55,0% | 53,7% | -1,3 |
| 60–70% | 2901 | 65,0% | 65,7% | 0,7 |
| 70–80% | 1251 | 73,6% | 76,6% | 3,0 |
| 80–90% | 66 | 82,6% | 89,4% | 6,8 |
| 90–100% | 8 | 93,7% | 100,0% | 6,3 |

**Original (regra do painel: 1+ jogo, últimos 20)** (1860 previsões, 465 jogos; ECE 5,1 p.p.)

| Faixa prevista | Casos | Média prevista | Aconteceu | Diferença (p.p.) |
| --- | ---: | ---: | ---: | ---: |
| 0–10% | 193 | 6,3% | 29,5% | 23,2 |
| 10–20% | 447 | 15,2% | 29,5% | 14,3 |
| 20–30% | 725 | 25,4% | 33,1% | 7,7 |
| 30–40% | 1332 | 35,5% | 34,6% | -0,9 |
| 40–50% | 1905 | 45,0% | 44,1% | -0,9 |
| 50–60% | 2097 | 54,5% | 51,8% | -2,7 |
| 60–70% | 1319 | 64,4% | 59,0% | -5,4 |
| 70–80% | 713 | 74,5% | 64,2% | -10,3 |
| 80–90% | 389 | 84,6% | 70,4% | -14,2 |
| 90–100% | 180 | 94,2% | 78,9% | -15,3 |

**Frequência histórica (Freq. A/B do painel)** (1860 previsões, 465 jogos; ECE 18,1 p.p.)

| Faixa prevista | Casos | Média prevista | Aconteceu | Diferença (p.p.) |
| --- | ---: | ---: | ---: | ---: |
| 0–10% | 1994 | 0,0% | 31,7% | 31,7 |
| 10–20% | 119 | 16,1% | 32,8% | 16,7 |
| 20–30% | 816 | 25,0% | 42,8% | 17,7 |
| 30–40% | 127 | 33,6% | 48,0% | 14,4 |
| 40–50% | 80 | 42,4% | 40,0% | -2,4 |
| 50–60% | 3416 | 50,2% | 48,7% | -1,5 |
| 60–70% | 126 | 66,2% | 54,0% | -12,2 |
| 70–80% | 727 | 74,9% | 61,5% | -13,4 |
| 80–90% | 110 | 83,8% | 65,5% | -18,3 |
| 90–100% | 1785 | 100,0% | 62,0% | -38,0 |

## Modo Ao vivo: peso do ritmo observado

Para cada jogo com quartos válidos, depois de 1, 2 ou 3 quartos, projeta o total do tempo normal e o próximo quarto. O peso do ritmo (0 = ignora o jogo, 1 = confia só no ritmo) é escolhido no período de ajuste e conferido no teste. Base pré-jogo: v2. Referência: pesos atuais de 20/30/40%.

| Momento | Peso do ritmo | Jogos ajuste | MAE final (ajuste) | Jogos teste | MAE final (teste) | MAE próximo quarto (teste) | DP dos z final (teste) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| após 1º quarto | 0% | 598 | 12,51 | 708 | 11,97 | 6,09 | 1,06 |
| após 1º quarto | 10% (melhor no ajuste) | 598 | 12,25 | 708 | 11,76 | 6,03 | 1,04 |
| após 1º quarto | 20% (atual) | 598 | 12,26 | 708 | 11,89 | 6,04 | 1,05 |
| após 1º quarto | 30% | 598 | 12,54 | 708 | 12,26 | 6,11 | 1,08 |
| após 1º quarto | 40% | 598 | 13,05 | 708 | 12,93 | 6,22 | 1,14 |
| após 1º quarto | 50% | 598 | 13,78 | 708 | 13,84 | 6,43 | 1,22 |
| após 1º quarto | 70% | 598 | 15,83 | 708 | 16,24 | 7,01 | 1,43 |
| após 1º quarto | 100% | 598 | 19,92 | 708 | 20,63 | 8,17 | 1,82 |
| após 2º quarto | 0% | 598 | 9,76 | 708 | 9,13 | 5,96 | 0,99 |
| após 2º quarto | 10% | 598 | 9,55 | 708 | 8,93 | 5,87 | 0,97 |
| após 2º quarto | 20% (melhor no ajuste) | 598 | 9,45 | 708 | 8,82 | 5,83 | 0,95 |
| após 2º quarto | 30% (atual) | 598 | 9,49 | 708 | 8,82 | 5,82 | 0,95 |
| após 2º quarto | 40% | 598 | 9,65 | 708 | 8,94 | 5,84 | 0,96 |
| após 2º quarto | 50% | 598 | 9,91 | 708 | 9,15 | 5,91 | 0,98 |
| após 2º quarto | 70% | 598 | 10,61 | 708 | 9,83 | 6,17 | 1,04 |
| após 2º quarto | 100% | 598 | 12,16 | 708 | 11,34 | 6,78 | 1,20 |
| após 3º quarto | 0% | 598 | 6,60 | 708 | 6,24 | 6,24 | 0,94 |
| após 3º quarto | 10% | 598 | 6,53 | 708 | 6,19 | 6,19 | 0,93 |
| após 3º quarto | 20% | 598 | 6,50 | 708 | 6,17 | 6,17 | 0,92 |
| após 3º quarto | 30% (melhor no ajuste) | 598 | 6,49 | 708 | 6,17 | 6,17 | 0,92 |
| após 3º quarto | 40% (atual) | 598 | 6,51 | 708 | 6,19 | 6,19 | 0,92 |
| após 3º quarto | 50% | 598 | 6,54 | 708 | 6,23 | 6,23 | 0,93 |
| após 3º quarto | 70% | 598 | 6,68 | 708 | 6,37 | 6,37 | 0,95 |
| após 3º quarto | 100% | 598 | 7,05 | 708 | 6,74 | 6,74 | 1,01 |

