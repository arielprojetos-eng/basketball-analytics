import unittest
from datetime import date

from collector import apisports as a
from collector.store import MemoryStore

CFG = {"keep_games_per_team": 60, "priority_competitions": ["NBB"], "only_competitions": [],
       "apisports": {"daily_call_limit": 90, "backfill_floor_days": 5, "finished_status": ["FT", "AOT"]}}


def g(gid, d="2026-11-14", status="FT", q=(20, 22, 25, 18), oq=(19, 21, 20, 22), ot=None, oot=None,
      league=("26", "NBB"), country="Brazil", home=(1, "Flamengo"), away=(2, "Franca")):
    sh = {f"quarter_{i+1}": v for i, v in enumerate(q)}; sh.update(over_time=ot, total=sum(q) + (ot or 0))
    sa = {f"quarter_{i+1}": v for i, v in enumerate(oq)}; sa.update(over_time=oot, total=sum(oq) + (oot or 0))
    return {"id": gid, "date": d + "T22:00:00+00:00", "status": {"short": status},
            "league": {"id": league[0], "name": league[1], "season": "2025-2026"}, "country": {"name": country},
            "teams": {"home": {"id": home[0], "name": home[1]}, "away": {"id": away[0], "name": away[1]}},
            "scores": {"home": sh, "away": sa}}


class R:
    def __init__(self, body, status=200):
        self.status_code, self._b = status, body

    def json(self):
        return self._b

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class S:
    def __init__(self, by_date, plan_before=None, quota=False):
        self.by_date, self.plan_before, self.quota, self.calls = by_date, plan_before, quota, []

    def get(self, url, params=None, headers=None, timeout=None):
        assert headers == {"x-apisports-key": "k"}
        self.calls.append(params["date"])
        if self.quota:
            return R({"errors": {"requests": "You have reached the request limit for the day"}, "response": []})
        if self.plan_before and params["date"] < self.plan_before:
            return R({"errors": {"plan": "Free plans do not have access to this date"}, "response": []})
        return R({"errors": [], "response": self.by_date.get(params["date"], [])})


def cl(s, budget=25):
    return a.Client("k", budget=budget, session=s, min_interval=0, sleep=lambda x: None)


