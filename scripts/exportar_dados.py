"""Exporta os dados já coletados do Firestore para a pasta dados/, para análise local.

Usa só a biblioteca padrão do Python. Não precisa de chave secreta: a leitura das coleções
teams e meta é pública pelas regras do Firestore, e a chave Web (pública) é lida de
public/js/firebase-config.js.

Uso (na raiz do projeto):
    python scripts/exportar_dados.py

Gera:
    dados/teams.json   documentos completos das equipes (até 60 jogos cada, com quartos)
    dados/meta.json    índice de competições, priors, backtest, agenda, status da coleta
    dados/jogos.csv    um jogo por linha (sem duplicar), com os 4 quartos de cada lado e prorrogação
    dados/RESUMO.txt   contagens rápidas para conferência
"""
import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dados"
PROJECT = "basketball-analytics-233f9"
BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
META_NAMES = ["index", "status", "backfill", "status_apisports", "backfill_apisports",
              "agenda", "priors", "backtest", "quota", "quota_apisports"]


def api_key():
    txt = (ROOT / "public/js/firebase-config.js").read_text(encoding="utf-8")
    m = re.search(r'apiKey:\s*"([^"]+)"', txt)
    if not m:
        sys.exit("apiKey não encontrada em public/js/firebase-config.js")
    return m.group(1)


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def from_value(v):
    if "nullValue" in v:
        return None
    if "booleanValue" in v:
        return v["booleanValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "stringValue" in v:
        return v["stringValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "arrayValue" in v:
        return [from_value(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return from_fields(v["mapValue"].get("fields", {}))
    return None


def from_fields(fields):
    return {k: from_value(v) for k, v in (fields or {}).items()}


def list_teams(key):
    teams, token = [], None
    while True:
        q = {"pageSize": 300, "key": key}
        if token:
            q["pageToken"] = token
        page = get(f"{BASE}/teams?{urllib.parse.urlencode(q)}")
        for d in page.get("documents", []):
            t = from_fields(d.get("fields"))
            t.setdefault("id", d["name"].rsplit("/", 1)[-1])
            teams.append(t)
        token = page.get("nextPageToken")
        if not token:
            return teams


def get_metas(key):
    out = {}
    for n in META_NAMES:
        try:
            out[n] = from_fields(get(f"{BASE}/meta/{n}?key={key}").get("fields"))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    return out


def games_table(teams):
    """Um jogo por linha, montado a partir da visão do mandante (com fallback pela visão do visitante)."""
    rows = {}
    for t in teams:
        for e in t.get("games", []):
            gid = e["gid"]
            if gid in rows and e.get("home") is False:
                continue
            pts, opp = list(e.get("pts") or []), list(e.get("oppPts") or [])
            if e.get("home"):
                h_id, h_n, a_id, a_n, hq, aq, hot, aot = t["id"], t.get("name"), e["oppId"], e["oppName"], pts, opp, e.get("ot", 0), e.get("oppOt", 0)
            else:
                h_id, h_n, a_id, a_n, hq, aq, hot, aot = e["oppId"], e["oppName"], t["id"], t.get("name"), opp, pts, e.get("oppOt", 0), e.get("ot", 0)
            hq += [None] * (4 - len(hq)); aq += [None] * (4 - len(aq))
            rows[gid] = {
                "gid": gid, "data": e.get("date"), "sortKey": e.get("sortKey"),
                "fonte": "apisports" if str(gid).startswith("as_") else "basketballapi",
                "cid": e.get("cid"), "competicao": e.get("cname"),
                "mandante_id": h_id, "mandante": h_n, "visitante_id": a_id, "visitante": a_n,
                **{f"m_q{i+1}": hq[i] for i in range(4)}, "m_ot": hot,
                **{f"v_q{i+1}": aq[i] for i in range(4)}, "v_ot": aot,
            }
    for r in rows.values():
        qs = [r[f"m_q{i}"] for i in range(1, 5)] + [r[f"v_q{i}"] for i in range(1, 5)]
        r["total_tempo_normal"] = sum(qs) if None not in qs else None
        r["total_final"] = r["total_tempo_normal"] + (r["m_ot"] or 0) + (r["v_ot"] or 0) if r["total_tempo_normal"] is not None else None
    return sorted(rows.values(), key=lambda r: str(r.get("sortKey") or ""))


def main():
    key = api_key()
    OUT.mkdir(exist_ok=True)
    print("Baixando equipes...")
    teams = list_teams(key)
    print("Baixando metadados...")
    metas = get_metas(key)
    games = games_table(teams)
    (OUT / "teams.json").write_text(json.dumps(teams, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "meta.json").write_text(json.dumps(metas, ensure_ascii=False, indent=1), encoding="utf-8")
    if games:
        with (OUT / "jogos.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(games[0].keys()))
            w.writeheader(); w.writerows(games)
    comps = {}
    for g in games:
        comps[g["competicao"]] = comps.get(g["competicao"], 0) + 1
    resumo = [f"Equipes: {len(teams)}", f"Jogos únicos: {len(games)}",
              f"Período: {games[0]['data'] if games else '-'} a {games[-1]['data'] if games else '-'}",
              "Jogos por competição:"] + [f"  {n}: {c}" for c, n in sorted(((c, n) for n, c in comps.items()), key=lambda x: -x[0])]
    (OUT / "RESUMO.txt").write_text("\n".join(resumo) + "\n", encoding="utf-8")
    print("\n".join(resumo[:3]))
    print(f"Arquivos gravados em {OUT}")


if __name__ == "__main__":
    main()
