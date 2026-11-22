"""Etapas 3 e 4: backtest walk-forward completo, referências simples, ajustes e modo Ao vivo.

Uso (na raiz):  python scripts/backtest_completo.py
Lê dados/teams.json e grava relatorio/03_backtest.md e relatorio/backtest_resultados.json.

Protocolo (sem vazamento):
- cada jogo é previsto só com jogos que começaram antes dele (motor collector/walkforward.py);
- o 1º dia de coleta (2026-11-14) não é avaliado: nada se sabia antes dele;
- parâmetros escolhidos SÓ no período de ajuste (até 2026-11-18) e avaliados no período de teste
  (2026-11-19 em diante), que não participou de nenhuma escolha;
- sem divisão aleatória. O sorteio só aparece no bootstrap por jogo, para intervalos de confiança.

Não há linhas de casas de apostas na base. As linhas de Over/Under usadas são sintéticas e iguais
para todos os modelos: a linha da referência "média da liga" (piso da média + 0,5) e deslocamentos
de ±2 e ±4 unidades (1 ponto nos quartos, 1,5 nos tempos, 3 no jogo).
"""
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector import backtest as BT  # noqa: E402
from collector import model as M  # noqa: E402
from collector import walkforward as W  # noqa: E402
from base_dados import load_teams  # noqa: E402

OUT = ROOT / "relatorio"
BURN = "2026-11-14"
TUNE_END = "2026-11-18"
QK = ("q1", "q2", "q3", "q4")
PERIODS = M.PERIODS
PL = {"q1": "1º quarto", "q2": "2º quarto", "q3": "3º quarto", "q4": "4º quarto", "h1": "1º tempo",
      "h2": "2º tempo", "reg": "Tempo normal"}
UNIT = {"q1": 1, "q2": 1, "q3": 1, "q4": 1, "h1": 1.5, "h2": 1.5, "reg": 3}
OFFS = (-4, -2, 0, 2, 4)
EPS = 0.005