class ApiSportsTests(unittest.TestCase):
    def test_normalize(self):
        game, (h, w) = a.normalize(g(10, ot=8, oot=5, status="AOT"), CFG)
        self.assertEqual(game["id"], "as_gm_10")
        self.assertEqual(game["competitionName"], "NBB (Brazil)")
        self.assertEqual(game["homeId"], "as_tm_1")
        self.assertEqual(h, [20, 22, 25, 18, 8]); self.assertEqual(w, [19, 21, 20, 22, 5])
        self.assertEqual(game["tier"], 0)
        self.assertIsNone(a.normalize(g(11, status="Q3"), CFG))  # em andamento
        bad = g(12); bad["scores"]["home"]["quarter_3"] = None
        self.assertIsNone(a.normalize(bad, CFG))  # sem quartos completos
        self.assertEqual(a.normalize(g(13, country="USA", league=("12", "NBA USA")), CFG)[0]["competitionName"], "NBA USA")

    def test_run_grava_e_nao_duplica(self):
        s = S({"2026-11-14": [g(1), g(2, status="NS")], "2026-11-15": [g(3, d="2026-11-15")]})
        st = MemoryStore()
        out = a.run(cl(s), st, CFG, today=date(2026, 11, 15))
        self.assertEqual(out["new"], 2)
        fla = st.get_team("as_tm_1")
        self.assertEqual(fla["n"], 2)
        self.assertEqual(fla["games"][0]["gid"], "as_gm_3")
        self.assertEqual(st.get_team("as_tm_2")["games"][0]["pts"], [19, 21, 20, 22])
        self.assertEqual(st.meta["index"]["competitions"]["as_cp_26"]["src"], "apisports")
        self.assertEqual(st.meta["quota_apisports"]["used"], len(s.calls))
        a.run(cl(s), st, CFG, today=date(2026, 11, 15))
        self.assertEqual(st.get_team("as_tm_1")["n"], 2)

    def test_agenda_inclui_agendados_e_amanha(self):
        s = S({"2026-11-14": [g(1)], "2026-11-15": [g(2, d="2026-11-15", status="NS")],
               "2026-11-16": [g(3, d="2026-11-16", status="NS"), g(1)]})
        st = MemoryStore()
        out = a.run(cl(s), st, CFG, today=date(2026, 11, 15))
        self.assertEqual(s.calls[:4], ["2026-11-14", "2026-11-15", "2026-11-16", "2026-11-17"])
        ag = st.meta["agenda"]["games"]
        self.assertEqual([x["id"] for x in ag], ["as_gm_1", "as_gm_2", "as_gm_3"])  # sem duplicar, em ordem
        self.assertEqual(out["agenda"], 3)
        self.assertEqual(ag[1]["st"], "NS")
        self.assertEqual(ag[0]["ln"], "NBB (Brazil)")
        self.assertEqual(ag[0]["h"], "as_tm_1")
        self.assertIsNone(st.get_team("as_tm_9"))
        self.assertEqual(st.get_team("as_tm_1")["n"], 1)  # agendados não entram no histórico

    def test_agenda_janela(self):
        far = g(50, d="2026-11-10", status="FT")  # fora da janela
        s = S({"2026-11-15": [g(2, d="2026-11-15", status="NS"), far]})
        st = MemoryStore()
        a.run(cl(s), st, CFG, today=date(2026, 11, 15))
        self.assertEqual([x["id"] for x in st.meta["agenda"]["games"]], ["as_gm_2"])

    def test_backfill_ate_o_limite(self):
        s = S({"2026-11-12": [g(7, d="2026-11-12")]})
        st = MemoryStore()
        out = a.run(cl(s), st, CFG, today=date(2026, 11, 15))
        self.assertEqual(out["backfill"], "done")
        self.assertIn("2026-11-10", s.calls)
        self.assertNotIn("2026-11-09", s.calls)  # floor de 5 dias
        self.assertEqual(out["backfillNew"], 1)

    def test_backfill_bloqueado_pelo_plano(self):
        s = S({}, plan_before="2026-11-13")
        st = MemoryStore()
        out = a.run(cl(s), st, CFG, today=date(2026, 11, 15))
        self.assertEqual(out["backfill"], "blocked")
        self.assertTrue(st.meta["backfill_apisports"]["blocked"])
        n = len(s.calls)
        a.run(cl(s), st, CFG, today=date(2026, 11, 15))
        self.assertEqual(len(s.calls) - n, 4)  # ontem até depois de amanhã

    def test_cota_e_orcamento(self):
        st = MemoryStore()
        out = a.run(cl(S({}, quota=True)), st, CFG, today=date(2026, 11, 15))
        self.assertIn("cota", out["note"])
        self.assertEqual(st.meta["quota_apisports"]["used"], 90 + 1)
        s = S({})
        c = cl(s, budget=3)
        a.run(c, MemoryStore(), CFG, today=date(2026, 11, 15))
        self.assertEqual(len(s.calls), 3)


def live_game(gid, d, st, q, oq):
    x = g(gid, d=d, status=st, q=(0, 0, 0, 0), oq=(0, 0, 0, 0))
    for side, vals in (("home", q), ("away", oq)):
        for i in range(4):
            x["scores"][side][f"quarter_{i+1}"] = vals[i] if i < len(vals) else None
        x["scores"][side]["total"] = sum(vals)
    return x


NOON = 1794744000  # 2026-11-15 12:00 UTC


