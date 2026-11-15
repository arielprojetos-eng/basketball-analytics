import unittest
from datetime import date

from collector import main as m
from collector.api import ApiError, BudgetExhausted, Client, UpgradeRequired
from collector.store import MemoryStore

CFG = {"daily_call_limit": 92, "keep_games_per_team": 3, "priority_competitions": ["NBB"],
       "only_competitions": [], "discovery_days_back": 2, "backfill_floor_days": 400}


def game(gid, comp="Liga X", d="2026-11-14", home=("tm_a", "Alfa"), away=("tm_b", "Beta")):
    return {"id": gid, "competition": {"id": "cp_" + comp, "name": comp}, "season": {"name": "2026"},
            "date": d, "tip_off": d + "T20:00:00Z", "status": "final",
            "home": {"id": home[0], "name": home[1]}, "away": {"id": away[0], "name": away[1]},
            "home_score": None, "away_score": None}


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._b, self.text = status, body, str(body)

    def json(self):
        return self._b


class FakeSession:
    """Simula a API: listagens em /games e detalhes em /games/{id}."""

    def __init__(self, listing, details, blocked_dates=False):
        self.listing, self.details, self.blocked_dates = listing, details, blocked_dates
        self.urls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.urls.append((url, dict(params or {})))
        path = url.split("/v1")[1]
        if path == "/games":
            if self.blocked_dates and "date" in params:
                return FakeResp(403, {"error": {"code": "upgrade_required", "message": "plano"}})
            rows = self.listing.get(params.get("date") or "recent", [])
            return FakeResp(200, {"data": rows, "meta": {"total_pages": 1}})
        gid = path.split("/")[2]
        return FakeResp(200, {"data": {"id": gid, "periods": self.details.get(gid)}, "meta": {}})


def client(session, budget=30):
    return Client("k", budget=budget, session=session, min_interval=0, sleep=lambda s: None)