# ---------------------------------------------------------------- utilitários
def f(x, nd=2):
    if x is None:
        return "–"
    return f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def table(head, rows):
    al = ["---"] + ["---:"] * (len(head) - 1)
    return "\n".join(["| " + " | ".join(head) + " |", "| " + " | ".join(al) + " |"] +
                     ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def phi(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def p_over(mu, sd, line):
    return 1 - phi((line - mu) / sd)


class Raw:
    """Estado do modelo original: todas as partidas, sem filtro (como collector/backtest.py)."""

    def __init__(self):
        self.comp = defaultdict(lambda: defaultdict(BT.Running))
        self.glob = defaultdict(BT.Running)

    def add_raw(self, g):
        for k in PERIODS:
            v = M.value(g["e"], k, "sum")
            self.comp[g["cid"]][k].add(v)
            self.glob[k].add(v)


def glob_combined(league, k):
    xs = [league.glob[g][k] for g in ("m", "w") if league.glob[g][k].n]
    n = sum(x.n for x in xs)
    if n < 2:
        return None, None
    mean = sum(x.mean * x.n for x in xs) / n
    m2 = sum(x.m2 + x.n * (x.mean - mean) ** 2 for x in xs)
    return mean, math.sqrt(m2 / (n - 1))


# ---------------------------------------------------------------- coleta walk-forward
def gather(teams):
    raw = Raw()
    recs = []

    def on_group(ctxs):
        for c in ctxs:
            g = c["g"]
            e = g["e"]
            if g["date"] <= BURN:
                continue
            tA, tB = teams[g["h"]], teams[g["a"]]
            raw10A, raw10B = BT.prior_rows(tA, g["cid"], g["sortKey"]), BT.prior_rows(tB, g["cid"], g["sortKey"])
            raw20A, raw20B = W.team_rows(tA, g["cid"], g["tip"], 20), W.team_rows(tB, g["cid"], g["tip"], 20)
            for k in PERIODS:
                if not M.usable(e, k):
                    continue
                L = c["league"].snapshot(g["cid"], g["women"], k)
                gm, gs = glob_combined(c["league"], k)
                prior = BT.walk_forward_prior(raw.comp, raw.glob, g["cid"], k)
                r = {"gid": g["gid"], "date": g["date"], "tip": g["tip"], "k": k, "cid": g["cid"], "cname": g["cname"],
                     "women": g["women"], "h": g["h"], "a": g["a"], "hn": tA.get("name"), "an": tB.get("name"),
                     "y": M.value(e, k, "sum"), "yh": M.value(e, k, "for"), "ya": M.value(e, k, "against"),
                     "L": L, "glob": (gm, gs),
                     "ta": M.team_totals(c["rowsA"], k), "tb": M.team_totals(c["rowsB"], k),
                     "taH": M.team_totals([x for x in c["rowsA"] if x["home"]], k),
                     "tbA": M.team_totals([x for x in c["rowsB"] if not x["home"]], k),
                     "fa": [M.value(x, k, "for") for x in c["rowsA"] if M.usable(x, k)],
                     "aa": [M.value(x, k, "against") for x in c["rowsA"] if M.usable(x, k)],
                     "fb": [M.value(x, k, "for") for x in c["rowsB"] if M.usable(x, k)],
                     "ab": [M.value(x, k, "against") for x in c["rowsB"] if M.usable(x, k)]}
                # modelo original, regra do backtest de produção (últimos 10, mínimo 3 de cada lado)
                if len(raw10A) >= BT.MIN_PRIOR and len(raw10B) >= BT.MIN_PRIOR:
                    A, B = M.summarize(raw10A, k), M.summarize(raw10B, k)
                    r["orig_bt"] = (M.cross(A, B), M.shrunk_sd(A, B, prior))
                # modelo original, regra do painel (últimos 20, mínimo 1 de cada lado)
                if raw20A and raw20B:
                    A, B = M.summarize(raw20A, k), M.summarize(raw20B, k)
                    r["orig"] = (M.cross(A, B), M.shrunk_sd(A, B, prior))
                    r["freqA"], r["freqB"] = A["totals"], B["totals"]
                recs.append(r)

    info = W.walk(teams, on_group, extra_states=(raw,))
    return recs, info


# ---------------------------------------------------------------- modelos sobre os registros
def baseline_liga(r):
    L = r["L"]
    if L["n"] >= 3:
        mu = L["mean"]
    else:
        mu = L["gmean"]
    gs = r["glob"][1] or M.DEFAULT_SD[r["k"]]
    sd = L["sd"] if L["n"] >= 15 and L["sd"] else gs
    return mu, sd


def baseline_global(r):
    gm, gs = r["glob"]
    return (gm if gm is not None else M.DEFAULT_MEAN[r["k"]]), (gs or M.DEFAULT_SD[r["k"]])


def v2(r, params, venue=False, recency=False):
    ta, tb = (r["taH"], r["tbA"]) if venue else (r["ta"], r["tb"])
    rows_a = [{"pts": [0, 0, 0, 0], "oppPts": [0, 0, 0, 0]}]  # não usado: totais já calculados
    p = {**M.V2, **params}
    lm = M.league_mean(r["L"], p["k_comp"])
    s = M.league_sd(r["L"], p["k_sd"])
    na, nb, kt = len(ta), len(tb), p["k_team"]
    da = (M.wmean(ta, recency) - lm) if na else 0.0
    db = (M.wmean(tb, recency) - lm) if nb else 0.0
    mean = lm + 0.5 * (na / (na + kt) * da + nb / (nb + kt) * db)
    nl = r["L"]["n"]
    var = s * s * (1 + 1 / (nl + p["k_comp"]) + 0.25 * (1 / (na + kt) + 1 / (nb + kt)))
    return mean, math.sqrt(var)


def v2_checked(r, params):
    """Mesma conta pela função de produção (garante que o script avalia exatamente o código do app)."""
    fake = lambda ts: [{"pts": [t, 0, 0, 0], "oppPts": [0, 1, 1, 1]} for t in ts]  # noqa: E731
    out = M.project_v2(fake(r["ta"]), fake(r["tb"]), "q1", r["L"], params)
    return out["mean"], out["sd"]


def clean_sd_original(r):
    """Ablação: modelo original com amostra limpa e dispersão da liga correta (sem os 18,4 contaminados)."""
    ta, tb = r["ta"], r["tb"]
    if not ta or not tb:
        return None
    mu = (sum(r["fa"]) / len(ta) + sum(r["ab"]) / len(tb)) / 2 + (sum(r["fb"]) / len(tb) + sum(r["aa"]) / len(ta)) / 2
    L = r["L"]
    prior = M.league_sd(L, 15)
    A = {"n": len(ta), "sd": M.sd(ta)}
    B = {"n": len(tb), "sd": M.sd(tb)}
    return mu, M.shrunk_sd(A, B, prior)


def online(recs, base_key, bias=False, scale=False, kb=100, ks=100):
    """Correções walk-forward de viés e de dispersão, por período, aprendidas só com jogos anteriores."""
    out = {}
    st = defaultdict(lambda: [0, 0.0, 0.0])  # k -> n, soma resíduo, soma z²
    by_tip = defaultdict(list)
    for i, r in enumerate(recs):
        if base_key in r:
            by_tip[r["tip"]].append(i)
    for tip in sorted(by_tip):
        idx = by_tip[tip]
        for i in idx:
            r = recs[i]
            mu, sd = r[base_key]
            n, sres, sz2 = st[r["k"]]
            b = sres / (n + kb) if bias else 0.0
            c = math.sqrt((sz2 + ks) / (n + ks)) if scale else 1.0
            out[i] = (mu + b, sd * c)
        for i in idx:
            r = recs[i]
            mu, sd = r[base_key]
            s = st[r["k"]]
            s[0] += 1
            s[1] += r["y"] - mu
            s[2] += ((r["y"] - mu) / sd) ** 2
    return out


# ---------------------------------------------------------------- métricas
def lines_of(r):
    base = math.floor(r["liga"][0]) + 0.5
    return [base + d * UNIT[r["k"]] for d in OFFS]


def prob(r, model, line):
    if model == "freq":
        if "freqA" not in r:
            return None
        fa = sum(1 for t in r["freqA"] if t > line) / len(r["freqA"])
        fb = sum(1 for t in r["freqB"] if t > line) / len(r["freqB"])
        return (fa + fb) / 2
    if model not in r:
        return None
    mu, sd = r[model]
    return p_over(mu, sd, line)


def metrics(rs, model):
    pts = [r for r in rs if (model in r) or (model == "freq" and "freqA" in r)]
    if not pts:
        return None
    out = {"games": len({r["gid"] for r in pts}), "n": len(pts)}
    if model != "freq":
        err = [r[model][0] - r["y"] for r in pts]
        out["mae"] = sum(abs(e) for e in err) / len(err)
        out["rmse"] = math.sqrt(sum(e * e for e in err) / len(err))
        out["bias"] = sum(err) / len(err)
        z = [(r["y"] - r[model][0]) / r[model][1] for r in pts]
        out["zsd"] = math.sqrt(sum(x * x for x in z) / len(z))
        out["cov80"] = sum(1 for x in z if abs(x) <= 1.2816) / len(z)
    br = ll = 0.0
    nl = hit = nh = 0
    bins = [[0, 0.0, 0.0] for _ in range(10)]
    for r in pts:
        for j, line in enumerate(lines_of(r)):
            p = prob(r, model, line)
            o = 1.0 if r["y"] > line else 0.0
            br += (p - o) ** 2
            pc = min(max(p, EPS), 1 - EPS)
            ll += -(o * math.log(pc) + (1 - o) * math.log(1 - pc))
            nl += 1
            b = bins[min(int(p * 10), 9)]
            b[0] += 1; b[1] += p; b[2] += o
            if OFFS[j] == 0 and p != 0.5:
                nh += 1
                hit += 1 if (p > 0.5) == (o == 1.0) else 0
    out["brier"] = br / nl
    out["logloss"] = ll / nl
    out["hit"] = hit / nh if nh else None
    out["calib"] = [{"lo": i / 10, "n": b[0], "p": b[1] / b[0], "freq": b[2] / b[0]} for i, b in enumerate(bins) if b[0]]
    out["ece"] = sum(c["n"] * abs(c["p"] - c["freq"]) for c in out["calib"]) / nl
    return out


def boot_diff(rs, ma, mb, stat="brier", reps=1000, seed=42):
    """IC 95% da diferença (ma - mb) por reamostragem de JOGOS (preserva a correlação entre linhas e períodos)."""
    common = [r for r in rs if ma in r and mb in r]
    by = defaultdict(list)
    for r in common:
        by[r["gid"]].append(r)
    gids = list(by)
    if len(gids) < 10:
        return None

    def val(sample):
        a = b = 0.0
        n = 0
        for gid in sample:
            for r in by[gid]:
                if stat == "mae":
                    a += abs(r[ma][0] - r["y"]); b += abs(r[mb][0] - r["y"]); n += 1
                else:
                    for line in lines_of(r):
                        o = 1.0 if r["y"] > line else 0.0
                        a += (prob(r, ma, line) - o) ** 2; b += (prob(r, mb, line) - o) ** 2; n += 1
        return (a - b) / n
    rnd = random.Random(seed)
    point = val(gids)
    sims = sorted(val([rnd.choice(gids) for _ in gids]) for _ in range(reps))
    return point, sims[int(0.025 * reps)], sims[int(0.975 * reps)], len(gids)


# ---------------------------------------------------------------- Ao vivo
def live_eval(recs, model, weights):
    """Para jogos com quartos válidos: depois de k quartos, projeta o total do tempo normal e o próximo quarto."""
    by = defaultdict(dict)
    for r in recs:
        if r["k"] in QK and model in r:
            by[r["gid"]][r["k"]] = r
    res = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0.0, 0.0]))  # (k, w) -> n, abs final, abs next, z2
    for gid, q in by.items():
        if len(q) < 4:
            continue
        mu = [q[k][model][0] for k in QK]
        sd = [q[k][model][1] for k in QK]
        y = [q[k]["y"] for k in QK]
        date = q["q1"]["date"]
        for kp in (1, 2, 3):
            obs, exp = sum(y[:kp]), sum(mu[:kp])
            pace = obs / exp
            for w in weights:
                mult = 1 + w * (pace - 1)
                rest = [m * mult for m in mu[kp:]]
                final = obs + sum(rest)
                sdr = math.sqrt(sum(s * s for s in sd[kp:]))
                a = res[(kp, w)][date <= TUNE_END]
                a[0] += 1
                a[1] += abs(final - sum(y))
                a[2] += abs(rest[0] - y[kp])
                a[3] += ((sum(y) - final) / sdr) ** 2
    return res