class AoVivoTests(unittest.TestCase):
    def test_agenda_traz_quartos_parciais(self):
        e = a.agenda_entry(live_game(5, "2026-11-15", "HT", (27, 23), (23, 17)), CFG)
        self.assertEqual(e["hq"], [27, 23, None, None])
        self.assertEqual(e["aq"], [23, 17, None, None])
        self.assertEqual((e["hs"], e["as"]), (50, 40))
        sched = {**g(6, status="NS"), "scores": {"home": {}, "away": {}}}
        self.assertNotIn("hq", a.agenda_entry(sched, CFG))  # sem placar, sem quartos

    def test_varredura_ao_vivo_atualiza_so_a_agenda(self):
        st = MemoryStore()
        st.set_meta("agenda", {"games": [
            {"id": "as_gm_5", "t": NOON - 3600, "st": "Q1", "hs": 20, "as": 18},
            {"id": "as_gm_9", "t": NOON + 86400, "st": "NS"},            # amanhã: preservado
            {"id": "as_gm_old", "t": NOON - 10 * 86400, "st": "FT"},     # fora da janela: sai
        ]})
        s = S({"2026-11-15": [live_game(5, "2026-11-15", "HT", (27, 23), (23, 17))]})
        out = a.run_live(cl(s), st, CFG, today=date(2026, 11, 15), now_ts=NOON)
        self.assertEqual(s.calls, ["2026-11-15"])           # 1 chamada ao meio-dia
        self.assertEqual(out["live"], 1)
        ids = [x["id"] for x in st.meta["agenda"]["games"]]
        self.assertEqual(sorted(ids), ["as_gm_5", "as_gm_9"])
        g5 = next(x for x in st.meta["agenda"]["games"] if x["id"] == "as_gm_5")
        self.assertEqual((g5["st"], g5["hs"], g5["hq"][:2]), ("HT", 50, [27, 23]))
        self.assertEqual(st.teams, {})                       # nada gravado nas equipes
        self.assertEqual(st.meta["quota_apisports"]["used"], 1)
        self.assertEqual(st.meta["status_live"]["lastTs"], NOON)

    def test_madrugada_busca_tambem_a_data_anterior(self):
        s = S({})
        a.run_live(cl(s), MemoryStore(), CFG, today=date(2026, 11, 15), now_ts=NOON - 9 * 3600)  # 03:00 UTC
        self.assertEqual(s.calls, ["2026-11-14", "2026-11-15"])

    def test_intervalo_minimo_do_plano(self):
        st = MemoryStore()
        cfg = a.effective({**CFG, "apisports": {**CFG["apisports"], "plan": "free",
                                                "plans": {"free": {"live_min_interval_minutes": 30}}}})
        self.assertTrue(a.live_due(st, cfg, NOON))
        st.set_meta("status_live", {"lastTs": NOON})
        self.assertFalse(a.live_due(st, cfg, NOON + 10 * 60))
        self.assertFalse(a.live_due(st, cfg, NOON + 24 * 60))
        self.assertTrue(a.live_due(st, cfg, NOON + 26 * 60))   # folga para atraso do agendador

    def test_agendador_a_cada_10_min_respeita_o_plano(self):
        import json
        import random
        from pathlib import Path
        raw = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))
        rnd = random.Random(3)
        for plan, lo, hi in (("free", 40, 48), ("pro", 140, 144)):
            cfg = a.effective({**raw, "apisports": {**raw["apisports"], "plan": plan}})
            st, runs = MemoryStore(), 0
            for i in range(144):   # um dia, disparo a cada 10 min com até 4 min de atraso
                now = NOON + i * 600 + rnd.randint(0, 240)
                if a.live_due(st, cfg, now):
                    runs += 1
                    st.set_meta("status_live", {"lastTs": now})
            self.assertTrue(lo <= runs <= hi, f"{plan}: {runs} varreduras")

    def test_troca_de_plano_pela_configuracao(self):
        import json
        from pathlib import Path
        raw = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))
        free = a.effective(raw)["apisports"]
        self.assertEqual(free["plan"], "free")
        self.assertLessEqual(free["daily_call_limit"], 100)
        # free: 48 varreduras/dia (até 2 chamadas) cabem com a reserva das coletas completas
        self.assertLessEqual(48 * 1 + 12 + free["live_reserve"], free["daily_call_limit"] + 10)
        pro = a.effective({**raw, "apisports": {**raw["apisports"], "plan": "pro"}})["apisports"]
        self.assertGreater(pro["daily_call_limit"], 1000)
        self.assertLess(pro["live_min_interval_minutes"], free["live_min_interval_minutes"])
        self.assertTrue(pro["backfill_days_per_run"])

    def test_retroativo_limitado_por_execucao(self):
        s = S({})
        cfg = {**CFG, "apisports": {**CFG["apisports"], "backfill_floor_days": 300, "backfill_days_per_run": 3}}
        a.run(cl(s, budget=50), MemoryStore(), cfg, today=date(2026, 11, 15))
        self.assertEqual(len(s.calls), 4 + 3)

    def test_cli_preserva_reserva_das_coletas(self):
        from collector import main as m
        st = MemoryStore()
        st.set_meta("quota_apisports", {"date": m.today_utc().isoformat(), "used": 75})
        calls = []
        rc = m.run_live_cli(m.load_config(), store=st, client_factory=lambda b: calls.append(b), now_ts=NOON)
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])   # 90 - 75 - reserva 20 < 1: não chama a API


def ou(name, lines):
    """Mercado de Over/Under no formato da API: lines = [(linha, odd_over, odd_under)]."""
    vals = []
    for ln, o, u in lines:
        vals += [{"value": f"Over {ln}", "odd": str(o)}, {"value": f"Under {ln}", "odd": str(u)}]
    return {"id": 99, "name": name, "values": vals}


