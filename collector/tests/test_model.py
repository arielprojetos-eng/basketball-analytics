import unittest

from collector import backtest as bt
from collector import model as M
from collector.main import scores_match
from collector.store import MemoryStore


def e(n, pts, opp, cid="c1", home=True, opp_id="B"):
    return {"gid": f"g{n}", "sortKey": f"2026-10-{n:02d}|g{n}", "cid": cid, "cname": "Liga", "home": home,
            "oppId": opp_id, "pts": pts, "oppPts": opp, "ot": 0, "oppOt": 0}


class ModelTests(unittest.TestCase):
    def test_valores_de_referencia_iguais_ao_js(self):
        # mesmos números do teste "projeções" em tests/stats.test.mjs
        A = {"n": 20, "for": 45, "against": 43, "sd": None}
        B = {"n": 20, "for": 47, "against": 44, "sd": None}
        self.assertEqual(M.cross(A, B), 89.5)
        self.assertAlmostEqual(M.prob_over(100, 10, 100), 0.5)
        self.assertEqual(M.central_line(46.2), 46.5)

    def test_recencia(self):
        self.assertEqual(M.wmean([10, 0], False), 5)
        w1 = 0.5 ** (1 / M.HALF_LIFE)
        self.assertAlmostEqual(M.wmean([10, 0], True), 10 / (1 + w1))
        self.assertGreater(M.wmean([10, 0], True), 5)  # o jogo mais recente pesa mais

    def test_dispersao_ajustada(self):
        prior = 7.5
        few = {"n": 2, "sd": 1.0}
        many = {"n": 60, "sd": 1.0}
        self.assertGreater(M.shrunk_sd(few, few, prior), M.shrunk_sd(many, many, prior))
        self.assertEqual(M.shrunk_sd({"n": 1, "sd": None}, {"n": 1, "sd": None}, prior), prior)

    def test_validacao_placar(self):
        self.assertTrue(scores_match(([20, 20, 20, 20], [18, 18, 18, 18]), 80, 72))
        self.assertFalse(scores_match(([20, 20, 20, 20], [18, 18, 18, 18]), 81, 72))
        self.assertFalse(scores_match(([20, 20, 20, 95], [18, 18, 18, 18]), None, None))
        self.assertTrue(scores_match(([20, 20, 20, 20, 5], [18, 18, 18, 26, 3]), 85, 83))


class BacktestTests(unittest.TestCase):
    def teams(self, k=8):
        A, B = [], []
        for i in range(1, k + 1):
            pa = [20 + (i % 3), 22, 21, 19]
            pb = [18, 20 + (i % 2), 22, 20]
            A.append(e(i, pa, pb, home=True, opp_id="B"))
            B.append({**e(i, pb, pa, home=False, opp_id="A")})
        return {"A": {"games": A}, "B": {"games": B}}

    def test_sem_vazamento_e_minimo(self):
        t = self.teams(8)
        pri = bt.compute_priors(bt.collect_games(t))
        res = bt.run_backtest(t, pri)
        # só jogos com 3 anteriores de cada lado: jogos 4..8
        self.assertEqual(res["games"], 5)
        self.assertEqual(res["periods"]["q1"]["n"], 5)
        self.assertIn("brierModel", res["periods"]["q3"])
        self.assertEqual(sum(c["n"] for c in res["calibration"]), 5 * len(M.PERIODS) * len(bt.LINE_OFFSETS))

    def test_projecao_usa_so_jogos_anteriores(self):
        t = self.teams(4)
        rows = bt.prior_rows(t["A"], "c1", "2026-10-04|g4")
        self.assertEqual([r["gid"] for r in rows], ["g3", "g2", "g1"])

    def test_run_uma_vez_por_dia(self):
        st = MemoryStore()
        for tid, d in self.teams(6).items():
            st.put_team(tid, d)
        self.assertIsNotNone(bt.run(st, "2026-11-15"))
        self.assertIsNone(bt.run(st, "2026-11-15"))
        self.assertIn("global", st.meta["priors"])
        self.assertEqual(st.meta["backtest"]["date"], "2026-11-15")


if __name__ == "__main__":
    unittest.main()
