"""Carga e verificação de integridade dos dados exportados (dados/teams.json).

Só biblioteca padrão. Usado por scripts/analise_dados.py e scripts/backtest_completo.py.

Regras de qualidade aplicadas aqui (documentadas no relatório):
- Jogo único por gid (o mesmo jogo aparece no documento das duas equipes).
- Duplicata entre fontes: o mesmo jogo físico gravado pela API-Sports (as_) e pela Basketball API,
  reconhecido pelos 8 quartos + prorrogação idênticos e datas a no máximo 1 dia. Fica a cópia as_.
- Jogo inválido: algum quarto 0 x 0 fora do padrão de tempos (jogo zerado ou truncado). Fica fora de tudo.
- Formato em tempos: algumas ligas (NCAA masculina) chegam com o 1º tempo no "2º quarto" e o 2º tempo
  no "4º quarto", com Q1 = Q3 = 0 para os dois lados. Tempos e jogo continuam válidos; quartos não.
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector import model as M  # noqa: E402

DADOS = ROOT / "dados"
QUARTERS = ("q1", "q2", "q3", "q4")


def load_teams(path=None):
    path = Path(path or DADOS / "teams.json")
    if not path.exists():
        sys.exit(f"{path} não encontrado. Rode antes: python scripts/exportar_dados.py")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {t["id"]: t for t in raw}


def is_women(cname):
    low = f" {(cname or '').lower()} "
    return "women" in low or " w " in low or " w(" in low or "wcba" in low or "wkbl" in low or "wnba" in low


def build_games(teams):
    """Um registro por gid, montado pela visão do mandante (ou do visitante, se o mandante faltar)."""
    games = {}
    for tid, t in teams.items():
        for e in t.get("games", []):
            gid = e["gid"]
            if gid in games and not e.get("home"):
                continue
            if e.get("home"):
                h, a, hp, ap, hot, aot = tid, e["oppId"], e["pts"], e["oppPts"], e.get("ot", 0), e.get("oppOt", 0)
                hn, an = t.get("name"), e.get("oppName")
            else:
                h, a, hp, ap, hot, aot = e["oppId"], tid, e["oppPts"], e["pts"], e.get("oppOt", 0), e.get("ot", 0)
                hn, an = e.get("oppName"), t.get("name")
            games[gid] = {
                "gid": gid, "date": e["date"], "sortKey": e["sortKey"], "tip": e["sortKey"].split("|")[0],
                "cid": e["cid"], "cname": e.get("cname") or e["cid"],
                "src": "apisports" if gid.startswith("as_") else "basketballapi",
                "h": h, "a": a, "hn": hn, "an": an, "hp": list(hp), "ap": list(ap), "hot": hot or 0, "aot": aot or 0,
                # entrada no formato das equipes, vista pelo mandante (usada pelas funções do modelo)
                "entry": {"pts": list(hp), "oppPts": list(ap), "ot": hot or 0, "oppOt": aot or 0},
            }
    for g in games.values():
        g["shape"] = M.shape(g["entry"])
        g["halves"] = g["shape"] == "halves"
        g["invalid"] = g["shape"] == "invalid"
        g["women"] = is_women(g["cname"])
    return games


def find_cross_source_duplicates(games):
    """gid da Basketball API -> gid as_ do mesmo jogo físico."""
    by_key = {}
    for g in games.values():
        k = tuple(g["hp"]) + tuple(g["ap"]) + (g["hot"], g["aot"])
        ks = tuple(g["ap"]) + tuple(g["hp"]) + (g["aot"], g["hot"])  # mando invertido entre as fontes
        by_key.setdefault(min(k, ks), []).append(g)
    dup = {}
    for grp in by_key.values():
        if len(grp) < 2:
            continue
        keep = [g for g in grp if g["src"] == "apisports"]
        other = [g for g in grp if g["src"] != "apisports"]
        for o in other:
            for k in keep:
                if abs((date.fromisoformat(o["date"]) - date.fromisoformat(k["date"])).days) <= 1:
                    dup[o["gid"]] = k["gid"]
                    break
    return dup


def integrity(teams, games):
    """Contagens de problemas de integridade. Não altera nada."""
    out = {"entradas": 0, "sem_adversario_no_banco": 0, "assimetricas": 0, "visao_divergente": 0,
           "quartos_fora_faixa": 0, "periodos_incompletos": 0}
    for tid, t in teams.items():
        for e in t.get("games", []):
            out["entradas"] += 1
            if len(e.get("pts") or []) != 4 or len(e.get("oppPts") or []) != 4:
                out["periodos_incompletos"] += 1
                continue
            if any(not 0 <= x <= 80 for x in e["pts"] + e["oppPts"]):
                out["quartos_fora_faixa"] += 1
            opp = teams.get(e["oppId"])
            if not opp:
                out["sem_adversario_no_banco"] += 1
                continue
            mirror = next((x for x in opp.get("games", []) if x["gid"] == e["gid"]), None)
            if not mirror:
                out["assimetricas"] += 1
            elif mirror["pts"] != e["oppPts"] or mirror["oppPts"] != e["pts"] or mirror.get("home") == e.get("home"):
                out["visao_divergente"] += 1
    return out


def clean_games(teams):
    """Jogos únicos, sem duplicatas entre fontes. Devolve (lista ordenada, duplicatas, todos)."""
    games = build_games(teams)
    dup = find_cross_source_duplicates(games)
    clean = [g for gid, g in games.items() if gid not in dup and not g["invalid"]]
    clean.sort(key=lambda g: g["sortKey"])
    return clean, dup, games