class OddsSession:
    def __init__(self, by_league):
        self.by_league, self.calls = by_league, []

    def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/games"):   # atualização da agenda feita antes das odds
            self.calls.append(("games", params["date"]))
            return R({"errors": [], "response": []})
        assert url.endswith("/odds")
        self.calls.append((params["league"], params["season"]))
        return R({"errors": [], "response": self.by_league.get(params["league"], [])})


class OddsTests(unittest.TestCase):
    def test_mercados_por_periodo(self):
        from collector.odds import period_of
        self.assertEqual(period_of("Over/Under"), "total")
        self.assertEqual(period_of("Over/Under (Including OT)"), "total")
        self.assertEqual(period_of("Over/Under 1st Half"), "h1")
        self.assertEqual(period_of("Over/Under 2nd Half"), "h2")
        self.assertEqual(period_of("Over/Under 1st Qtr"), "q1")
        self.assertEqual(period_of("Over/Under 3rd Quarter"), "q3")
        self.assertIsNone(period_of("Home Team Over/Under"))
        self.assertIsNone(period_of("Asian Handicap 1st Qtr"))
        self.assertIsNone(period_of("Odd/Even 1st Half"))

    def test_consenso_sem_margem(self):
        from collector.odds import game_markets
        item = {"game": {"id": 7}, "bookmakers": [
            {"id": 1, "bets": [ou("Over/Under", [(170.5, 1.80, 2.00), (171.5, 1.90, 1.90), (172.5, 2.0, 1.8)]),
                               ou("Over/Under 1st Qtr", [(43.5, 1.85, 1.95)])]},
            {"id": 2, "bets": [ou("Over/Under", [(171.5, 1.95, 1.85)])]},
            {"id": 3, "bets": [ou("Over/Under", [(172.5, 1.88, 1.92)])]},
        ]}
        m = game_markets(item)
        self.assertEqual(m["total"]["line"], 171.5)          # mediana das linhas principais
        self.assertEqual(m["total"]["books"], 3)
        p1 = (1 / 1.9) / (1 / 1.9 + 1 / 1.9)
        p2 = (1 / 1.95) / (1 / 1.95 + 1 / 1.85)
        self.assertAlmostEqual(m["total"]["pOver"], round((p1 + p2) / 2, 4))
        self.assertEqual((m["total"]["lo"], m["total"]["hi"]), (171.5, 172.5))
        self.assertGreater(m["total"]["margin"], 0)
        self.assertEqual(m["q1"]["line"], 43.5)
        self.assertNotIn("h1", m)

    def test_escolhe_ligas_proximas_e_prioritarias(self):
        from collector.odds import pick_leagues
        ag = [{"id": f"g{i}", "t": NOON + 3600, "st": "NS", "lg": "as_cp_12", "ss": "2026-2027", "tier": 0} for i in range(2)]
        ag += [{"id": f"h{i}", "t": NOON + 7200, "st": "NS", "lg": "as_cp_116", "ss": "2026-2027", "tier": 1} for i in range(9)]
        ag += [{"id": "x", "t": NOON + 7200, "st": "NS", "lg": "as_cp_5", "ss": "2026", "tier": 1}]
        ag += [{"id": "old", "t": NOON - 60, "st": "FT", "lg": "as_cp_9", "ss": "2026", "tier": 0},
               {"id": "far", "t": NOON + 3 * 86400, "st": "NS", "lg": "as_cp_8", "ss": "2026", "tier": 0},
               {"id": "nos", "t": NOON + 3600, "st": "NS", "lg": "as_cp_7", "tier": 0}]  # sem temporada
        self.assertEqual(pick_leagues(ag, NOON, 2), [("12", "2026-2027"), ("116", "2026-2027")])
        self.assertEqual(len(pick_leagues(ag, NOON, 10)), 3)

    def test_coleta_grava_painel_e_historico(self):
        from collector.odds import run_odds
        st = MemoryStore()
        st.set_meta("agenda", {"games": [
            {"id": "as_gm_7", "t": NOON + 3600, "st": "NS", "lg": "as_cp_12", "ss": "2026-2027", "tier": 0, "h": "as_tm_1", "a": "as_tm_2"}]})
        st.set_meta("odds", {"games": {"as_gm_1": {"t": NOON - 86400, "m": {}}}})  # antigo: sai
        item = {"game": {"id": 7}, "bookmakers": [{"id": 1, "bets": [ou("Over/Under", [(171.5, 1.9, 1.9)])]}]}
        s = OddsSession({"12": [item]})
        out = run_odds(cl(s, budget=4), st, CFG, now_ts=NOON)
        self.assertEqual(s.calls, [("12", "2026-2027")])
        self.assertEqual(out["games"], 1)
        g = st.meta["odds"]["games"]
        self.assertEqual(list(g), ["as_gm_7"])
        self.assertEqual(g["as_gm_7"]["m"]["total"]["line"], 171.5)
        self.assertEqual(g["as_gm_7"]["h"], "as_tm_1")
        self.assertIn("as_gm_7", st.docs["odds_hist"]["2026-11-15"])
        self.assertEqual(st.meta["quota_apisports"]["used"], 1)
        self.assertEqual(st.teams, {})

    def test_cli_respeita_reserva_e_plano(self):
        from collector import main as m
        st = MemoryStore()
        st.set_meta("quota_apisports", {"date": m.today_utc().isoformat(), "used": 79})
        calls = []
        m.run_odds_cli(m.load_config(), store=st, client_factory=lambda b: calls.append(b), now_ts=NOON)
        self.assertEqual(calls, [])   # 90 - 79 - reserva 12 < 1
        st.set_meta("quota_apisports", {"date": m.today_utc().isoformat(), "used": 50})
        budget, _ = m.odds_budget(st, a.effective(m.load_config())["apisports"])
        self.assertEqual(budget, 4)   # plano gratuito: 4 chamadas por dia

    def test_plano_que_recusa_odds_nao_e_tentado_de_novo(self):
        from collector import main as m
        from collector.odds import run_odds

        class Recusa:
            calls = 0

            def get(self, url, params=None, headers=None, timeout=None):
                Recusa.calls += 1
                return R({"errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."}, "response": []})

        st = MemoryStore()
        st.set_meta("agenda", {"games": [{"id": "as_gm_7", "t": NOON + 3600, "st": "NS", "lg": "as_cp_12", "ss": "2026-2027", "tier": 0}]})
        cfg = a.effective(m.load_config())
        out = run_odds(cl(Recusa(), budget=4), st, cfg, now_ts=NOON)
        self.assertEqual(Recusa.calls, 1)                    # para na primeira recusa
        self.assertIn("plano", out["note"])
        self.assertEqual(st.meta["odds"]["blockedPlan"], "free")
        made = []
        m.run_odds_cli(m.load_config(), store=st, client_factory=lambda b: made.append(b), now_ts=NOON)
        self.assertEqual(made, [])                           # nem a agenda é atualizada à toa
        pro = {**m.load_config()}
        pro["apisports"] = {**pro["apisports"], "plan": "pro"}
        st.set_meta("quota_apisports", {"date": m.today_utc().isoformat(), "used": 0})
        tried = []
        m.run_odds_cli(pro, store=st, client_factory=lambda b: tried.append(b) or cl(OddsSession({}), budget=b), now_ts=NOON)
        self.assertTrue(tried)                               # trocou de plano: tenta de novo

    def test_agenda_traz_temporada(self):
        self.assertEqual(a.agenda_entry(g(5), CFG)["ss"], "2025-2026")


