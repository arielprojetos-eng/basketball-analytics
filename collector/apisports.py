"""Segunda fonte: API-Sports Basketball (v1.basketball.api-sports.io), mesma chave da API-Football.

Vantagem: /games?date=AAAA-MM-DD devolve todos os jogos do dia, no mundo inteiro,
já com os pontos de cada quarto. Uma chamada por data, em vez de uma por jogo.

Particularidade: erros de plano e de cota vêm com HTTP 200 e o campo "errors" preenchido.
"""
import time
from datetime import date, timedelta

import requests

from .api import BudgetExhausted
from .main import competition_allowed, competition_tier, record_game, scores_match, today_utc
from .store import now_iso

BASE = "https://v1.basketball.api-sports.io"
SRC = "apisports"


class PlanRestricted(Exception):
    """O plano gratuito não libera essa data ou temporada."""


class QuotaExceeded(Exception):
    pass


class Client:
    def __init__(self, key, budget=25, min_interval=6.5, session=None, sleep=time.sleep):
        self.key, self.budget, self.min_interval = key, budget, min_interval
        self.session = session or requests.Session()
        self.sleep = sleep
        self.calls = 0
        self._last = 0.0

    def remaining(self):
        return self.budget - self.calls

    def get(self, path, params):
        for attempt in range(3):
            if self.calls >= self.budget:
                raise BudgetExhausted()
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0 and self._last:
                self.sleep(wait)
            self.calls += 1
            self._last = time.monotonic()
            resp = self.session.get(BASE + path, params=params,
                                    headers={"x-apisports-key": self.key}, timeout=30)
            if resp.status_code == 429 and attempt < 2:
                self.sleep(20)
                continue
            resp.raise_for_status()
            body = resp.json()
            errors = body.get("errors")
            if errors:
                text = " ".join(str(v) for v in (errors.values() if isinstance(errors, dict) else errors))
                keys = set(errors) if isinstance(errors, dict) else set()
                if "rateLimit" in keys and attempt < 2:
                    self.sleep(20)
                    continue
                if "requests" in keys or "limit" in text.lower() and "day" in text.lower():
                    raise QuotaExceeded(text)
                if "plan" in keys or "plan" in text.lower():
                    raise PlanRestricted(text)
                raise RuntimeError(f"API-Sports: {text}")
            return body.get("response") or []
        raise RuntimeError("API-Sports: limite por minuto persistente")


def normalize(g, cfg):
    """Converte um jogo da API-Sports para o formato do projeto. None se não servir."""
    status = (g.get("status") or {}).get("short")
    if status not in cfg.get("apisports", {}).get("finished_status", ["FT", "AOT"]):
        return None
    sc = g.get("scores") or {}
    sh, sa = sc.get("home") or {}, sc.get("away") or {}
    try:
        home = [int(sh[f"quarter_{i}"]) for i in range(1, 5)]
        away = [int(sa[f"quarter_{i}"]) for i in range(1, 5)]
    except (KeyError, TypeError, ValueError):
        return None
    oth, ota = sh.get("over_time"), sa.get("over_time")
    if oth is not None and ota is not None:
        try:
            home.append(int(oth)); away.append(int(ota))
        except (TypeError, ValueError):
            pass
    if not scores_match((home, away), sh.get("total"), sa.get("total")):
        return None
    league = g.get("league") or {}
    teams = g.get("teams") or {}
    th, ta = teams.get("home") or {}, teams.get("away") or {}
    if not th.get("id") or not ta.get("id") or not league.get("id"):
        return None
    cname = comp_name(g)
    tip = (g.get("date") or "")[:19] + "Z"
    d = tip[:10]
    game = {
        "id": f"as_gm_{g['id']}",
        "competitionId": f"as_cp_{league['id']}",
        "competitionName": cname,
        "season": str(league.get("season") or ""),
        "date": d,
        "tipOff": tip,
        "sortKey": f"{tip}|as_gm_{g['id']}",
        "homeId": f"as_tm_{th['id']}",
        "homeName": th.get("name"),
        "awayId": f"as_tm_{ta['id']}",
        "awayName": ta.get("name"),
        "homeScore": sh.get("total"),
        "awayScore": sa.get("total"),
        "status": "final",
        "tier": competition_tier(cname, cfg),
        "periodsFetched": True,
        "hasQuarters": True,
        "periods": {"home": home, "away": away},
        "source": SRC,
        "fetchedAt": now_iso(),
    }
    return game, (home, away)


def ingest_rows(store, cfg, rows):
    """Grava os jogos finalizados. Não usa a coleção games: a deduplicação é feita
    pelo histórico de cada equipe, o que economiza gravações no Firestore."""
    new = 0
    for g in rows:
        p = normalize(g, cfg)
        if not p or not competition_allowed(p[0]["competitionName"], cfg):
            continue
        if record_game(store, p[0], p[1], cfg):
            new += 1
    return new


