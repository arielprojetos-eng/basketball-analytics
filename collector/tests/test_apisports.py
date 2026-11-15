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
        self.assertEqual(len(s.calls) - n, 2)  # só ontem e hoje

    def test_cota_e_orcamento(self):
        st = MemoryStore()
        out = a.run(cl(S({}, quota=True)), st, CFG, today=date(2026, 11, 15))
        self.assertIn("cota", out["note"])
        self.assertEqual(st.meta["quota_apisports"]["used"], 90 + 1)
        s = S({})
        c = cl(s, budget=3)
        a.run(c, MemoryStore(), CFG, today=date(2026, 11, 15))
        self.assertEqual(len(s.calls), 3)


if __name__ == "__main__":
    unittest.main()
