"""Odds de Over/Under da API-Sports, coletadas à parte e com poucas chamadas (fase 1: só grava).

O que a documentação garante (api-sports.io/documentation/basketball/v1, "odds"):
- odds pré-jogo, de 1 a 7 dias antes, atualizadas UMA vez por dia, histórico de 7 dias;
- filtros: league, season, game, bookmaker, bet. Uma chamada por liga e temporada traz
  todos os jogos próximos daquela liga.

Por isso: uma execução por dia, poucas chamadas (ligas com mais jogos e mais prioridade nas
próximas 36 h). Por jogo e período (q1..q4, h1, h2, total) guarda a linha de consenso entre as
casas e a chance de Over sem a margem da casa.

Grava: meta/odds (jogos próximos, para o painel na fase 2) e odds_hist/{AAAA-MM-DD} (retrato por
data de início: o último retrato antes do jogo é a linha de fechamento, usada no backtest
modelo x mercado).
"""
import re
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone

from .api import BudgetExhausted
from .apisports import PlanRestricted, QuotaExceeded
from .store import now_iso

HORIZON = 36 * 3600   # jogos considerados à frente
KEEP_PAST = 12 * 3600  # quanto tempo um jogo já iniciado fica em meta/odds

_QTR = {"1st": "q1", "2nd": "q2", "3rd": "q3", "4th": "q4"}


def period_of(bet_name):
    """Nome do mercado -> período do modelo. None para o que não se aplica (total de um time etc.)."""
    n = (bet_name or "").lower()
    if "over/under" not in n:
        return None
    if any(w in n for w in ("home", "away", "team", "player", "race", "exact")):
        return None
    m = re.search(r"(1st|2nd|3rd|4th)\s*(qtr|quarter)", n)
    if m:
        return _QTR[m.group(1)]
    m = re.search(r"(1st|2nd)\s*half", n)
    if m:
        return "h1" if m.group(1) == "1st" else "h2"
    if re.fullmatch(r"over/under(\s*\(including ot\))?", n.strip()):
        return "total"
    return None


def parse_values(values):
    """[{"value": "Over 180.5", "odd": "1.90"}, ...] -> {180.5: {"over": 1.9, "under": 1.85}}"""
    lines = defaultdict(dict)
    for v in values or []:
        m = re.match(r"\s*(over|under)\s*([0-9]+(?:\.[0-9]+)?)\s*$", str(v.get("value", "")), re.I)
        if not m:
            continue
        try:
            odd = float(v.get("odd"))
        except (TypeError, ValueError):
            continue
        if odd <= 1:
            continue
        lines[float(m.group(2))][m.group(1).lower()] = odd
    return {k: x for k, x in lines.items() if "over" in x and "under" in x}


def devig(over, under):
    """Chance de Over sem a margem da casa (normalização proporcional) e a margem."""
    io, iu = 1 / over, 1 / under
    return io / (io + iu), io + iu - 1


def summarize_market(book_lines):
    """book_lines: [ {linha: {"over", "under"}} por casa ] -> consenso do mercado."""
    mains, probs = [], defaultdict(list)
    margins = []
    for lines in book_lines:
        if not lines:
            continue
        best = None
        for line, od in lines.items():
            p, mg = devig(od["over"], od["under"])
            probs[line].append(p)
            if best is None or abs(p - 0.5) < abs(best[1] - 0.5):
                best = (line, p, mg)
        mains.append(best[0])
        margins.append(best[2])
    if not mains:
        return None
    line = statistics.median_low(sorted(mains))
    p = statistics.fmean(probs[line])
    return {"line": line, "pOver": round(p, 4), "books": len(mains), "lo": min(mains), "hi": max(mains),
            "margin": round(statistics.fmean(margins), 4)}


def game_markets(item):
    """Item da resposta de /odds -> {período: consenso}."""
    per = defaultdict(list)
    for bk in item.get("bookmakers") or []:
        by_period = defaultdict(dict)
        for bet in bk.get("bets") or []:
            k = period_of(bet.get("name"))
            if k:
                by_period[k].update(parse_values(bet.get("values")))
        for k, lines in by_period.items():
            per[k].append(lines)
    out = {}
    for k, books in per.items():
        s = summarize_market(books)
        if s:
            out[k] = s
    return out


def pick_leagues(agenda_games, now_ts, max_calls):
    """(liga, temporada) com jogos próximos, por prioridade e número de jogos."""
    groups = {}
    for g in agenda_games or []:
        if g.get("st") != "NS" or not (now_ts < g.get("t", 0) <= now_ts + HORIZON):
            continue
        if not str(g.get("lg", "")).startswith("as_cp_") or not g.get("ss"):
            continue
        key = (g["lg"][6:], str(g["ss"]))
        grp = groups.setdefault(key, {"tier": g.get("tier", 1), "n": 0})
        grp["n"] += 1
        grp["tier"] = min(grp["tier"], g.get("tier", 1))
    order = sorted(groups.items(), key=lambda kv: (kv[1]["tier"], -kv[1]["n"], kv[0]))
    return [k for k, _ in order[:max_calls]]


def run_odds(client, store, cfg, now_ts=None):
    now_ts = int(now_ts if now_ts is not None else time.time())
    today = datetime.fromtimestamp(now_ts, timezone.utc).date().isoformat()
    acfg = cfg.get("apisports", {})
    agenda = store.get_meta("agenda").get("games") or []
    by_gid = {g["id"]: g for g in agenda}
    leagues = pick_leagues(agenda, now_ts, client.remaining())
    quota = store.get_meta("quota_apisports")
    if quota.get("date") != today:
        quota = {"date": today, "used": 0}
    found, note = {}, ""
    try:
        for league, season in leagues:
            try:
                rows = client.get("/odds", {"league": league, "season": season})
            except PlanRestricted as e:
                note = f"plano bloqueou odds: {e}"[:300]
                break
            for item in rows:
                gid = f"as_gm_{(item.get('game') or {}).get('id')}"
                m = game_markets(item)
                if not m:
                    continue
                g = by_gid.get(gid, {})
                found[gid] = {"t": g.get("t"), "lg": f"as_cp_{league}", "h": g.get("h"), "a": g.get("a"),
                              "at": now_ts, "m": m}
    except BudgetExhausted:
        note = note or "orçamento da execução esgotado"
    except QuotaExceeded as e:
        note = f"cota diária esgotada: {e}"[:300]
        quota["used"] = acfg.get("daily_call_limit", 90)
    finally:
        old = store.get_meta("odds").get("games") or {}
        keep = {k: v for k, v in old.items() if (v.get("t") or 0) > now_ts - KEEP_PAST}
        keep.update(found)
        store.set_meta("odds", {"updatedAt": now_iso(), "games": keep, "calls": client.calls,
                                "leagues": [f"{lg}/{ss}" for lg, ss in leagues], "note": note})
        by_day = defaultdict(dict)
        for gid, v in found.items():
            if v.get("t"):
                day = datetime.fromtimestamp(v["t"], timezone.utc).date().isoformat()
                by_day[day][gid] = v
        for day, games in by_day.items():
            store.merge_doc("odds_hist", day, games)
        quota["used"] = quota.get("used", 0) + client.calls
        store.set_meta("quota_apisports", quota)
    return {"calls": client.calls, "leagues": len(leagues), "games": len(found), "note": note}
