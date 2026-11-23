"""Backtest walk-forward e dispersão padrão por liga.

Para cada jogo já armazenado, refaz a projeção usando SÓ informação disponível antes do início dele:
- médias: jogos anteriores das duas equipes (mesma competição, últimos N);
- dispersão de referência da liga (prior): calculada só com jogos que começaram antes.
Jogos que começam no mesmo horário não entram um no cálculo do outro.

A dispersão gravada em meta/priors usa todo o histórico, porque serve às projeções de agora
(no momento da previsão, todo o passado é conhecido). Ela não é usada no backtest.
"""
import math
from collections import defaultdict

from . import model as M
from .store import now_iso

N_GAMES = 10
MIN_PRIOR = 3
LINE_OFFSETS = (-6, -3, 0, 3, 6)
BUCKETS = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
MIN_PRIOR_GAMES = 15   # jogos da liga para calcular a dispersão própria
MIN_GLOBAL_GAMES = 30  # jogos no total para usar a dispersão geral em vez do padrão fixo
CALIB_MIN_CASES = 500  # casos de chance avaliados antes de dar veredito de calibração
ECE_OK, ECE_FAIR = 0.03, 0.06


class Running:
    """Média e variância acumuladas (Welford), para a dispersão sem olhar o futuro."""
    __slots__ = ("n", "mean", "m2")

    def __init__(self):
        self.n, self.mean, self.m2 = 0, 0.0, 0.0

    def add(self, x):
        self.n += 1
        d = x - self.mean
        self.mean += d / self.n
        self.m2 += d * (x - self.mean)

    def sd(self):
        return math.sqrt(self.m2 / (self.n - 1)) if self.n > 1 else None


def tip_of(sort_key):
    return sort_key.split("|")[0]


def collect_games(teams):
    """gid -> (cid, cname, sortKey, idCasa, idFora, entradaDaCasa). Cada jogo uma vez."""
    games = {}
    for tid, t in teams.items():
        for e in t.get("games", []):
            if e.get("home") and e["gid"] not in games:
                games[e["gid"]] = (e["cid"], e.get("cname") or e["cid"], e["sortKey"], tid, e["oppId"], e)
    return games


def compute_priors(games):
    by_comp = defaultdict(lambda: defaultdict(list))
    allv = defaultdict(list)
    for cid, _, _, _, _, e in games.values():
        for k in M.PERIODS:
            v = M.value(e, k, "sum")
            by_comp[cid][k].append(v)
            allv[k].append(v)
    glob = {k: round(M.sd(allv[k]), 2) if len(allv[k]) >= 30 else M.DEFAULT_SD[k] for k in M.PERIODS}
    comps = {}
    for cid, per in by_comp.items():
        if len(per["q1"]) >= MIN_PRIOR_GAMES:
            comps[cid] = {k: round(M.sd(per[k]), 2) for k in M.PERIODS}
    return {"global": glob, "comps": comps}


def prior_rows(team, cid, sort_key):
    tip = tip_of(sort_key)
    rows = [e for e in team.get("games", []) if e["cid"] == cid and tip_of(e["sortKey"]) < tip]
    rows.sort(key=lambda e: e["sortKey"], reverse=True)
    return rows[:N_GAMES]


def walk_forward_prior(comp_stats, glob_stats, cid, k):
    c = comp_stats[cid][k]
    if c.n >= MIN_PRIOR_GAMES:
        return c.sd()
    g = glob_stats[k]
    if g.n >= MIN_GLOBAL_GAMES:
        return g.sd()
    return M.DEFAULT_SD[k]


def calibration_verdict(calibration):
    cases = sum(c["n"] for c in calibration)
    if not cases:
        return 0, None, "sem dados"
    ece = sum(c["n"] / cases * abs(c["p"] - c["freq"]) for c in calibration if c["n"])
    if cases < CALIB_MIN_CASES:
        status = "amostra insuficiente"
    elif ece <= ECE_OK:
        status = "calibrado"
    elif ece <= ECE_FAIR:
        status = "aceitável"
    else:
        status = "descalibrado"
    return cases, round(ece, 4), status


