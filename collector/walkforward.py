"""Motor walk-forward: percorre os jogos em ordem de início e entrega, para cada jogo, só o que
se sabia antes dele. Usado pelo backtest de produção (collector/backtest.py) e pela avaliação
completa (scripts/backtest_completo.py).

Garantias contra vazamento:
- as estatísticas da liga e as amostras das equipes só incluem jogos com início ANTERIOR;
- jogos com o mesmo horário de início são todos avaliados antes de qualquer um entrar nas estatísticas;
- o mesmo jogo gravado pelas duas fontes (IDs diferentes) é avaliado uma vez só e entra uma vez só
  nas estatísticas, para uma cópia não "vazar" o resultado da outra;
- jogos inválidos (quarto 0 x 0 fora do padrão de tempos) não são avaliados nem entram nas estatísticas.
"""
import math
from collections import defaultdict
from datetime import date

from . import model as M

N_TEAM = 20  # jogos anteriores da equipe considerados (mesma competição)


class Running:
    """Média e variância acumuladas (Welford)."""
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


def collect(teams):
    """Um registro por gid (visão do mandante), em ordem de início."""
    games = {}
    for tid, t in teams.items():
        for e in t.get("games", []):
            if e.get("home") and e["gid"] not in games:
                games[e["gid"]] = {
                    "gid": e["gid"], "cid": e["cid"], "cname": e.get("cname") or e["cid"],
                    "sortKey": e["sortKey"], "tip": tip_of(e["sortKey"]),
                    "date": e.get("date") or e["sortKey"][:10],
                    "h": tid, "a": e["oppId"], "e": e, "shape": M.shape(e), "women": M.is_women(e.get("cname")),
                }
    return sorted(games.values(), key=lambda g: g["sortKey"])


def duplicates(games):
    """gid da Basketball API -> gid da API-Sports do mesmo jogo físico (quartos e prorrogação idênticos,
    datas a até 1 dia). Fica a cópia da API-Sports, a fonte com mais cobertura."""
    by_key = defaultdict(list)
    for g in games:
        e = g["e"]
        k1 = tuple(e["pts"]) + tuple(e["oppPts"]) + (e.get("ot", 0), e.get("oppOt", 0))
        k2 = tuple(e["oppPts"]) + tuple(e["pts"]) + (e.get("oppOt", 0), e.get("ot", 0))
        by_key[min(k1, k2)].append(g)
    dup = {}
    for grp in by_key.values():
        keep = [g for g in grp if g["gid"].startswith("as_")]
        for o in grp:
            if o["gid"].startswith("as_"):
                continue
            for k in keep:
                if abs((date.fromisoformat(o["date"]) - date.fromisoformat(k["date"])).days) <= 1:
                    dup[o["gid"]] = k["gid"]
                    break
    return dup