class BufferTests(unittest.TestCase):
    def test_grava_cada_equipe_uma_vez(self):
        from collector.store import BufferedStore

        class Counting(MemoryStore):
            writes = 0

            def put_team(self, tid, data):
                Counting.writes += 1
                super().put_team(tid, data)

            def set_meta(self, name, data):
                Counting.writes += 1
                super().set_meta(name, data)

        inner = Counting()
        games = [g(i, d="2026-11-14") for i in range(1, 11)]  # 10 jogos, mesmas 2 equipes
        s = S({"2026-11-14": games})
        st = BufferedStore(inner)
        cfg = {**CFG, "apisports": {**CFG["apisports"], "backfill_floor_days": 1}}
        a.run(cl(s), st, cfg, today=date(2026, 11, 15))
        before = Counting.writes
        st.flush()
        self.assertEqual(Counting.writes - before, 3)  # 2 equipes + índice
        self.assertEqual(inner.get_team("as_tm_1")["n"], 10)
        self.assertIn("as_cp_26", inner.meta["index"]["competitions"])
        # segunda execução com os mesmos jogos: nada é regravado
        st2 = BufferedStore(inner)
        a.run(cl(S({"2026-11-14": games})), st2, cfg, today=date(2026, 11, 15))
        self.assertEqual(st2.flush(), 0)


if __name__ == "__main__":
    unittest.main()