def run_backtest(teams, trace=None):
    games = collect_games(teams)
    per = {k: defaultdict(float) for k in M.PERIODS}
    calib = [defaultdict(float) for _ in BUCKETS]
    comp = defaultdict(lambda: defaultdict(float))
    comp_stats = defaultdict(lambda: defaultdict(Running))
    glob_stats = defaultdict(Running)
    evaluated = 0
    ordered = sorted(games.items(), key=lambda kv: kv[1][2])
    i = 0
    while i < len(ordered):
        # todos os jogos do mesmo horário são avaliados antes de entrarem na estatística
        tip = tip_of(ordered[i][1][2])
        group = []
        while i < len(ordered) and tip_of(ordered[i][1][2]) == tip:
            group.append(ordered[i]); i += 1
        for gid, (cid, cname, skey, hid, aid, e) in group:
            if hid not in teams or aid not in teams:
                continue
            ra, rb = prior_rows(teams[hid], cid, skey), prior_rows(teams[aid], cid, skey)
            if len(ra) < MIN_PRIOR or len(rb) < MIN_PRIOR:
                continue
            evaluated += 1
            for k in M.PERIODS:
                actual = M.value(e, k, "sum")
                A, B = M.summarize(ra, k), M.summarize(rb, k)
                Ar, Br = M.summarize(ra, k, True), M.summarize(rb, k, True)
                ps, pr = M.cross(A, B), M.cross(Ar, Br)
                prior = walk_forward_prior(comp_stats, glob_stats, cid, k)
                s = M.shrunk_sd(A, B, prior)
                if trace is not None:
                    trace.append((gid, k, round(prior, 6), round(ps, 6), round(s, 6)))
                d = per[k]
                d["n"] += 1
                d["absSimple"] += abs(ps - actual)
                d["absRecency"] += abs(pr - actual)
                d["errSimple"] += ps - actual
                for off in LINE_OFFSETS:
                    line = M.central_line(ps) + off
                    hit = 1.0 if actual > line else 0.0
                    pm = M.prob_over(ps, s, line)
                    if pm is None:
                        # dispersão zero (ex.: NCAA masculina em tempos, com Q1 = Q3 = 0 sempre):
                        # o modelo original não tem probabilidade; a linha não entra na avaliação.
                        d["degenerate"] += 1
                        continue
                    fa, fb = M.freq_over(A["totals"], line), M.freq_over(B["totals"], line)
                    pf = (fa + fb) / 2
                    d["lines"] += 1
                    d["brierModel"] += (pm - hit) ** 2
                    d["brierFreq"] += (pf - hit) ** 2
                    for (lo, hi), c in zip(BUCKETS, calib):
                        if lo <= pm < hi:
                            c["n"] += 1; c["p"] += pm; c["hit"] += hit
                            break
                if k in ("q1", "q2", "q3", "q4"):
                    c = comp[cid]
                    c["name"] = cname
                    c["n"] += 1
                    c["abs"] += abs(ps - actual)

        for gid, (cid, cname, skey, hid, aid, e) in group:
            for k in M.PERIODS:
                v = M.value(e, k, "sum")
                comp_stats[cid][k].add(v)
                glob_stats[k].add(v)

    def r(x, nd=2):
        return round(x, nd)

    periods = {}
    for k, d in per.items():
        n, L = d["n"], d["lines"]
        periods[k] = {"n": int(n)} if not n else {
            "n": int(n), "maeSimple": r(d["absSimple"] / n), "maeRecency": r(d["absRecency"] / n),
            "bias": r(d["errSimple"] / n), "brierModel": r(d["brierModel"] / L, 4) if L else None,
            "brierFreq": r(d["brierFreq"] / L, 4) if L else None, "skippedLines": int(d["degenerate"])}
    calibration = [{"lo": lo, "hi": min(hi, 1), "n": int(c["n"]),
                    "p": r(c["p"] / c["n"], 3) if c["n"] else None,
                    "freq": r(c["hit"] / c["n"], 3) if c["n"] else None}
                   for (lo, hi), c in zip(BUCKETS, calib)]
    cases, ece, status = calibration_verdict(calibration)
    by_comp = sorted(({"cid": cid, "name": c["name"], "n": int(c["n"] / 4), "mae": r(c["abs"] / c["n"])}
                      for cid, c in comp.items()), key=lambda x: -x["n"])[:20]
    return {"updatedAt": now_iso(), "games": evaluated,
            "params": {"lastN": N_GAMES, "minPrior": MIN_PRIOR, "halfLife": M.HALF_LIFE,
                       "minCalibCases": CALIB_MIN_CASES},
            "periods": periods, "calibration": calibration, "byComp": by_comp,
            "calibrationCases": cases, "ece": ece, "calibrationStatus": status,
            "leakFree": True}


