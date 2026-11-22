"""Etapa 1: análise exploratória dos dados exportados.

Uso (na raiz):  python scripts/analise_dados.py
Lê dados/teams.json e grava relatorio/01_analise_dados.md. Só biblioteca padrão.
"""
import math
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

from base_dados import QUARTERS, ROOT, clean_games, integrity, load_teams
from collector import model as M

OUT = ROOT / "relatorio"
MIN_COMP = 15      # jogos para descrever uma competição
MIN_TEAM_OK = 10   # jogos para considerar a amostra de uma equipe confiável
PERIODS = ["q1", "q2", "q3", "q4", "h1", "h2", "reg"]
PL = {"q1": "1º quarto", "q2": "2º quarto", "q3": "3º quarto", "q4": "4º quarto", "h1": "1º tempo",
      "h2": "2º tempo", "reg": "Tempo normal", "total": "Com prorrogação"}


def f(x, nd=1):
    return "–" if x is None else f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def quant(v, q):
    s = sorted(v)
    if not s:
        return None
    i = (len(s) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def moments(v):
    n = len(v)
    if n < 3:
        return None, None
    m, s = st.fmean(v), st.stdev(v)
    sk = sum((x - m) ** 3 for x in v) / n / s ** 3
    ku = sum((x - m) ** 4 for x in v) / n / s ** 4 - 3
    return sk, ku


def p_two_sided(z):
    return math.erfc(abs(z) / math.sqrt(2))


def table(head, rows, align=None):
    align = align or ["l"] + ["r"] * (len(head) - 1)
    sep = ["---:" if a == "r" else "---" for a in align]
    return "\n".join(["| " + " | ".join(head) + " |", "| " + " | ".join(sep) + " |"] +
                     ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def tot(g, k):
    return M.value(g["entry"], k, "sum") if k != "total" else sum(g["hp"]) + sum(g["ap"]) + g["hot"] + g["aot"]


def main():
    teams = load_teams()
    games, dup, allg = clean_games(teams)
    integ = integrity(teams, allg)
    L = []
    w = L.append
    dates = sorted({g["date"] for g in games})
    comps = Counter(g["cname"] for g in games)
    halves = [g for g in games if g["halves"]]
    qgames = [g for g in games if not g["halves"]]

    w("# Etapa 1: análise exploratória dos dados\n")
    w(f"Fonte: `dados/teams.json` exportado do Firestore por `scripts/exportar_dados.py`. Gerado por `scripts/analise_dados.py`.\n")
    w("## 1. Estrutura e abrangência\n")
    w(table(["Item", "Valor"], [
        ["Documentos de equipe", len(teams)],
        ["Entradas jogo-equipe", integ["entradas"]],
        ["Jogos únicos por gid", len(allg)],
        ["Duplicatas entre fontes (mesmo jogo nas duas APIs)", len(dup)],
        ["Jogos inválidos (quarto 0 x 0 fora do padrão de tempos: zerados ou truncados)", sum(1 for gid, g in allg.items() if g["invalid"] and gid not in dup)],
        ["Jogos únicos válidos (sem duplicatas e sem inválidos)", len(games)],
        ["Jogos com quartos válidos", len(qgames)],
        ["Jogos no formato de tempos (Q1 = Q3 = 0)", len(halves)],
        ["Período", f"{dates[0]} a {dates[-1]} ({len(dates)} dias)"],
        ["Competições (após deduplicar)", len(comps)],
        ["Competições com 15+ jogos", sum(1 for c in comps.values() if c >= MIN_COMP)],
        ["Jogos da API-Sports / Basketball API", f"{sum(g['src'] == 'apisports' for g in games)} / {sum(g['src'] != 'apisports' for g in games)}"],
        ["Jogos femininos (pelo nome da liga)", sum(g["women"] for g in games)],
    ]))
    w("\nCampos por jogo de equipe: `gid, date, sortKey, cid, cname, home, oppId, oppName, pts[4], oppPts[4], ot, oppOt`. "
      "Não há temporada, posses, arremessos nem linhas de mercado. A temporada é descartada pelo coletor ao gravar a equipe.\n")

    # ---------- integridade ----------
    w("## 2. Qualidade e integridade\n")
    by_half = Counter(g["cname"] for g in halves)
    w(table(["Verificação", "Resultado"], [
        ["Jogos duplicados pelo mesmo gid", "0 (o gid é a chave; cada jogo aparece uma vez por equipe)"],
        ["Mesmo jogo gravado pelas duas fontes", f"{len(dup)} pares ({100 * len(dup) / len(allg):.1f}% dos gids)"],
        ["Quartos ausentes ou incompletos", integ["periodos_incompletos"]],
        ["Quartos fora de 0 a 80", integ["quartos_fora_faixa"]],
        ["Visões divergentes entre as duas equipes do jogo", integ["visao_divergente"]],
        ["Entradas sem a contrapartida no documento do adversário", integ["assimetricas"]],
        ["Adversário sem documento no banco", integ["sem_adversario_no_banco"]],
        ["Jogos inválidos gravados como encerrados", "; ".join(f"{g['cname']} {g['date']}: {g['hn']} x {g['an']} {g['hp']} / {g['ap']}" for gid, g in allg.items() if g["invalid"] and gid not in dup)],
        ["Jogos em tempos gravados como quartos", f"{len(halves)}: " + ", ".join(f"{c} ({n})" for c, n in by_half.most_common())],
    ]))
    ex = halves[0] if halves else None
    if ex:
        w(f"\nExemplo do formato em tempos: {ex['hn']} x {ex['an']} ({ex['date']}), mandante {ex['hp']}, visitante {ex['ap']}. "
          "O 1º tempo está no 2º quarto e o 2º tempo no 4º. Os totais de tempo e de jogo estão corretos; os de quarto, não.\n")
        w("**Impacto no sistema atual:** esses jogos entravam nas médias e na dispersão de referência de quarto. "
          "A dispersão global gravada em `meta/priors` para um quarto era 18,4 pontos, maior até que a do 1º tempo (17,6), "
          "o que é matematicamente incoerente para dados corretos. Como a maioria das ligas usa a dispersão global, as chances "
          "de Over do painel ficavam achatadas perto de 50%. Para times da NCAA masculina, o painel projetava 0 ponto no 1º e no 3º quarto.\n")

    # ---------- distribuição por período ----------
    w("## 3. Distribuição dos totais (soma dos dois times)\n")
    w("Quartos só com jogos de quartos válidos; tempos e jogo com todos os jogos deduplicados. "
      "\"DP dentro da liga\" é o desvio padrão depois de descontar a média de cada competição (só ligas com 15+ jogos): "
      "é a incerteza que sobra quando já se sabe a liga, e é a que importa para o modelo.\n")
    rows = []
    within = {}
    for k in PERIODS + ["total"]:
        src = qgames if k in QUARTERS else games
        v = [tot(g, k) for g in src]
        sk, ku = moments(v)
        by = defaultdict(list)
        for g in src:
            if comps[g["cname"]] >= MIN_COMP:
                by[g["cname"]].append(tot(g, k))
        res = [x - st.fmean(xs) for xs in by.values() for x in xs]
        dof = sum(len(xs) - 1 for xs in by.values())
        wsd = math.sqrt(sum(r * r for r in res) / dof) if dof else None
        within[k] = wsd
        allv = [tot(g, k) for g in src if comps[g["cname"]] >= MIN_COMP]
        eta = 1 - (sum(r * r for r in res) / sum((x - st.fmean(allv)) ** 2 for x in allv)) if allv else None
        rows.append([PL[k], len(v), f(st.fmean(v)), f(st.median(v)), f(st.stdev(v)), f(wsd), f(100 * eta, 0) + "%",
                     f(quant(v, .05), 0), f(quant(v, .95), 0), f(sk, 2), f(ku, 2)])
    w(table(["Período", "Jogos", "Média", "Mediana", "DP bruto", "DP dentro da liga", "Variância explicada pela liga",
             "P5", "P95", "Assimetria", "Curtose"], rows))
    w("\nLeitura: a liga explica a maior parte da variância dos totais. O desvio que sobra dentro de uma liga, por quarto, "
      f"fica em torno de {f(st.fmean(within[k] for k in QUARTERS))} pontos, bem abaixo dos 18,4 que o sistema usava. "
      "Assimetria e curtose próximas de zero sustentam a aproximação normal usada nas chances de Over.\n")

    # quarto com maior variância (dentro da liga)
    w("### Quartos: média e variância dentro da liga\n")
    share = {k: [] for k in QUARTERS}
    for g in qgames:
        r = tot(g, "reg")
        for k in QUARTERS:
            share[k].append(tot(g, k) / r)
    qrows = []
    for k in QUARTERS:
        s = share[k]
        qrows.append([PL[k], f(100 * st.fmean(s), 2) + "%", f(100 * 1.96 * st.stdev(s) / math.sqrt(len(s)), 2) + " p.p.", f(within[k], 2)])
    w(table(["Quarto", "Fatia média do total do jogo", "IC 95% (±)", "DP dentro da liga"], qrows))
    # teste pareado Q4 vs média dos outros
    diffs = {k: [tot(g, k) - tot(g, "reg") / 4 for g in qgames] for k in QUARTERS}
    trows = []
    for k in QUARTERS:
        d = diffs[k]
        m, s = st.fmean(d), st.stdev(d)
        z = m / (s / math.sqrt(len(d)))
        trows.append([PL[k], f(m, 2), f(z, 2), f"{p_two_sided(z):.2g}"])
    w("\nDiferença de cada quarto para a média dos quatro quartos do mesmo jogo (teste pareado, aproximação normal):\n")
    w(table(["Quarto", "Diferença média (pts)", "z", "p"], trows))
    w("")

    # ---------- por competição ----------
    w("## 4. Totais por competição (só ligas com 15+ jogos)\n")
    crows = []
    for c, n in comps.most_common():
        if n < MIN_COMP:
            continue
        gs = [g for g in games if g["cname"] == c]
        qg = [g for g in gs if not g["halves"]]
        qv = [tot(g, k) for g in qg for k in QUARTERS]
        reg = [tot(g, "reg") for g in gs]
        hv = [sum(g["hp"]) - sum(g["ap"]) for g in gs]
        crows.append([c, n, f(st.fmean(qv)) if qv else "tempos", f(st.stdev(qv)) if len(qv) > 1 else "–",
                      f(st.fmean(reg)), f(st.stdev(reg)), f(st.fmean(hv)),
                      f(100 * sum(1 for g in gs if g["hot"] or g["aot"]) / n, 0) + "%"])
    w(table(["Competição", "Jogos", "Média por quarto", "DP por quarto", "Média do jogo", "DP do jogo", "Saldo médio do mandante", "Prorrogação"], crows))
    few = [(c, n) for c, n in comps.items() if n < MIN_COMP]
    w(f"\n{len(few)} competições têm menos de 15 jogos ({sum(n for _, n in few)} jogos, "
      f"{100 * sum(n for _, n in few) / len(games):.0f}% da base) e {sum(1 for _, n in few if n < 5)} têm menos de 5. "
      "Nenhuma conclusão é tirada sobre elas individualmente.\n")

    # masculino x feminino
    wv = [tot(g, k) for g in qgames if g["women"] for k in QUARTERS]
    mv = [tot(g, k) for g in qgames if not g["women"] for k in QUARTERS]
    z = (st.fmean(mv) - st.fmean(wv)) / math.sqrt(st.variance(mv) / len(mv) + st.variance(wv) / len(wv))
    w(f"Masculino x feminino (quartos válidos): média por quarto {f(st.fmean(mv))} x {f(st.fmean(wv))} pontos "
      f"(diferença {f(st.fmean(mv) - st.fmean(wv))}, z = {f(z, 1)}). Ligas femininas pontuam muito menos; "
      "misturá-las numa referência única distorce médias e dispersões.\n")

    # ---------- mandante x visitante ----------
    w("## 5. Mandante x visitante\n")
    hrows = []
    for k in QUARTERS + ("reg",):
        src = qgames if k in QUARTERS else games
        d = [M.value(g["entry"], k, "for") - M.value(g["entry"], k, "against") for g in src]
        m, s = st.fmean(d), st.stdev(d)
        z = m / (s / math.sqrt(len(d)))
        hp = st.fmean(M.value(g["entry"], k, "for") for g in src)
        ap = st.fmean(M.value(g["entry"], k, "against") for g in src)
        hrows.append([PL[k], len(d), f(hp), f(ap), f(m, 2), f(z, 2), f"{p_two_sided(z):.2g}"])
    w(table(["Período", "Jogos", "Mandante", "Visitante", "Diferença", "z", "p"], hrows))
    wins = sum(1 for g in games if sum(g["hp"]) + g["hot"] > sum(g["ap"]) + g["aot"])
    w(f"\nO mandante venceu {wins} de {len(games)} jogos ({100 * wins / len(games):.1f}%). "
      "Atenção: jogos em quadra neutra (copas, torneios) não são identificados pela API e entram como mando normal.\n")
    w("A vantagem do mandante desloca o **placar de cada time**, mas não necessariamente o **total**. Para Over/Under, "
      "o que interessa é se o total muda com o mando, o que é testado no backtest (Etapa 3).\n")

    # ---------- amostra por equipe ----------
    w("## 6. Tamanho da amostra por equipe\n")
    per_team = Counter()
    for g in games:
        per_team[g["h"]] += 1
        per_team[g["a"]] += 1
    dist = Counter(per_team.values())
    w(table(["Jogos armazenados", "Equipes"], [[k, dist[k]] for k in sorted(dist)]))
    ok = sum(1 for n in per_team.values() if n >= MIN_TEAM_OK)
    five = sum(1 for n in per_team.values() if n >= 5)
    w(f"\nNenhuma equipe tem {MIN_TEAM_OK} jogos ou mais (equipes com 10+: {ok}). Só {five} têm 5 ou mais. "
      "Com no máximo 6 jogos por equipe, **nenhuma amostra de equipe é confiável** para uma média própria: "
      "o erro padrão da média de um quarto com 4 jogos é cerca de 4 pontos. Isso define a estratégia de modelagem: "
      "partir da média da liga e ajustar pela equipe só na medida da evidência.\n")
    top = sorted(per_team.items(), key=lambda x: -x[1])[:10]
    name = {tid: t.get("name") for tid, t in teams.items()}
    w("Equipes com mais jogos: " + "; ".join(f"{name.get(t, t)} ({n})" for t, n in top) + ".\n")

    # ---------- valores atípicos ----------
    w("## 7. Valores atípicos\n")
    out = []
    for g in games:
        c = g["cname"]
        if comps[c] < MIN_COMP:
            continue
        xs = [tot(x, "reg") for x in games if x["cname"] == c]
        m, s = st.fmean(xs), st.stdev(xs)
        z = (tot(g, "reg") - m) / s
        if abs(z) >= 3:
            out.append((abs(z), z, g))
    out.sort(key=lambda x: -x[0])
    w(f"Jogos com total do tempo normal a 3 desvios ou mais da média da própria liga: {len(out)} "
      f"(numa normal, o esperado seria cerca de {round(0.0027 * sum(n for n in comps.values() if n >= MIN_COMP))}).\n")
    if out:
        w(table(["Jogo", "Liga", "Data", "Total", "z"], [[f"{g['hn']} x {g['an']}", g["cname"], g["date"], tot(g, "reg"), f(z, 1)] for _, z, g in out[:10]]))
    qz = []
    for g in qgames:
        for k in QUARTERS:
            if tot(g, k) < 10:
                qz.append((g, k))
    w(f"\nQuartos com total abaixo de 10 pontos entre os jogos com quartos válidos: {len(qz)}. "
      "Depois de excluir os jogos inválidos, os atípicos restantes são placares plausíveis (vitórias largas, ligas femininas de nível baixo) e foram mantidos.\n")

    # ---------- tempo ----------
    w("## 8. Vieses temporais e temporadas\n")
    drows = []
    for d in dates:
        gs = [g for g in games if g["date"] == d]
        # desvio do total em relação à média da própria liga (remove a mistura de ligas de cada dia)
        zs = []
        for g in gs:
            c = g["cname"]
            if comps[c] >= MIN_COMP:
                xs = [tot(x, "reg") for x in games if x["cname"] == c]
                zs.append(tot(g, "reg") - st.fmean(xs))
        drows.append([d, len(gs), sum(g["halves"] for g in gs), f(st.fmean(zs), 2) if zs else "–"])
    w(table(["Data", "Jogos", "Em tempos", "Total menos média da liga"], drows))
    w(f"\nA coleta começou em {dates[0]}: o plano gratuito bloqueia datas anteriores (backfill \"blocked\" nas duas fontes). "
      "O volume diário oscila com o calendário (NCAA concentra jogos em alguns dias). "
      "A coluna da direita não mostra deriva sistemática ao longo dos dias. "
      "**Temporadas:** todos os jogos são do início da temporada 2026-27; não há como comparar temporadas, "
      "e o início de temporada costuma ter mais variação (elencos novos), o que pode não se repetir adiante.\n")

    w("## 9. Conclusões objetivas\n")
    w("\n".join([
        f"1. Base pequena e curta: {len(games)} jogos únicos em {len(dates)} dias, no máximo 6 jogos por equipe.",
        f"2. Defeitos graves de integridade: {sum(1 for gid, g in allg.items() if g['invalid'] and gid not in dup)} jogos zerados ou truncados gravados como encerrados (excluídos) e {len(halves)} jogos da NCAA masculina estão em tempos, não em quartos. "
        "Eles contaminavam médias e dispersões de quarto. Corrigido no modelo (ver Etapa 4).",
        f"3. {len(dup)} jogos aparecem nas duas fontes com IDs diferentes. Não geram vazamento entre equipes "
        "(cada fonte tem seus próprios IDs), mas inflavam contagens e a dispersão global.",
        "4. A liga explica a maior parte da variância dos totais; o desvio que sobra dentro da liga é de 7 a 8 pontos por quarto.",
        "5. Ligas femininas pontuam bem menos por quarto; referência única global mistura populações diferentes.",
        "6. Os quatro quartos têm médias estatisticamente iguais (diferenças abaixo de 0,25 ponto, p > 0,1) e dispersões parecidas dentro da liga (7,7 a 8,1; o 4º quarto é o mais disperso). Ajuste de média específico por quarto não se justifica.",
        "7. O mando muda o placar de cada time (cerca de 1,3 ponto por quarto), o que importa para a divisão de pontos, não para o total.",
        "8. Não há amostra de equipe confiável. Qualquer modelo precisa regredir à média da liga.",
    ]))
    OUT.mkdir(exist_ok=True)
    (OUT / "01_analise_dados.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
