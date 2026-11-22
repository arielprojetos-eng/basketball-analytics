import unittest
from collections import defaultdict

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
        res = bt.run_backtest(t)
        # só jogos com 3 anteriores de cada lado: jogos 4..8
        self.assertEqual(res["games"], 5)
        self.assertEqual(res["periods"]["q1"]["n"], 5)
        self.assertIn("brierModel", res["periods"]["q3"])
        self.assertEqual(sum(c["n"] for c in res["calibration"]), 5 * len(M.PERIODS) * len(bt.LINE_OFFSETS))

    def test_jogos_futuros_nao_mudam_avaliacao_passada(self):
        """A avaliação de cada jogo tem de ser idêntica com ou sem os jogos que vieram depois."""
        def league(k, wild_after=None):
            teams = {}
            names = [f"T{i}" for i in range(6)]
            for t in names:
                teams[t] = {"games": []}
            n = 0
            for day in range(1, k + 1):
                for x in range(0, 6, 2):
                    h, a = names[(x + day) % 6], names[(x + day + 1) % 6]
                    n += 1
                    base = 20 + (n * 7) % 9
                    if wild_after and day > wild_after:
                        base = 5 + (n * 37) % 60  # futuro com dispersão enorme
                    ph, pa = [base, base + 1, base - 1, base], [base - 2, base, base + 2, base - 1]
                    sk = f"2026-10-{day:02d}T20:00:00Z|g{n}"
                    teams[h]["games"].append({"gid": f"g{n}", "sortKey": sk, "cid": "c1", "cname": "L", "home": True,
                                              "oppId": a, "pts": ph, "oppPts": pa, "ot": 0, "oppOt": 0})
                    teams[a]["games"].append({"gid": f"g{n}", "sortKey": sk, "cid": "c1", "cname": "L", "home": False,
                                              "oppId": h, "pts": pa, "oppPts": ph, "ot": 0, "oppOt": 0})
            return teams

        full, cut = [], []
        bt.run_backtest(league(28, wild_after=20), trace=full)
        bt.run_backtest(league(20), trace=cut)
        self.assertTrue(cut)
        self.assertEqual(full[:len(cut)], cut)

    def test_prior_comeca_no_padrao_e_ignora_jogos_simultaneos(self):
        trace = []
        bt.run_backtest(self.teams(8), trace=trace)
        first = [x for x in trace if x[0] == trace[0][0]]
        for gid, k, prior, _, _ in first:
            self.assertEqual(prior, M.DEFAULT_SD[k])  # sem jogos anteriores suficientes na liga

        # dois jogos no mesmo horário: o segundo não pode usar o primeiro na dispersão
        st = defaultdict(lambda: defaultdict(bt.Running)); gl = defaultdict(bt.Running)
        self.assertEqual(bt.walk_forward_prior(st, gl, "c1", "q1"), M.DEFAULT_SD["q1"])

    def test_veredito_de_calibracao(self):
        few = [{"n": 10, "p": 0.5, "freq": 0.5}]
        self.assertEqual(bt.calibration_verdict(few)[2], "amostra insuficiente")
        good = [{"n": 300, "p": 0.3, "freq": 0.31}, {"n": 300, "p": 0.7, "freq": 0.69}]
        self.assertEqual(bt.calibration_verdict(good)[2], "calibrado")
        bad = [{"n": 300, "p": 0.3, "freq": 0.45}, {"n": 300, "p": 0.7, "freq": 0.55}]
        cases, ece, status = bt.calibration_verdict(bad)
        self.assertEqual((cases, status), (600, "descalibrado"))
        self.assertAlmostEqual(ece, 0.15)
        self.assertEqual(bt.calibration_verdict([])[2], "sem dados")

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


# ---------------------------------------------------------------- modelo v2
# Mesmos números em tests/stats.test.mjs ("v2: valores de referência iguais ao Python").
RA = [{"pts": [22, 20, 25, 21], "oppPts": [20, 19, 22, 24], "ot": 0, "oppOt": 0, "home": True},
      {"pts": [18, 24, 20, 19], "oppPts": [21, 22, 18, 20], "ot": 0, "oppOt": 0, "home": False},
      {"pts": [25, 23, 21, 26], "oppPts": [24, 20, 23, 22], "ot": 6, "oppOt": 4, "home": True}]
RB = [{"pts": [19, 21, 18, 20], "oppPts": [17, 22, 19, 21], "ot": 0, "oppOt": 0, "home": False},
      {"pts": [0, 38, 0, 41], "oppPts": [0, 35, 0, 37], "ot": 0, "oppOt": 0, "home": True}]  # jogo em tempos
LQ = {"n": 12, "mean": 42.5, "sd": 8.2, "gmean": 40.0, "pooled": 7.8, "scale": 0.95}
LR = {"n": 12, "mean": 170.0, "sd": 16.0, "gmean": 160.0, "pooled": 15.0, "scale": 0.93}