def ingest_date(client, store, cfg, d):
    rows = client.get("/games", {"date": d.isoformat(), "timezone": "UTC"})
    return ingest_rows(store, cfg, rows)


def comp_name(g):
    league = g.get("league") or {}
    country = (g.get("country") or {}).get("name")
    lname = league.get("name") or "Liga"
    return f"{lname} ({country})" if country and country.lower() not in lname.lower() else lname


def agenda_entry(g, cfg):
    """Versão compacta de um jogo (agendado, em andamento ou encerrado) para a tela de jogos."""
    league = g.get("league") or {}
    teams = g.get("teams") or {}
    th, ta = teams.get("home") or {}, teams.get("away") or {}
    if not th.get("id") or not ta.get("id") or not league.get("id"):
        return None
    ts = g.get("timestamp")
    if not isinstance(ts, (int, float)):
        try:
            from datetime import datetime
            ts = int(datetime.fromisoformat((g.get("date") or "").replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    sc = g.get("scores") or {}
    name = comp_name(g)
    if not competition_allowed(name, cfg):
        return None
    sh, sa = sc.get("home") or {}, sc.get("away") or {}
    entry = {
        "id": f"as_gm_{g['id']}", "t": int(ts), "st": (g.get("status") or {}).get("short") or "",
        "lg": f"as_cp_{league['id']}", "ln": name, "tier": competition_tier(name, cfg),
        "h": f"as_tm_{th['id']}", "hn": th.get("name"), "a": f"as_tm_{ta['id']}", "an": ta.get("name"),
        "hs": sh.get("total"), "as": sa.get("total"),
    }
    # Quartos (parciais, durante o jogo): permitem ao painel calcular as chances ao vivo sozinho.
    hq, aq = quarter_list(sh), quarter_list(sa)
    if any(x is not None for x in hq + aq):
        entry["hq"], entry["aq"] = hq, aq
    return entry


def quarter_list(side):
    out = []
    for i in range(1, 5):
        v = side.get(f"quarter_{i}")
        try:
            out.append(int(v) if v is not None else None)
        except (TypeError, ValueError):
            out.append(None)
    return out


def effective(cfg):
    """Configuração com os limites do plano escolhido em apisports.plan ("free" ou "pro") aplicados.

    Trocar de plano é só mudar apisports.plan em collector/config.json (a chave continua no Secret).
    """
    a = dict(cfg.get("apisports", {}))
    plan = a.get("plan", "free")
    a.update((a.get("plans") or {}).get(plan, {}))
    a["plan"] = plan
    return {**cfg, "apisports": a}


def agenda_window(today):
    """Janela do documento meta/agenda: início de ontem até o fim de amanhã em Brasília, com folga."""
    from datetime import datetime, time, timezone as tz
    start = int(datetime.combine(today - timedelta(days=1), time(0), tzinfo=tz.utc).timestamp()) - 6 * 3600
    end = int(datetime.combine(today + timedelta(days=2), time(12), tzinfo=tz.utc).timestamp())
    return start, end


def merge_agenda(old_games, new_games, today):
    """Atualiza a agenda com os jogos novos (mesmo id substitui) e descarta o que saiu da janela."""
    start, end = agenda_window(today)
    by_id = {x["id"]: x for x in old_games or []}
    for x in new_games:
        by_id[x["id"]] = x
    return sorted((x for x in by_id.values() if start <= x["t"] <= end), key=lambda x: (x["t"], x["id"]))


def backfill(client, store, cfg, reserve=0, today=None):
    """Volta um dia por chamada enquanto houver orçamento. Para se o plano bloquear."""
    today = today or today_utc()
    state = store.get_meta("backfill_apisports")
    if state.get("blocked"):
        return 0, "blocked"
    acfg = cfg.get("apisports", {})
    floor = today - timedelta(days=acfg.get("backfill_floor_days", 400))
    nxt = date.fromisoformat(state["nextDate"]) if state.get("nextDate") else today - timedelta(days=2)
    # No plano pago sobra cota de chamadas; o limite passa a ser a cota de gravações do Firestore.
    max_days = acfg.get("backfill_days_per_run") or 10 ** 6
    new = days = 0
    try:
        while client.remaining() > reserve and nxt >= floor and days < max_days:
            days += 1
            new += ingest_date(client, store, cfg, nxt)
            nxt -= timedelta(days=1)
            store.set_meta("backfill_apisports", {"nextDate": nxt.isoformat(), "at": now_iso()})
    except PlanRestricted as e:
        store.set_meta("backfill_apisports", {"nextDate": nxt.isoformat(), "blocked": True,
                                              "reason": str(e)[:300], "at": now_iso()})
        return new, "blocked"
    return new, "done" if nxt < floor else "ok"


def run(client, store, cfg, today=None):
    today = today or today_utc()
    quota = store.get_meta("quota_apisports")
    if quota.get("date") != today.isoformat():
        quota = {"date": today.isoformat(), "used": 0}
    summary = {"new": 0, "backfillNew": 0, "backfill": None, "agenda": 0, "note": ""}
    agenda = []
    try:
        # Ontem até depois de amanhã (UTC): cobre ontem, hoje e amanhã inteiros no horário de Brasília,
        # inclusive os jogos noturnos (ex.: NBA às 21h-24h, que já caem no dia seguinte em UTC).
        for d in (today - timedelta(days=1), today, today + timedelta(days=1), today + timedelta(days=2)):
            try:
                rows = client.get("/games", {"date": d.isoformat(), "timezone": "UTC"})
            except PlanRestricted as e:
                summary["note"] = f"plano bloqueou {d.isoformat()}: {e}"[:300]
                continue
            summary["new"] += ingest_rows(store, cfg, rows)
            agenda.extend(x for x in (agenda_entry(g, cfg) for g in rows) if x)
        summary["backfillNew"], summary["backfill"] = backfill(client, store, cfg, today=today)
    except BudgetExhausted:
        summary["note"] = summary["note"] or "orçamento da execução esgotado"
    except QuotaExceeded as e:
        summary["note"] = f"cota diária esgotada: {e}"[:300]
        quota["used"] = cfg.get("apisports", {}).get("daily_call_limit", 90)
    finally:
        if agenda:
            # Janela fixa para o documento não crescer; a coleta completa reconstrói a agenda inteira.
            games = merge_agenda([], agenda, today)
            store.set_meta("agenda", {"updatedAt": now_iso(), "games": games})
            summary["agenda"] = len(games)
        quota["used"] = quota.get("used", 0) + client.calls
        store.set_meta("quota_apisports", quota)
        store.set_meta("status_apisports", {"lastRun": now_iso(), "callsThisRun": client.calls,
                                            "usedToday": quota["used"], "lastSummary": summary})
    return summary


LIVE_STATUS = {"Q1", "Q2", "Q3", "Q4", "OT", "BT", "HT"}


def live_due(store, cfg, now_ts):
    """A varredura ao vivo respeita o intervalo mínimo do plano (o agendador pode chamar mais vezes)."""
    last = store.get_meta("status_live").get("lastTs") or 0
    gap = cfg.get("apisports", {}).get("live_min_interval_minutes", 30) * 60
    # folga para o atraso normal do agendador do GitHub (minutos): 5 min, ou metade do intervalo
    return now_ts - last >= gap - min(300, gap / 2)


def run_live(client, store, cfg, today=None, now_ts=None):
    """Varredura curta: só atualiza os placares (com quartos) na agenda.

    Não grava nas equipes: jogos encerrados entram no histórico pela coleta completa, o que evita
    duas execuções gravando o mesmo documento de equipe ao mesmo tempo. Usa 1 chamada
    (2 de madrugada em UTC, quando ainda há jogos que começaram na data UTC anterior).
    """
    import time as _t
    today = today or today_utc()
    now_ts = int(now_ts if now_ts is not None else _t.time())
    quota = store.get_meta("quota_apisports")
    if quota.get("date") != today.isoformat():
        quota = {"date": today.isoformat(), "used": 0}
    dates = [today]
    if (now_ts % 86400) < 6 * 3600:
        dates.insert(0, today - timedelta(days=1))
    fresh, note = [], ""
    try:
        for d in dates:
            try:
                rows = client.get("/games", {"date": d.isoformat(), "timezone": "UTC"})
            except PlanRestricted as e:
                note = f"plano bloqueou {d.isoformat()}: {e}"[:300]
                continue
            fresh.extend(x for x in (agenda_entry(g, cfg) for g in rows) if x)
    except BudgetExhausted:
        note = note or "orçamento da execução esgotado"
    except QuotaExceeded as e:
        note = f"cota diária esgotada: {e}"[:300]
        quota["used"] = cfg.get("apisports", {}).get("daily_call_limit", 90)
    finally:
        live = sum(1 for x in fresh if x["st"] in LIVE_STATUS)
        if fresh:
            old = store.get_meta("agenda").get("games") or []
            store.set_meta("agenda", {"updatedAt": now_iso(), "games": merge_agenda(old, fresh, today),
                                      "liveAt": now_iso()})
        quota["used"] = quota.get("used", 0) + client.calls
        store.set_meta("quota_apisports", quota)
        store.set_meta("status_live", {"lastRun": now_iso(), "lastTs": now_ts, "calls": client.calls,
                                       "games": len(fresh), "live": live, "note": note,
                                       "plan": cfg.get("apisports", {}).get("plan", "free")})
    return {"games": len(fresh), "live": live, "calls": client.calls, "note": note}
