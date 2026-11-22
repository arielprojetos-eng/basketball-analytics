"""Coletor de placares por quarto.

Uso:
    python -m collector.main run [--max-calls N]

Fluxo de cada execução (respeitando a cota gratuita de 100 chamadas/dia):
  1. Descoberta: lista jogos finalizados dos últimos dias (/games).
  2. Detalhes: para cada jogo novo, busca os pontos por período (/games/{id}).
  3. Retroativo: com orçamento sobrando e sem fila, tenta voltar no tempo.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .api import (ApiError, BudgetExhausted, Client, QuotaExceeded,
                  UpgradeRequired)
from .model import shape
from .store import BufferedStore, FirestoreStore, now_iso

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def today_utc():
    return datetime.now(timezone.utc).date()


# ---------- classificação e normalização ----------

def competition_tier(name, cfg):
    low = (name or "").lower()
    for kw in cfg.get("priority_competitions", []):
        if kw.lower() in low:
            return 0
    return 1


def competition_allowed(name, cfg):
    only = cfg.get("only_competitions") or []
    if not only:
        return True
    low = (name or "").lower()
    return any(kw.lower() in low for kw in only)


def normalize_game(g, cfg):
    comp = g.get("competition") or {}
    season = g.get("season") or {}
    home = g.get("home") or {}
    away = g.get("away") or {}
    d = g.get("date") or (g.get("tip_off") or "")[:10]
    tip = g.get("tip_off") or d
    return {
        "id": g["id"],
        "competitionId": comp.get("id"),
        "competitionName": comp.get("name"),
        "season": season.get("name"),
        "date": d,
        "tipOff": tip,
        "sortKey": f"{tip}|{g['id']}",
        "homeId": home.get("id"),
        "homeName": home.get("name"),
        "awayId": away.get("id"),
        "awayName": away.get("name"),
        "homeScore": g.get("home_score"),
        "awayScore": g.get("away_score"),
        "status": g.get("status"),
        "tier": competition_tier(comp.get("name"), cfg),
        "periodsFetched": False,
        "hasQuarters": None,
        "source": "basketballapi",
    }


def valid_periods(periods):
    """Exige ao menos quatro períodos para os dois lados, todos numéricos."""
    if not periods:
        return None
    home, away = periods.get("home"), periods.get("away")
    if not home or not away or len(home) < 4 or len(away) < 4 or len(home) != len(away):
        return None
    try:
        return [int(x) for x in home], [int(x) for x in away]
    except (TypeError, ValueError):
        return None


def scores_match(periods, home_total, away_total):
    """Os quartos (mais prorrogações) precisam somar o placar final, e cada período ter valor plausível."""
    home, away = periods
    if any(not 0 <= x <= 80 for x in home + away):
        return False
    # Quarto 0 x 0 fora do padrão de tempos (Q1 = Q3 = 0) é jogo zerado ou truncado, não placar real.
    if shape({"pts": home[:4], "oppPts": away[:4]}) == "invalid":
        return False
    if home_total is not None and sum(home) != int(home_total):
        return False
    if away_total is not None and sum(away) != int(away_total):
        return False
    return True


def team_entry(game, periods, is_home):
    home, away = periods
    own, opp = (home, away) if is_home else (away, home)
    return {
        "gid": game["id"],
        "date": game["date"],
        "sortKey": game["sortKey"],
        "cid": game["competitionId"],
        "cname": game["competitionName"],
        "home": is_home,
        "oppId": game["awayId"] if is_home else game["homeId"],
        "oppName": game["awayName"] if is_home else game["homeName"],
        "pts": own[:4],
        "oppPts": opp[:4],
        "ot": sum(own[4:]),
        "oppOt": sum(opp[4:]),
    }


def add_to_team(store, tid, name, game, entry, keep):
    team = store.get_team(tid) or {"id": tid, "name": name, "games": []}
    if any(e["gid"] == entry["gid"] for e in team.get("games", [])):
        return team, False  # já registrado: não regrava (economiza cota do Firestore)
    team["name"] = name or team.get("name")
    games = list(team.get("games", []))
    games.append(entry)
    games.sort(key=lambda e: e["sortKey"], reverse=True)
    team["games"] = games[:keep]
    team["n"] = len(team["games"])
    team["updatedAt"] = now_iso()
    store.put_team(tid, team)
    return team, True


def update_index(store, game, teams_by_id):
    idx = store.get_meta("index") or {}
    comps = idx.setdefault("competitions", {})
    c = comps.setdefault(game["competitionId"], {"name": game["competitionName"], "teams": {}})
    c["name"] = game["competitionName"]
    c["src"] = game.get("source", "basketballapi")
    for tid, team in teams_by_id.items():
        inside = sum(1 for e in team["games"] if e["cid"] == game["competitionId"])
        c["teams"][tid] = {"name": team["name"], "n": inside}
    idx["updatedAt"] = now_iso()
    store.set_meta("index", idx)


# ---------- etapas ----------

def discover(client, store, cfg, days_back, today=None):
    today = today or today_utc()
    start = today - timedelta(days=days_back)
    games = client.paginate(
        "/games",
        {"from": start.isoformat(), "to": today.isoformat(), "status": "final"},
        max_pages=6,
    )
    return ingest_listing(store, games, cfg)


def ingest_listing(store, games, cfg):
    wanted = [g for g in games
              if g.get("status") == "final"
              and competition_allowed((g.get("competition") or {}).get("name"), cfg)]
    known = store.existing_game_ids([g["id"] for g in wanted])
    new = 0
    for g in wanted:
        if g["id"] in known:
            continue
        store.put_game(normalize_game(g, cfg))
        new += 1
    return new


def fetch_details(client, store, cfg, max_games):
    done = 0
    for game in store.pending_games(max_games):
        if client.remaining() <= 0:
            break
        try:
            data, _ = client.get(f"/games/{game['id']}")
        except UpgradeRequired:
            raise
        except ApiError as e:
            if e.status == 404:
                store.update_game(game["id"], {"periodsFetched": True, "hasQuarters": False})
                continue
            raise
        periods = valid_periods((data or {}).get("periods"))
        if periods and not scores_match(periods, game.get("homeScore"), game.get("awayScore")):
            periods = None
        if not periods:
            store.update_game(game["id"], {"periodsFetched": True, "hasQuarters": False})
            done += 1
            continue
        record_game(store, dict(game), periods, cfg)
        store.update_game(game["id"], {
            "periodsFetched": True,
            "hasQuarters": True,
            "periods": {"home": periods[0], "away": periods[1]},
            "fetchedAt": now_iso(),
        })
        done += 1
    return done


def record_game(store, game, periods, cfg):
    """Grava o jogo nos históricos das duas equipes e atualiza o índice."""
    he = team_entry(game, periods, True)
    ae = team_entry(game, periods, False)
    keep = cfg.get("keep_games_per_team", 60)
    ht, new_h = add_to_team(store, game["homeId"], game["homeName"], game, he, keep)
    at, new_a = add_to_team(store, game["awayId"], game["awayName"], game, ae, keep)
    if new_h or new_a:
        update_index(store, game, {game["homeId"]: ht, game["awayId"]: at})
    return new_h or new_a


def backfill_step(client, store, cfg, today=None):
    """Tenta buscar um dia anterior. Se o plano gratuito bloquear, registra e para."""
    today = today or today_utc()
    state = store.get_meta("backfill")
    if state.get("blocked"):
        return "blocked"
    floor = today - timedelta(days=cfg.get("backfill_floor_days", 400))
    nxt = state.get("nextDate")
    d = date.fromisoformat(nxt) if nxt else today - timedelta(days=cfg.get("discovery_days_back", 2) + 1)
    if d < floor:
        return "done"
    try:
        games = client.paginate("/games", {"date": d.isoformat(), "status": "final"}, max_pages=4)
    except (UpgradeRequired, ApiError) as e:
        if isinstance(e, QuotaExceeded):
            raise
        store.set_meta("backfill", {**state, "blocked": True, "reason": str(e), "at": now_iso()})
        return "blocked"
    ingest_listing(store, games, cfg)
    store.set_meta("backfill", {"nextDate": (d - timedelta(days=1)).isoformat(),
                                "lastDate": d.isoformat(), "at": now_iso()})
    return "ok"


# ---------- orquestração ----------

def run(client, store, cfg, today=None):
    day = today or today_utc()
    today = day.isoformat()
    quota = store.get_meta("quota")
    if quota.get("date") != today:
        quota = {"date": today, "used": 0}
    summary = {"new": 0, "details": 0, "backfill": None, "note": ""}
    try:
        try:
            summary["new"] = discover(client, store, cfg, cfg.get("discovery_days_back", 2), day)
            room = client.remaining() - 1
            if room > 0:
                summary["details"] = fetch_details(client, store, cfg, room)
            pending = store.count_pending()
            if pending == 0 and client.remaining() >= 8:
                summary["backfill"] = backfill_step(client, store, cfg, day)
        except BudgetExhausted:
            summary["note"] = "orçamento da execução esgotado"
        except QuotaExceeded:
            summary["note"] = "cota diária esgotada no servidor"
            quota["used"] = cfg.get("daily_call_limit", 92)
        except UpgradeRequired as e:
            summary["note"] = f"endpoint não liberado no plano gratuito: {e}"
    finally:
        quota["used"] = quota.get("used", 0) + client.calls
        store.set_meta("quota", quota)
        status = {
            "lastRun": now_iso(),
            "callsThisRun": client.calls,
            "usedToday": quota["used"],
            "pending": store.count_pending(),
            "lastSummary": summary,
        }
        store.set_meta("status", status)
    return summary


def daily_budget(store, cfg, quota_name, limit_key, run_key, override=None):
    today = today_utc().isoformat()
    quota = store.get_meta(quota_name)
    used = quota.get("used", 0) if quota.get("date") == today else 0
    left = cfg.get(limit_key, 92) - used
    return min(override or cfg.get(run_key, 30), left), used


def live_budget(store, acfg, override=None):
    """Chamadas liberadas para a varredura ao vivo, preservando a reserva das coletas completas."""
    today = today_utc().isoformat()
    quota = store.get_meta("quota_apisports")
    used = quota.get("used", 0) if quota.get("date") == today else 0
    left = acfg.get("daily_call_limit", 90) - used - acfg.get("live_reserve", 20)
    return max(0, min(override or acfg.get("live_calls_per_run", 2), left)), used


def run_live_cli(cfg, max_calls=None, store=None, client_factory=None, now_ts=None, force=False):
    """Varredura ao vivo (agendada a cada poucos minutos). Só API-Sports, só agenda."""
    import time
    from . import apisports
    key = os.environ.get("APISPORTS_KEY")
    if not key and client_factory is None:
        print("Defina APISPORTS_KEY.", file=sys.stderr)
        return 2
    cfg = apisports.effective(cfg)
    store = store or BufferedStore(FirestoreStore())
    now_ts = time.time() if now_ts is None else now_ts
    if not force and not apisports.live_due(store, cfg, now_ts):
        print(f"ao vivo: intervalo mínimo do plano {cfg['apisports']['plan']} "
              f"({cfg['apisports'].get('live_min_interval_minutes', 30)} min) ainda não passou.")
        return 0
    budget, used = live_budget(store, cfg["apisports"], max_calls)
    if budget < 1:
        print(f"ao vivo: sem cota livre (usadas {used}, reserva das coletas completas preservada).")
        return 0
    client = (client_factory or (lambda b: apisports.Client(key, budget=b)))(budget)
    out = apisports.run_live(client, store, cfg, now_ts=now_ts)
    print("ao vivo:", json.dumps(out, ensure_ascii=False))
    if hasattr(store, "flush"):
        store.flush()
    return 0


def odds_budget(store, acfg, override=None):
    """Chamadas para as odds, preservando a reserva das demais coletas do dia."""
    today = today_utc().isoformat()
    quota = store.get_meta("quota_apisports")
    used = quota.get("used", 0) if quota.get("date") == today else 0
    left = acfg.get("daily_call_limit", 90) - used - acfg.get("odds_reserve", 12)
    return max(0, min(override or acfg.get("odds_calls_per_run", 4), left)), used


def run_odds_cli(cfg, max_calls=None, store=None, client_factory=None, now_ts=None, refresh_agenda=True):
    """Coleta diária de odds de Over/Under (só API-Sports). Fase 1: só grava, o painel não mostra."""
    from . import apisports, odds
    key = os.environ.get("APISPORTS_KEY")
    if not key and client_factory is None:
        print("Defina APISPORTS_KEY.", file=sys.stderr)
        return 2
    cfg = apisports.effective(cfg)
    store = store or BufferedStore(FirestoreStore())
    plan = cfg["apisports"].get("plan", "free")
    if store.get_meta("odds").get("blockedPlan") == plan:
        print(f"odds: o plano {plan} não libera odds da temporada atual; nada a fazer até trocar de plano.")
        return 0
    if refresh_agenda:
        # agenda recém-atualizada: traz a temporada de cada liga, exigida pelo endpoint de odds (1 chamada)
        run_live_cli(cfg, 1, store=store, client_factory=client_factory, now_ts=now_ts, force=True)
    budget, used = odds_budget(store, cfg["apisports"], max_calls)
    if budget < 1:
        print(f"odds: sem cota livre (usadas {used}, reserva das demais coletas preservada).")
        return 0
    client = (client_factory or (lambda b: apisports.Client(key, budget=b)))(budget)
    out = odds.run_odds(client, store, cfg, now_ts=now_ts)
    print("odds:", json.dumps(out, ensure_ascii=False))
    if hasattr(store, "flush"):
        store.flush()
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--max-calls", type=int, default=None)
    r.add_argument("--only", choices=["basketballapi", "apisports", "backtest", "live", "odds"], default=None)
    r.add_argument("--force", action="store_true", help="ao vivo: ignora o intervalo mínimo do plano (usado antes das odds)")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.only == "live":
        return run_live_cli(cfg, args.max_calls, force=args.force)
    if args.only == "odds":
        return run_odds_cli(cfg, args.max_calls)
    key_bba = os.environ.get("BASKETBALL_API_KEY")
    key_as = os.environ.get("APISPORTS_KEY")
    if not key_bba and not key_as:
        print("Defina BASKETBALL_API_KEY e/ou APISPORTS_KEY.", file=sys.stderr)
        return 2
    store = BufferedStore(FirestoreStore())
    failures = 0
    if args.only == "backtest":
        from . import backtest
        print("backtest:", backtest.run(store, "forcar"))
        return 0

    if key_as and args.only in (None, "apisports"):
        from . import apisports
        acfg = apisports.effective(cfg)["apisports"]
        budget, used = daily_budget(store, acfg, "quota_apisports", "daily_call_limit", "per_run_call_limit", args.max_calls)
        if budget >= 2:
            try:
                c = apisports.Client(key_as, budget=budget)
                out = apisports.run(c, store, apisports.effective(cfg))
                print("api-sports:", json.dumps({"calls": c.calls, **out}, ensure_ascii=False))
            except Exception as e:  # uma fonte com problema não derruba a outra
                failures += 1
                print("api-sports falhou:", e, file=sys.stderr)
            finally:
                print("api-sports: documentos gravados:", store.flush())
        else:
            print(f"api-sports: cota diária quase esgotada (usadas {used}).")

    if key_bba and args.only in (None, "basketballapi"):
        budget, used = daily_budget(store, cfg, "quota", "daily_call_limit", "per_run_call_limit", args.max_calls)
        if budget >= 3:
            try:
                client = Client(key_bba, budget=budget)
                summary = run(client, store, cfg)
                print("basketballapi:", json.dumps({"calls": client.calls, **summary}, ensure_ascii=False))
            except Exception as e:
                failures += 1
                print("basketballapi falhou:", e, file=sys.stderr)
            finally:
                print("basketballapi: documentos gravados:", store.flush())
        else:
            print(f"basketballapi: cota diária quase esgotada (usadas {used}).")
    if args.only is None:
        try:
            from . import backtest
            out = backtest.run(store, today_utc().isoformat())
            if out:
                print("backtest:", out)
        except Exception as e:
            failures += 1
            print("backtest falhou:", e, file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