class CollectorTests(unittest.TestCase):
    def test_fluxo_completo_e_trim(self):
        games = [game(f"gm_{i}", d=f"2026-11-{10+i:02d}") for i in range(4)]
        details = {f"gm_{i}": {"home": [20 + i, 25, 22, 23], "away": [18, 20, 21, 19]} for i in range(4)}
        details["gm_3"] = {"home": [20, 25, 22, 23, 6], "away": [18, 20, 21, 19, 4]}  # prorrogação
        s = FakeSession({"recent": games}, details)
        store = MemoryStore()
        summary = m.run(client(s), store, CFG, today=date(2026, 11, 15))
        self.assertEqual(summary["new"], 4)
        self.assertEqual(summary["details"], 4)
        alfa = store.get_team("tm_a")
        self.assertEqual(alfa["n"], 3)  # trim em 3
        self.assertEqual(alfa["games"][0]["gid"], "gm_3")  # mais recente primeiro
        self.assertEqual(alfa["games"][0]["ot"], 6)
        self.assertEqual(alfa["games"][0]["oppOt"], 4)
        beta = store.get_team("tm_b")
        self.assertEqual(beta["games"][0]["pts"], [18, 20, 21, 19])
        self.assertEqual(beta["games"][0]["oppPts"], [20, 25, 22, 23])
        self.assertFalse(beta["games"][0]["home"])
        self.assertEqual(store.meta["index"]["competitions"]["cp_Liga X"]["teams"]["tm_a"]["n"], 3)
        self.assertEqual(store.meta["quota"]["used"], store.meta["status"]["callsThisRun"])

    def test_nao_duplica_e_nao_regasta_chamada(self):
        games = [game("gm_1")]
        details = {"gm_1": {"home": [1, 2, 3, 4], "away": [4, 3, 2, 1]}}
        store = MemoryStore()
        m.run(client(FakeSession({"recent": games}, details)), store, CFG, today=date(2026, 11, 15))
        s2 = FakeSession({"recent": games}, details)
        c2 = client(s2)
        summary = m.run(c2, store, CFG, today=date(2026, 11, 15))
        self.assertEqual(summary["new"], 0)
        self.assertEqual(store.get_team("tm_a")["n"], 1)
        self.assertNotIn("/games/gm_1", [u[0].split("/v1")[1] for u in s2.urls])

    def test_sem_quartos_marca_e_nao_repete(self):
        store = MemoryStore()
        s = FakeSession({"recent": [game("gm_9")]}, {"gm_9": None})
        m.run(client(s), store, CFG, today=date(2026, 11, 15))
        self.assertTrue(store.games["gm_9"]["periodsFetched"])
        self.assertFalse(store.games["gm_9"]["hasQuarters"])
        self.assertIsNone(store.get_team("tm_a"))

    def test_periodos_invalidos(self):
        self.assertIsNone(m.valid_periods({"home": [1, 2], "away": [1, 2]}))
        self.assertIsNone(m.valid_periods({"home": [1, 2, 3, 4], "away": [1, 2, 3]}))
        self.assertIsNone(m.valid_periods({"home": [1, 2, 3, "x"], "away": [1, 2, 3, 4]}))
        self.assertEqual(m.valid_periods({"home": [1, 2, 3, 4], "away": [5, 6, 7, 8]}), ([1, 2, 3, 4], [5, 6, 7, 8]))

    def test_prioridade_de_ligas(self):
        store = MemoryStore()
        games = [game("gm_a", comp="Outra", d="2026-11-14"), game("gm_b", comp="NBB", d="2026-11-10")]
        m.ingest_listing(store, games, CFG)
        self.assertEqual(store.pending_games(1)[0]["id"], "gm_b")  # NBB primeiro mesmo sendo mais antigo

    def test_filtro_de_competicoes(self):
        store = MemoryStore()
        cfg = {**CFG, "only_competitions": ["nbb"]}
        m.ingest_listing(store, [game("1", comp="NBB"), game("2", comp="Outra")], cfg)
        self.assertEqual(set(store.games), {"1"})

    def test_orcamento_respeitado(self):
        games = [game(f"gm_{i}") for i in range(10)]
        details = {f"gm_{i}": {"home": [1, 2, 3, 4], "away": [4, 3, 2, 1]} for i in range(10)}
        s = FakeSession({"recent": games}, details)
        c = client(s, budget=4)
        m.run(c, MemoryStore(), CFG, today=date(2026, 11, 15))
        self.assertLessEqual(c.calls, 4)
        self.assertLessEqual(len(s.urls), 4)

    def test_backfill_bloqueado_registra_e_para(self):
        store = MemoryStore()
        s = FakeSession({"recent": []}, {}, blocked_dates=True)
        m.run(client(s), store, CFG, today=date(2026, 11, 15))
        self.assertTrue(store.meta["backfill"]["blocked"])
        calls_before = len(s.urls)
        m.run(client(s), store, CFG, today=date(2026, 11, 15))
        self.assertEqual(len(s.urls) - calls_before, 1)  # só a descoberta, sem tentar de novo

    def test_backfill_avanca_um_dia_por_vez(self):
        store = MemoryStore()
        old = game("gm_old", d="2026-11-12")
        s = FakeSession({"recent": [], "2026-11-12": [old]}, {"gm_old": {"home": [1, 2, 3, 4], "away": [4, 3, 2, 1]}})
        m.run(client(s), store, CFG, today=date(2026, 11, 15))
        self.assertEqual(store.meta["backfill"]["lastDate"], "2026-11-12")
        self.assertIn("gm_old", store.games)

    def test_cota_diaria_acumula_e_zera(self):
        store = MemoryStore()
        s = FakeSession({"recent": []}, {})
        m.run(client(s), store, CFG, today=date(2026, 11, 15))
        used1 = store.meta["quota"]["used"]
        m.run(client(s), store, CFG, today=date(2026, 11, 15))
        self.assertGreater(store.meta["quota"]["used"], used1)
        m.run(client(s), store, CFG, today=date(2026, 11, 16))
        self.assertEqual(store.meta["quota"]["date"], "2026-11-16")


class ApiTests(unittest.TestCase):
    def test_orcamento_lanca(self):
        c = client(FakeSession({"recent": []}, {}), budget=1)
        c.get("/games")
        with self.assertRaises(BudgetExhausted):
            c.get("/games")

    def test_upgrade_required(self):
        c = client(FakeSession({}, {}, blocked_dates=True))
        with self.assertRaises(UpgradeRequired):
            c.get("/games", {"date": "2020-01-01"})


if __name__ == "__main__":
    unittest.main()


class ValidacaoTests(unittest.TestCase):
    def test_placar_inconsistente_nao_entra(self):
        gm = game("gm_x")
        gm["home_score"], gm["away_score"] = 999, 80
        s = FakeSession({"recent": [gm]}, {"gm_x": {"home": [20, 20, 20, 20], "away": [20, 20, 20, 20]}})
        store = MemoryStore()
        m.run(client(s), store, CFG, today=date(2026, 11, 15))
        self.assertFalse(store.games["gm_x"]["hasQuarters"])
        self.assertIsNone(store.get_team("tm_a"))