# =====================================================================================
# Backtest v2 (produção). O original (run_backtest) continua calculado como referência.
# =====================================================================================
V2_MIN_GAMES = 300      # jogos distintos avaliados nos quartos antes de dar veredito de calibração
V2_BINS = 10
V2_OFFS = (-4, -2, 0, 2, 4)
V2_UNIT = {"q1": 1, "q2": 1, "q3": 1, "q4": 1, "h1": 1.5, "h2": 1.5, "reg": 3}


def _league_ref(L):
    """Referência simples: média da liga (com 3+ jogos) ou média global do gênero."""
    return L["mean"] if L["n"] >= 3 else L["gmean"]


class _RawPrior:
    """Estatísticas sem filtro, como o modelo original usava (para a comparação ser fiel)."""

    def __init__(self):
        self.comp = defaultdict(lambda: defaultdict(Running))
        self.glob = defaultdict(Running)

    def add_raw(self, g):
        for k in M.PERIODS:
            v = M.value(g["e"], k, "sum")
            self.comp[g["cid"]][k].add(v)
            self.glob[k].add(v)


def run_backtest_v2(teams, trace=None):
    """Avalia o v2, o original (regra do painel) e a média da liga, jogo a jogo, sem olhar o futuro.

    O veredito de calibração conta JOGOS distintos (as linhas e os quartos de um mesmo jogo são
    correlacionados e não valem como casos independentes).
    """
    from . import walkforward as W

    per = {k: defaultdict(float) for k in M.PERIODS}
    bins = [[0, 0.0, 0.0] for _ in range(V2_BINS)]
    calib_games = set()
    comp = defaultdict(lambda: defaultdict(float))
    z2 = defaultdict(lambda: [0, 0.0])        # k -> n, soma de z² (sem escala): escala final para o painel
    online = defaultdict(lambda: [0, 0.0])    # idem, só com jogos anteriores: avaliação honesta da escala
    raw = _RawPrior()
    first = {}

    def on_group(ctxs):
        pending = []
        for c in ctxs:
            g = c["g"]
            first.setdefault("date", g["date"])
            if g["date"] == first["date"]:
                continue   # 1º dia da base: nada se sabia antes
            e = g["e"]
            r20a = W.team_rows(teams[g["h"]], g["cid"], g["tip"], 20)
            r20b = W.team_rows(teams[g["a"]], g["cid"], g["tip"], 20)
            for k in M.PERIODS:
                if not M.usable(e, k):
                    continue
                y = M.value(e, k, "sum")
                L = c["league"].snapshot(g["cid"], g["women"], k)
                L["scale"] = M.sd_scale(*online[k])
                pr = M.project_v2(c["rowsA"], c["rowsB"], k, L)
                if trace is not None:
                    trace.append((g["gid"], k, round(pr["mean"], 6), round(pr["sd"], 6)))
                mu, sd = pr["mean"], pr["sd"]
                ref = _league_ref(L)
                ref_sd = L["sd"] if L["n"] >= 15 and L["sd"] else L["pooled"]
                line0 = math.floor(ref) + 0.5
                d = per[k]
                d["n"] += 1
                d["abs"] += abs(mu - y)
                d["err"] += mu - y
                d["absLiga"] += abs(ref - y)
                orig = None
                if r20a and r20b:
                    A, B = M.summarize(r20a, k), M.summarize(r20b, k)
                    orig = (M.cross(A, B), M.shrunk_sd(A, B, walk_forward_prior(raw.comp, raw.glob, g["cid"], k)))
                    d["nOrig"] += 1
                    d["absOrig"] += abs(orig[0] - y)
                    d["absV2o"] += abs(mu - y)
                for off in V2_OFFS:
                    line = line0 + off * V2_UNIT[k]
                    hit = 1.0 if y > line else 0.0
                    pm = M.prob_over(mu, sd, line)
                    d["lines"] += 1
                    d["brier"] += (pm - hit) ** 2
                    d["brierLiga"] += (M.prob_over(ref, ref_sd, line) - hit) ** 2
                    if orig:
                        d["linesOrig"] += 1
                        d["brierOrig"] += (M.prob_over(orig[0], orig[1], line) - hit) ** 2
                        d["brierV2o"] += (pm - hit) ** 2
                    if k in M.QUARTER_KEYS:
                        b = bins[min(int(pm * V2_BINS), V2_BINS - 1)]
                        b[0] += 1
                        b[1] += pm
                        b[2] += hit
                        calib_games.add(g["gid"])
                if k in M.QUARTER_KEYS:
                    cc = comp[g["cid"]]
                    cc["name"] = g["cname"]
                    cc["n"] += 1
                    cc["abs"] += abs(mu - y)
                    cc["absLiga"] += abs(ref - y)
                zz = ((y - mu) / (sd / L["scale"])) ** 2
                pending.append((k, zz))
                z2[k][0] += 1
                z2[k][1] += zz
        for k, zz in pending:   # só depois do horário inteiro: jogos simultâneos não se enxergam
            online[k][0] += 1
            online[k][1] += zz

    info = W.walk(teams, on_group, extra_states=(raw,))

    def r(x, nd=2):
        return round(x, nd)

    periods = {}
    for k, d in per.items():
        n = d["n"]
        if not n:
            periods[k] = {"n": 0}
            continue
        row = {"n": int(n), "mae": r(d["abs"] / n), "bias": r(d["err"] / n), "maeLiga": r(d["absLiga"] / n),
               "brier": r(d["brier"] / d["lines"], 4), "brierLiga": r(d["brierLiga"] / d["lines"], 4),
               "nOrig": int(d["nOrig"])}
        if d["nOrig"]:
            row.update({"maeOrig": r(d["absOrig"] / d["nOrig"]), "maeV2Same": r(d["absV2o"] / d["nOrig"]),
                        "brierOrig": r(d["brierOrig"] / d["linesOrig"], 4),
                        "brierV2Same": r(d["brierV2o"] / d["linesOrig"], 4)})
        periods[k] = row
    total = sum(b[0] for b in bins)
    calibration = [{"lo": i / V2_BINS, "hi": (i + 1) / V2_BINS, "n": int(b[0]),
                    "p": r(b[1] / b[0], 3) if b[0] else None, "freq": r(b[2] / b[0], 3) if b[0] else None}
                   for i, b in enumerate(bins)]
    ece = sum(b[0] / total * abs(b[1] / b[0] - b[2] / b[0]) for b in bins if b[0]) if total else None
    ngames = len(calib_games)
    if not total:
        status = "sem dados"
    elif ngames < V2_MIN_GAMES:
        status = "amostra insuficiente"
    elif ece <= ECE_OK:
        status = "calibrado"
    elif ece <= ECE_FAIR:
        status = "aceitável"
    else:
        status = "descalibrado"
    by_comp = sorted(({"cid": cid, "name": c["name"], "n": int(c["n"] / 4), "mae": r(c["abs"] / c["n"]),
                       "maeLiga": r(c["absLiga"] / c["n"])} for cid, c in comp.items()), key=lambda x: -x["n"])[:20]
    scale = {k: r(M.sd_scale(n, s), 4) for k, (n, s) in z2.items()}
    scale["total"] = scale.get("reg", 1.0)
    games = int(max((d["n"] for d in per.values()), default=0))
    return {"model": "v2", "updatedAt": now_iso(), "games": games,
            "params": {**M.V2, "minCalibGames": V2_MIN_GAMES,
                       "liveWeights": {str(k): v for k, v in M.LIVE_WEIGHT_V2.items()}},
            "periods": periods, "calibration": calibration, "calibrationGames": ngames,
            "calibrationCases": int(total), "ece": r(ece, 4) if ece is not None else None,
            "calibrationStatus": status, "byComp": by_comp, "sdScale": scale,
            "duplicatesSkipped": info["duplicates"], "leakFree": True}, info["league"]


def run(store, today_iso):
    """Roda uma vez por dia. Lê todas as equipes (1 leitura por equipe) e grava 2 documentos.

    meta/priors mantém os campos antigos (global, comps) e ganha "v2" (médias e dispersões por liga,
    usadas pelo painel). meta/backtest passa a trazer o v2, com o original em "reference".
    """
    state = store.get_meta("backtest")
    if state.get("date") == today_iso:
        return None
    teams = store.all_teams()
    priors = compute_priors(collect_games(teams))
    priors["updatedAt"] = now_iso()
    result, league = run_backtest_v2(teams)
    priors["v2"] = {**league.export(), "sdScale": result["sdScale"]}
    result["date"] = today_iso
    # O modelo original roda só como referência: uma falha nele não pode impedir a gravação do v2.
    try:
        ref = run_backtest(teams)
        result["reference"] = {k: ref[k] for k in ("games", "periods", "ece", "calibrationStatus", "calibrationCases")}
    except Exception as e:  # noqa: BLE001
        result["reference"] = {"error": f"{type(e).__name__}: {e}"[:300]}
    store.set_meta("priors", priors)
    store.set_meta("backtest", result)
    return {"teams": len(teams), "games": result["games"], "status": result["calibrationStatus"]}
