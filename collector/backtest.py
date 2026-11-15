"""Backtest walk-forward e dispersão padrão por liga.

Para cada jogo já armazenado, refaz a projeção usando SÓ os jogos anteriores das duas equipes
(mesma competição, últimos N) e compara com o que aconteceu. Nada do próprio jogo entra no cálculo.
"""
from collections import defaultdict

from . import model as M
from .store import now_iso

N_GAMES = 10
MIN_PRIOR = 3
LINE_OFFSETS = (-6, -3, 0, 3, 6)
BUCKETS = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
MIN_PRIOR_GAMES = 15   # jogos da liga para calcular a dispersão própria


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
    rows = [e for e in team.get("games", []) if e["cid"] == cid and e["sortKey"] < sort_key]
    rows.sort(key=lambda e: e["sortKey"], reverse=True)
    return rows[:N_GAMES]


def run_backtest(teams, priors):
    games = collect_games(teams)
    per = {k: defaultdict(float) for k in M.PERIODS}
    calib = [defaultdict(float) for _ in BUCKETS]
    comp = defaultdict(lambda: defaultdict(float))
    evaluated = 0
    for gid, (cid, cname, skey, hid, aid, e) in games.items():
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
            prior = priors["comps"].get(cid, priors["global"])[k]
            s = M.shrunk_sd(A, B, prior)
            d = per[k]
            d["n"] += 1
            d["absSimple"] += abs(ps - actual)
            d["absRecency"] += abs(pr - actual)
            d["errSimple"] += ps - actual
            for off in LINE_OFFSETS:
                line = M.central_line(ps) + off
                hit = 1.0 if actual > line else 0.0
                pm = M.prob_over(ps, s, line)
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

    def r(x, nd=2):
        return round(x, nd)

    periods = {}
    for k, d in per.items():
        n, L = d["n"], d["lines"]
        periods[k] = {"n": int(n)} if not n else {
            "n": int(n), "maeSimple": r(d["absSimple"] / n), "maeRecency": r(d["absRecency"] / n),
            "bias": r(d["errSimple"] / n), "brierModel": r(d["brierModel"] / L, 4),
            "brierFreq": r(d["brierFreq"] / L, 4)}
    calibration = [{"lo": lo, "hi": min(hi, 1), "n": int(c["n"]),
                    "p": r(c["p"] / c["n"], 3) if c["n"] else None,
                    "freq": r(c["hit"] / c["n"], 3) if c["n"] else None}
                   for (lo, hi), c in zip(BUCKETS, calib)]
    by_comp = sorted(({"cid": cid, "name": c["name"], "n": int(c["n"] / 4), "mae": r(c["abs"] / c["n"])}
                      for cid, c in comp.items()), key=lambda x: -x["n"])[:20]
    return {"updatedAt": now_iso(), "games": evaluated,
            "params": {"lastN": N_GAMES, "minPrior": MIN_PRIOR, "halfLife": M.HALF_LIFE},
            "periods": periods, "calibration": calibration, "byComp": by_comp}


def run(store, today_iso):
    """Roda uma vez por dia. Lê todas as equipes (1 leitura por equipe) e grava 2 documentos."""
    state = store.get_meta("backtest")
    if state.get("date") == today_iso:
        return None
    teams = store.all_teams()
    priors = compute_priors(collect_games(teams))
    priors["updatedAt"] = now_iso()
    result = run_backtest(teams, priors)
    result["date"] = today_iso
    store.set_meta("priors", priors)
    store.set_meta("backtest", result)
    return {"teams": len(teams), "games": result["games"]}