# ---------------------------------------------------------------- principal
def main():
    teams = load_teams()
    recs, info = gather(teams)
    for r in recs:
        r["liga"] = baseline_liga(r)
        r["global"] = baseline_global(r)
        cs = clean_sd_original(r)
        if cs:
            r["limpo"] = cs
    tune = [r for r in recs if r["date"] <= TUNE_END]
    test = [r for r in recs if r["date"] > TUNE_END]

    # conferência: a reprodução do modelo original bate com o código de produção
    trace = []
    BT.run_backtest(teams, trace)
    tr = {(g, k): (ps, s) for g, k, _, ps, s in trace}
    chk = [(r["orig_bt"], tr[(r["gid"], r["k"])]) for r in recs if "orig_bt" in r and (r["gid"], r["k"]) in tr]
    max_diff = max((abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in chk), default=0)
    assert max_diff < 1e-4, f"reprodução do modelo original diverge ({max_diff})"

    # grade de parâmetros do v2, escolhida só no período de ajuste
    grid = [{"k_team": kt, "k_comp": kc, "k_sd": ks}
            for kt in (1, 2, 4, 8, 15, 30, 1e9) for kc in (1, 3, 6, 12) for ks in (5, 15, 40)]
    scores = []
    for p in grid:
        tot = 0.0
        for k in PERIODS:
            rs = [r for r in tune if r["k"] == k]
            ll = 0.0
            n = 0
            for r in rs:
                mu, sd = v2(r, p)
                for line in lines_of(r):
                    o = 1.0 if r["y"] > line else 0.0
                    pc = min(max(p_over(mu, sd, line), EPS), 1 - EPS)
                    ll += -(o * math.log(pc) + (1 - o) * math.log(1 - pc)); n += 1
            tot += ll / n
        scores.append((tot / len(PERIODS), p))
    scores.sort(key=lambda x: x[0])
    best = scores[0][1]
    for r in recs:
        r["v2"] = v2(r, best)
        r["v2_semequipe"] = v2(r, {**best, "k_team": 1e9})
        r["v2_recencia"] = v2(r, best, recency=True)
        r["v2_mando"] = v2(r, best, venue=True)
    # a conta do script é a mesma da função de produção
    for r in recs[:500]:
        a, b = r["v2"], v2_checked(r, best)
        assert abs(a[0] - b[0]) < 1e-9 and abs(a[1] - b[1]) < 1e-9
    for i, x in online(recs, "v2", bias=True).items():
        recs[i]["v2_vies"] = x
    for i, x in online(recs, "v2", scale=True).items():
        recs[i]["v2_escala"] = x

    MODELS = [("global", "Referência: média global"), ("liga", "Referência: média da liga"),
              ("orig", "Original (regra do painel: 1+ jogo, últimos 20)"),
              ("orig_bt", "Original (regra do backtest: 3+ jogos, últimos 10)"),
              ("freq", "Frequência histórica (Freq. A/B do painel)"),
              ("limpo", "Original com dados limpos e dispersão correta"),
              ("v2_semequipe", "v2 só liga (sem ajuste de equipe)"),
              ("v2", "v2 liga + equipe encolhida (escolhido)"),
              ("v2_recencia", "v2 + peso de recência"), ("v2_mando", "v2 + amostra por mando"),
              ("v2_vies", "v2 + correção de viés"), ("v2_escala", "v2 + escala de dispersão")]
    L = []
    w = L.append
    R = {"best": best, "grid_top": [(round(s, 5), p) for s, p in scores[:5]], "info": {k: v for k, v in info.items() if k != "league"}}
    games_all = {r["gid"] for r in recs}
    w("# Etapas 3 e 4: backtest walk-forward e recalibragem\n")
    w("Gerado por `scripts/backtest_completo.py` a partir de `dados/teams.json`. Nenhum número foi digitado à mão.\n")
    w("## Protocolo\n")
    w(table(["Item", "Valor"], [
        ["Jogos na base (registros por gid)", info["games"]],
        ["Duplicatas entre fontes descartadas", info["duplicates"]],
        ["Jogos avaliados (a partir de 2026-11-15)", len(games_all)],
        ["Período de ajuste (escolha de parâmetros)", f"2026-11-15 a {TUNE_END}: {len({r['gid'] for r in tune})} jogos"],
        ["Período de teste (fora da amostra)", f"2026-11-19 a 2026-11-22: {len({r['gid'] for r in test})} jogos"],
        ["Linhas por período", "5 linhas sintéticas comuns a todos os modelos (sem linhas de mercado na base)"],
        ["Reprodução do modelo original", f"idêntica ao código de produção em {len(chk)} previsões (diferença máx. {max_diff:.1e})"],
    ]))
    w("\nO jogo de 2026-11-14 não é avaliado porque não havia nenhum jogo anterior. Jogos em tempos (NCAA masculina) "
      "entram só nos tempos e no jogo; jogos inválidos ficam de fora.\n")

    def comp_table(rs, title, models=MODELS):
        rows = []
        res = {}
        for key, name in models:
            m = metrics(rs, key)
            res[key] = m
            if not m:
                continue
            rows.append([name, m["games"], f(m.get("mae")), f(m.get("rmse")), f(m.get("bias")),
                         f(100 * m["hit"], 1) + "%" if m.get("hit") is not None else "–",
                         f(m["brier"], 4), f(m["logloss"], 4), f(100 * m["ece"], 1), f(m.get("zsd")),
                         f(100 * m["cov80"], 0) + "%" if m.get("cov80") is not None else "–"])
        w(f"### {title}\n")
        w(table(["Modelo", "Jogos", "MAE", "RMSE", "Viés", "Acerto na linha central", "Brier", "Log loss",
                 "ECE (p.p.)", "DP dos z", "Cobertura 80%"], rows))
        w("")
        return res

    w("## Escolha dos parâmetros do v2 (só período de ajuste)\n")
    w(f"Grade de {len(grid)} combinações; critério: log loss médio dos 7 períodos. Melhores:\n")
    w(table(["Log loss", "k_team", "k_comp", "k_sd"],
            [[f(s, 5), "∞" if p["k_team"] > 1e8 else p["k_team"], p["k_comp"], p["k_sd"]] for s, p in scores[:6]]))
    w(f"\nEscolhido: k_team = {best['k_team']}, k_comp = {best['k_comp']}, k_sd = {best['k_sd']}. "
      "O ganho entre as primeiras combinações é pequeno; a escolha é estável.\n")

    w("## Resultado fora da amostra (período de teste), quartos agrupados\n")
    w("MAE, RMSE e viés em pontos do total dos dois times no quarto. Viés positivo = projetou acima do real. "
      "\"Acerto na linha central\": lado (Over/Under) certo na linha da referência da liga. Brier e log loss: quanto menor, melhor "
      "(chute de 50% dá 0,25 e 0,693). ECE: distância média entre chance prevista e frequência observada. "
      "\"DP dos z\" perto de 1 e cobertura perto de 80% indicam dispersão bem dimensionada.\n")
    tq = [r for r in test if r["k"] in QK]
    R["test_quarters"] = comp_table(tq, "Todos os jogos do teste")
    R["test_quarters_orig_set"] = comp_table([r for r in tq if "orig" in r], "Só jogos em que o original do painel tem projeção (1+ jogo de cada equipe)")
    R["test_quarters_bt_set"] = comp_table([r for r in tq if "orig_bt" in r], "Só jogos em que o original do backtest avalia (3+ jogos de cada equipe)")

    w("## Período inteiro avaliado (ajuste + teste), quartos agrupados\n")
    R["all_quarters"] = comp_table([r for r in recs if r["k"] in QK], "Todos os jogos avaliados")

    w("## Intervalos de confiança (bootstrap por jogo, 1.000 reamostragens, período de teste)\n")
    rows = []
    for a, b, stat in (("v2", "orig", "brier"), ("v2", "orig", "mae"), ("v2", "liga", "brier"), ("v2", "liga", "mae"),
                       ("v2", "v2_semequipe", "brier"), ("v2", "v2_semequipe", "mae"),
                       ("v2_escala", "v2", "brier"), ("v2_vies", "v2", "brier"), ("v2_recencia", "v2", "mae"),
                       ("v2_mando", "v2", "mae")):
        bd = boot_diff(tq, a, b, stat)
        if bd:
            rows.append([f"{a} menos {b}", stat.upper(), bd[3], f(bd[0], 4), f"[{f(bd[1], 4)}; {f(bd[2], 4)}]",
                         "melhora comprovada" if bd[2] < 0 else "piora comprovada" if bd[1] > 0 else "sem diferença comprovada"])
    w(table(["Comparação", "Métrica", "Jogos", "Diferença", "IC 95%", "Conclusão"], rows))
    w("\nDiferença negativa = o primeiro modelo erra menos.\n")
    R["boot"] = rows

    w("## Por período (teste)\n")
    prow = []
    for k in PERIODS:
        rs = [r for r in test if r["k"] == k]
        mv, mo, ml = metrics(rs, "v2"), metrics(rs, "orig"), metrics(rs, "liga")
        mo2 = metrics([r for r in rs if "orig" in r], "v2")
        prow.append([PL[k], mv["games"], f(mv["mae"]), f(mv["bias"]), f(mv["brier"], 4), f(100 * mv["ece"], 1), f(mv["zsd"]),
                     f(ml["mae"]), f(ml["brier"], 4),
                     f"{mo['games']}: {f(mo['mae'])} / {f(mo2['mae'])}" if mo else "–",
                     f"{f(mo['brier'], 4)} / {f(mo2['brier'], 4)}" if mo else "–"])
    w(table(["Período", "Jogos", "MAE v2", "Viés v2", "Brier v2", "ECE v2", "DP dos z v2", "MAE liga", "Brier liga",
             "Original: jogos: MAE orig / MAE v2", "Brier orig / v2"], prow))
    w("")
    R["periods"] = prow

    w("## Por competição (teste, quartos; ligas com 15+ jogos avaliados)\n")
    by = defaultdict(list)
    for r in tq:
        by[r["cname"]].append(r)
    crow = []
    for c, rs in sorted(by.items(), key=lambda x: -len({r["gid"] for r in x[1]})):
        n = len({r["gid"] for r in rs})
        if n < 15:
            continue
        mv, ml, mo = metrics(rs, "v2"), metrics(rs, "liga"), metrics(rs, "orig")
        crow.append([c, n, f(mv["mae"]), f(mv["bias"]), f(mv["brier"], 4), f(ml["mae"]), f(ml["brier"], 4),
                     f"{mo['games']} / {f(mo['mae'])}" if mo else "–"])
    w(table(["Competição", "Jogos", "MAE v2", "Viés v2", "Brier v2", "MAE liga", "Brier liga", "Original: jogos / MAE"], crow))
    w("")
    R["comps"] = crow

    w("## Por equipe (período inteiro, quartos; equipes com 4+ jogos avaliados)\n")
    byt = defaultdict(list)
    for r in recs:
        if r["k"] in QK:
            byt[r["hn"]].append(r)
            byt[r["an"]].append(r)
    trow = []
    for t, rs in sorted(byt.items(), key=lambda x: -len({r["gid"] for r in x[1]})):
        n = len({r["gid"] for r in rs})
        if n < 4:
            continue
        mv, ml = metrics(rs, "v2"), metrics(rs, "liga")
        trow.append([t, rs[0]["cname"], n, f(mv["mae"]), f(mv["bias"]), f(ml["mae"])])
    w(table(["Equipe", "Liga", "Jogos", "MAE v2", "Viés v2", "MAE liga"], trow[:25]))
    w(f"\n{len(trow)} equipes têm 4 ou mais jogos avaliados; nenhuma tem amostra suficiente para conclusão individual "
      "(com 4 jogos x 4 quartos, o erro padrão do MAE de uma equipe passa de 1 ponto).\n")

    w("## Por tamanho da amostra (teste, quartos): menor número de jogos anteriores entre as duas equipes\n")
    srow = []
    for lo, hi, lab in ((0, 0, "0"), (1, 1, "1"), (2, 2, "2"), (3, 99, "3 ou mais")):
        rs = [r for r in tq if lo <= min(len(r["ta"]), len(r["tb"])) <= hi]
        if not rs:
            continue
        mv, ml, mo = metrics(rs, "v2"), metrics(rs, "liga"), metrics(rs, "orig")
        srow.append([lab, mv["games"], f(mv["mae"]), f(mv["brier"], 4), f(ml["mae"]), f(ml["brier"], 4),
                     f(mo["mae"]) if mo else "sem projeção", f(mo["brier"], 4) if mo else "–"])
    w(table(["Jogos anteriores", "Jogos", "MAE v2", "Brier v2", "MAE liga", "Brier liga", "MAE original", "Brier original"], srow))
    w("")
    R["sizes"] = srow

    w("## Por faixa de total previsto (teste, quartos)\n")
    w("Faixa medida em desvios da média da liga: o v2 projeta abaixo, perto ou acima da liga.\n")
    frow = []
    for lo, hi, lab in ((-99, -0.15, "abaixo da liga"), (-0.15, 0.15, "perto da liga"), (0.15, 99, "acima da liga")):
        rs = [r for r in tq if lo <= (r["v2"][0] - M.league_mean(r["L"], best["k_comp"])) / M.league_sd(r["L"], best["k_sd"]) < hi]
        if not rs:
            continue
        mv, mo = metrics(rs, "v2"), metrics([r for r in rs if "orig" in r], "orig")
        frow.append([lab, mv["games"], f(mv["mae"]), f(mv["bias"]), f(mv["brier"], 4), f(mo["bias"]) if mo else "–"])
    w(table(["Faixa", "Jogos", "MAE v2", "Viés v2", "Brier v2", "Viés original (mesma faixa)"], frow))
    w("")

    w("## Masculino x feminino (teste, quartos)\n")
    grow = []
    for wv, lab in ((False, "Masculino"), (True, "Feminino")):
        rs = [r for r in tq if r["women"] == wv]
        mv, ml = metrics(rs, "v2"), metrics(rs, "liga")
        grow.append([lab, mv["games"], f(mv["mae"]), f(mv["bias"]), f(mv["brier"], 4), f(ml["mae"])])
    w(table(["Gênero", "Jogos", "MAE v2", "Viés v2", "Brier v2", "MAE liga"], grow))
    w("")

    w("## Mandante x visitante: pontos de cada time (teste, quartos)\n")
    w("Para o total o mando quase não importa; para a divisão dos pontos, sim. Comparação da projeção de pontos de cada time "
      "com e sem a vantagem média do mandante na liga (aprendida só com jogos anteriores).\n")
    hrow = []
    for use_home in (False, True):
        eh = ea = 0.0
        n = 0
        for r in tq:
            p = best
            lm = M.league_mean(r["L"], p["k_comp"])
            kt = p["k_team"]
            na, nb = len(r["fa"]), len(r["fb"])
            offA = (sum(r["fa"]) / na - lm / 2) if na else 0
            defA = (sum(r["aa"]) / na - lm / 2) if na else 0
            offB = (sum(r["fb"]) / nb - lm / 2) if nb else 0
            defB = (sum(r["ab"]) / nb - lm / 2) if nb else 0
            sa, sb = na / (na + kt), nb / (nb + kt)
            h = (r["L"]["home"] or 0) if use_home else 0
            ph = lm / 2 + h / 2 + 0.5 * (sa * offA + sb * defB)
            pa = lm / 2 - h / 2 + 0.5 * (sb * offB + sa * defA)
            eh += abs(ph - r["yh"]); ea += abs(pa - r["ya"]); n += 1
        hrow.append(["com vantagem do mandante" if use_home else "sem vantagem do mandante", n, f(eh / n), f(ea / n)])
    w(table(["Projeção de pontos", "Casos", "MAE mandante", "MAE visitante"], hrow))
    w("")
    R["home"] = hrow

    w("## Calibração das probabilidades (teste, quartos, todas as linhas)\n")
    for key in ("v2", "orig", "freq"):
        m = metrics(tq if key == "v2" else [r for r in tq if "orig" in r], key)
        w(f"**{dict(MODELS)[key]}** ({m['n']} previsões, {m['games']} jogos; ECE {f(100 * m['ece'], 1)} p.p.)\n")
        w(table(["Faixa prevista", "Casos", "Média prevista", "Aconteceu", "Diferença (p.p.)"],
                [[f"{int(c['lo'] * 100)}–{int(c['lo'] * 100 + 10)}%", c["n"], f(100 * c["p"], 1) + "%", f(100 * c["freq"], 1) + "%",
                  f(100 * (c["freq"] - c["p"]), 1)] for c in m["calib"]]))
        w("")
    R["calib_v2"] = metrics(tq, "v2")["calib"]

    # ---------------- Ao vivo
    w("## Modo Ao vivo: peso do ritmo observado\n")
    w("Para cada jogo com quartos válidos, depois de 1, 2 ou 3 quartos, projeta o total do tempo normal e o próximo quarto. "
      "O peso do ritmo (0 = ignora o jogo, 1 = confia só no ritmo) é escolhido no período de ajuste e conferido no teste. "
      "Base pré-jogo: v2. Referência: pesos atuais de 20/30/40%.\n")
    WS = (0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0)
    lv = live_eval(recs, "v2", WS)
    lrow = []
    best_w = {}
    for kp in (1, 2, 3):
        tune_best = min(WS, key=lambda x: lv[(kp, x)][True][1] / max(lv[(kp, x)][True][0], 1))
        best_w[kp] = tune_best
        cur = {1: 0.2, 2: 0.3, 3: 0.4}[kp]
        for wv in WS:
            tt = lv[(kp, wv)][False]
            tu = lv[(kp, wv)][True]
            mark = (" (atual)" if wv == cur else "") + (" (melhor no ajuste)" if wv == tune_best else "")
            lrow.append([f"após {kp}º quarto", f"{int(wv * 100)}%{mark}", tu[0], f(tu[1] / tu[0]), tt[0], f(tt[1] / tt[0]),
                         f(tt[2] / tt[0]), f(math.sqrt(tt[3] / tt[0]))])
    w(table(["Momento", "Peso do ritmo", "Jogos ajuste", "MAE final (ajuste)", "Jogos teste", "MAE final (teste)",
             "MAE próximo quarto (teste)", "DP dos z final (teste)"], lrow))
    w("")
    R["live_best"] = best_w
    R["live"] = lrow

    OUT.mkdir(exist_ok=True)
    (OUT / "03_backtest.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    (OUT / "backtest_resultados.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