class FormatoTests(unittest.TestCase):
    def test_formatos_de_placar(self):
        self.assertEqual(M.shape({"pts": [20, 21, 22, 23], "oppPts": [19, 0, 18, 20]}), "quarters")  # 0 de um lado é real
        self.assertEqual(M.shape({"pts": [0, 45, 0, 63], "oppPts": [0, 40, 0, 46]}), "halves")
        self.assertEqual(M.shape({"pts": [0, 0, 0, 0], "oppPts": [0, 0, 0, 0]}), "invalid")
        self.assertEqual(M.shape({"pts": [27, 31, 28, 0], "oppPts": [27, 24, 27, 0]}), "invalid")
        self.assertEqual(M.shape({"pts": [11, 28, 0, 0], "oppPts": [21, 14, 0, 0]}), "invalid")
        halves = {"pts": [0, 45, 0, 63], "oppPts": [0, 40, 0, 46]}
        self.assertFalse(M.usable(halves, "q1"))
        self.assertTrue(M.usable(halves, "h1"))
        self.assertTrue(M.usable(halves, "reg"))

    def test_coletor_recusa_jogo_zerado_ou_truncado(self):
        self.assertFalse(scores_match(([0, 0, 0, 0], [0, 0, 0, 0]), 0, 0))
        self.assertFalse(scores_match(([27, 31, 28, 0], [27, 24, 27, 0]), 86, 78))
        self.assertTrue(scores_match(([0, 45, 0, 63], [0, 40, 0, 46]), 108, 86))  # tempos: guarda tempos e jogo

    def test_genero_pelo_nome(self):
        self.assertTrue(M.is_women("NCAA Women (USA)"))
        self.assertTrue(M.is_women("WKBL W (South Korea)"))
        self.assertTrue(M.is_women("Liga Femenina Women (Argentina)"))
        self.assertFalse(M.is_women("NBA (USA)"))
        self.assertFalse(M.is_women("Basketligan (Sweden)"))

    def test_total_com_prorrogacao(self):
        self.assertEqual(M.value(RA[2], "total", "for"), 95 + 6)
        self.assertEqual(M.value(RA[2], "total", "sum"), 95 + 6 + 89 + 4)


class V2Tests(unittest.TestCase):
    def test_valores_de_referencia_iguais_ao_js(self):
        p = M.project_v2(RA, RB, "q2", LQ)
        self.assertAlmostEqual(p["mean"], 42.24285714285714, places=9)
        self.assertAlmostEqual(p["sd"], 8.044295449636701, places=9)
        self.assertEqual((p["nA"], p["nB"]), (3, 1))  # o jogo em tempos não entra no quarto
        r = M.project_v2(RA, RB, "reg", LR)
        self.assertAlmostEqual(r["mean"], 166.73809523809524, places=9)
        self.assertAlmostEqual(r["sd"], 15.141020674275017, places=9)
        self.assertEqual((r["nA"], r["nB"]), (3, 2))  # mas entra no jogo
        a, b = M.split_points(RA, RB, "reg", r["league"])
        self.assertAlmostEqual(a + b, r["mean"], places=9)

    def test_sem_amostra_vale_a_liga_e_muita_amostra_vale_a_equipe(self):
        p = M.project_v2([], [], "q1", LQ)
        self.assertAlmostEqual(p["mean"], M.league_mean(LQ, M.V2["k_comp"]))
        lm = p["mean"]
        hot = [{"pts": [30, 20, 20, 20], "oppPts": [30, 20, 20, 20]} for _ in range(400)]  # q1 = 60
        q = M.project_v2(hot, hot, "q1", LQ)
        self.assertGreater(q["mean"], lm + 0.97 * (60 - lm))
        few = M.project_v2(hot[:1], hot[:1], "q1", LQ)
        self.assertLess(few["mean"], lm + 0.25 * (60 - lm))  # 1 jogo move pouco
        self.assertGreater(p["sd"], q["sd"])  # menos amostra, mais incerteza

    def test_liga_nova_usa_referencia_do_genero(self):
        L = {"n": 0, "mean": None, "sd": None, "gmean": 33.0, "pooled": 7.8}
        self.assertEqual(M.league_mean(L, 3), 33.0)
        self.assertEqual(M.league_sd(L, 40), 7.8)

    def test_ao_vivo_intervalo_50_40(self):
        qs = [{"a": 21.0, "b": 19.5, "sd": 7.6}, {"a": 20.5, "b": 20.0, "sd": 7.4},
              {"a": 21.2, "b": 19.8, "sd": 7.7}, {"a": 20.4, "b": 20.6, "sd": 8.0}]
        r = M.live_v2(qs, [(27, 23), (23, 17)], margin_sd=9.0)
        self.assertEqual(r["weight"], 0.2)
        self.assertAlmostEqual(r["finalTotal"], 173.82222222222222, places=9)
        self.assertAlmostEqual(r["restTotal"], 83.82222222222222, places=9)
        self.assertAlmostEqual(r["sdRest"], 11.103603018840326, places=9)
        self.assertAlmostEqual(r["winA"], 0.81112517941598, places=6)
        self.assertAlmostEqual(r["finalA"] - r["finalB"], r["margin"], places=9)
        self.assertIsNone(M.live_v2(qs, []))
        self.assertIsNone(M.live_v2(qs, [(1, 1)] * 4))