class LeagueState:
    """Estatísticas acumuladas por liga, por gênero e agrupadas dentro das ligas, por período."""

    MIN_GLOBAL = 30

    def __init__(self):
        self.comp = defaultdict(lambda: defaultdict(Running))
        self.home = defaultdict(lambda: defaultdict(Running))
        self.glob = defaultdict(lambda: defaultdict(Running))   # "w"/"m" -> período
        self.pool_m2 = defaultdict(float)
        self.pool_dof = defaultdict(int)

    def add(self, g):
        e = g["e"]
        gender = "w" if g["women"] else "m"
        for k in M.V2_PERIODS:
            if not M.usable(e, k):
                continue
            v = M.value(e, k, "sum")
            r = self.comp[g["cid"]][k]
            before = r.m2
            r.add(v)
            self.pool_m2[k] += r.m2 - before
            if r.n > 1:
                self.pool_dof[k] += 1
            self.glob[gender][k].add(v)
            self.home[g["cid"]][k].add(M.value(e, k, "for") - M.value(e, k, "against"))

    def pooled(self, k):
        if self.pool_dof[k] >= self.MIN_GLOBAL:
            return math.sqrt(self.pool_m2[k] / self.pool_dof[k])
        return M.DEFAULT_SD[k]

    def gmean(self, women, k):
        g = self.glob["w" if women else "m"][k]
        if g.n >= self.MIN_GLOBAL:
            return g.mean
        n = sum(x[k].n for x in self.glob.values())
        if n >= self.MIN_GLOBAL:
            return sum(x[k].mean * x[k].n for x in self.glob.values()) / n
        return M.DEFAULT_MEAN[k]

    def snapshot(self, cid, women, k):
        r = self.comp[cid][k]
        h = self.home[cid][k]
        return {"n": r.n, "mean": r.mean if r.n else None, "sd": r.sd(), "gmean": self.gmean(women, k),
                "pooled": self.pooled(k), "home": h.mean if h.n >= 10 else None,
                "msd": h.sd() if h.n >= 10 else self.pooled_margin(k)}

    def export(self):
        """Formato gravado em meta/priors (campo v2), usado pelo painel nas projeções de agora."""
        comps = {}
        for cid, per in self.comp.items():
            row = {}
            for k, r in per.items():
                if not r.n:
                    continue
                h = self.home[cid][k]
                row[k] = {"n": r.n, "mean": round(r.mean, 3), "sd": round(r.sd(), 3) if r.sd() else None,
                          "home": round(h.mean, 3) if h.n >= 10 else None,
                          "msd": round(h.sd(), 3) if h.n >= 10 else None}
            comps[cid] = row
        return {"comps": comps,
                "gmean": {g: {k: round(self.gmean(g == "w", k), 3) for k in M.V2_PERIODS} for g in ("m", "w")},
                "pooled": {k: round(self.pooled(k), 3) for k in M.V2_PERIODS},
                "msd": {k: round(self.pooled_margin(k), 3) for k in M.V2_PERIODS}}

    def pooled_margin(self, k):
        """Dispersão do saldo (mandante menos visitante) agrupada entre as ligas."""
        xs = [per[k] for per in self.home.values() if per[k].n > 1]
        dof = sum(x.n - 1 for x in xs)
        if dof >= self.MIN_GLOBAL:
            return math.sqrt(sum(x.m2 for x in xs) / dof)
        return M.DEFAULT_SD[k] * 1.3


def team_rows(team, cid, tip, n=N_TEAM):
    rows = [e for e in team.get("games", []) if e["cid"] == cid and tip_of(e["sortKey"]) < tip]
    rows.sort(key=lambda e: e["sortKey"], reverse=True)
    return rows[:n]


def walk(teams, on_group, extra_states=()):
    """Chama on_group(contextos) para cada horário de início, antes de atualizar os estados.

    Cada contexto: {"g": jogo, "league": LeagueState, "rowsA": [...], "rowsB": [...]}.
    extra_states: objetos com .add_raw(g), atualizados com TODOS os jogos (inclusive duplicatas e
    inválidos), para reproduzir fielmente o modelo original, que não os filtrava.
    """
    games = collect(teams)
    dup = duplicates(games)
    league = LeagueState()
    i = 0
    while i < len(games):
        tip = games[i]["tip"]
        group = []
        while i < len(games) and games[i]["tip"] == tip:
            group.append(games[i])
            i += 1
        ctxs = []
        for g in group:
            if g["gid"] in dup or g["shape"] == "invalid":
                continue
            if g["h"] not in teams or g["a"] not in teams:
                continue
            ctxs.append({"g": g, "league": league,
                         "rowsA": team_rows(teams[g["h"]], g["cid"], tip),
                         "rowsB": team_rows(teams[g["a"]], g["cid"], tip)})
        if ctxs:
            on_group(ctxs)
        for g in group:
            for s in extra_states:
                s.add_raw(g)
            if g["gid"] not in dup and g["shape"] != "invalid":
                league.add(g)
    return {"games": len(games), "duplicates": len(dup), "league": league}