def _league_games(k, wild_after=None, dup_after=None, invalid_on=None):
    names = [f"T{i}" for i in range(6)]
    teams = {t: {"games": []} for t in names}
    n = 0
    for day in range(1, k + 1):
        for x in range(0, 6, 2):
            h, a = names[(x + day) % 6], names[(x + day + 1) % 6]
            n += 1
            base = 20 + (n * 7) % 9
            if wild_after and day > wild_after:
                base = 5 + (n * 37) % 60
            ph, pa = [base, base + 1, base - 1, base], [base - 2, base, base + 2, base - 1]
            if invalid_on == n:
                ph, pa = [base, base, base, 0], [base, base, base, 0]
            sk = f"2026-10-{day:02d}T20:00:00Z|as_g{n}"
            teams[h]["games"].append({"gid": f"as_g{n}", "sortKey": sk, "date": f"2026-10-{day:02d}", "cid": "c1",
                                      "cname": "L", "home": True, "oppId": a, "pts": ph, "oppPts": pa, "ot": 0, "oppOt": 0})
            teams[a]["games"].append({"gid": f"as_g{n}", "sortKey": sk, "date": f"2026-10-{day:02d}", "cid": "c1",
                                      "cname": "L", "home": False, "oppId": h, "pts": pa, "oppPts": ph, "ot": 0, "oppOt": 0})
    return teams


class BacktestV2Tests(unittest.TestCase):
    def test_jogos_futuros_nao_mudam_avaliacao_passada(self):
        full, cut = [], []
        bt.run_backtest_v2(_league_games(28, wild_after=20), trace=full)
        bt.run_backtest_v2(_league_games(20), trace=cut)
        self.assertTrue(cut)
        self.assertEqual(full[:len(cut)], cut)

    def test_primeiro_dia_nao_e_avaliado(self):
        trace = []
        bt.run_backtest_v2(_league_games(3), trace=trace)
        self.assertNotIn("as_g1", {t[0] for t in trace})
        self.assertIn("as_g4", {t[0] for t in trace})

    def test_jogo_invalido_fica_fora(self):
        trace = []
        bt.run_backtest_v2(_league_games(6, invalid_on=8), trace=trace)
        self.assertNotIn("as_g8", {t[0] for t in trace})

    def test_duplicata_entre_fontes_avaliada_uma_vez(self):
        teams = _league_games(6)
        # cópia do jogo as_g10 gravada pela outra fonte, com outros IDs de equipe
        src = next(e for t in teams.values() for e in t["games"] if e["gid"] == "as_g10" and e["home"])
        cp = {**src, "gid": "x10", "sortKey": src["sortKey"].replace("as_g10", "x10"), "oppId": "Y"}
        teams["X"] = {"games": [dict(cp, home=True)]}
        teams["Y"] = {"games": [dict(cp, home=False, oppId="X", pts=src["oppPts"], oppPts=src["pts"])]}
        trace = []
        res, _ = bt.run_backtest_v2(teams, trace=trace)
        self.assertEqual(res["duplicatesSkipped"], 1)
        self.assertNotIn("x10", {t[0] for t in trace})

    def test_veredito_conta_jogos_e_nao_casos(self):
        res, _ = bt.run_backtest_v2(_league_games(10))
        self.assertGreater(res["calibrationCases"], res["calibrationGames"])
        self.assertEqual(res["calibrationStatus"], "amostra insuficiente")  # 27 jogos < 300

    def test_run_grava_v2_e_referencia(self):
        st = MemoryStore()
        for tid, d in _league_games(8).items():
            st.put_team(tid, d)
        bt.run(st, "2026-11-15")
        self.assertEqual(st.meta["backtest"]["model"], "v2")
        self.assertIn("reference", st.meta["backtest"])
        self.assertIn("v2", st.meta["priors"])
        self.assertIn("global", st.meta["priors"])   # campos antigos preservados
        self.assertIn("q1", st.meta["priors"]["v2"]["sdScale"])
        self.assertIn("total", st.meta["priors"]["v2"]["pooled"])


if __name__ == "__main__":
    unittest.main()
