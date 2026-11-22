"""Modelo estatístico do painel, em Python, para o backtest.

Mantém as mesmas fórmulas de public/js/stats.js. Se mudar uma, mude a outra
(os testes comparam valores de referência nas duas linguagens).
"""
import math

PERIODS = ["q1", "q2", "q3", "q4", "h1", "h2", "reg"]
# Períodos do modelo v2: os mesmos mais o jogo com prorrogação ("total").
V2_PERIODS = PERIODS + ["total"]
# Desvio padrão padrão do total dos dois times no período, usado quando ainda não há dados da liga.
DEFAULT_SD = {"q1": 7.5, "q2": 7.5, "q3": 7.5, "q4": 7.5, "h1": 10.5, "h2": 10.5, "reg": 15.0, "total": 15.5}
HALF_LIFE = 8      # jogos: peso cai pela metade a cada 8 jogos de distância
SHRINK_K = 6       # força do ajuste da dispersão em direção ao padrão da liga


QUARTER_KEYS = ("q1", "q2", "q3", "q4")


def shape(e):
    """Formato do placar: "quarters", "halves" ou "invalid".

    - "halves": algumas ligas (ex.: NCAA masculina na API-Sports) chegam com o 1º tempo no "2º quarto"
      e o 2º tempo no "4º quarto", com Q1 = Q3 = 0 para os dois lados. Tempos e jogo seguem corretos;
      os quartos não existem.
    - "invalid": algum outro quarto com 0 x 0 (jogo zerado ou truncado, ex.: [27, 31, 28, 0]).
      Um quarto real sem ponto dos dois times não ocorre na prática.
    """
    p, o = e.get("pts") or [], e.get("oppPts") or []
    if len(p) < 4 or len(o) < 4:
        return "invalid"
    dead = [p[i] == 0 and o[i] == 0 for i in range(4)]
    if not any(dead):
        return "quarters"
    if dead == [True, False, True, False]:
        return "halves"
    return "invalid"


def quarters_valid(e):
    return shape(e) == "quarters"


def usable(e, key):
    """O jogo pode entrar no cálculo deste período?"""
    s = shape(e)
    return s == "quarters" or (s == "halves" and key not in QUARTER_KEYS)


def value(e, key, side):
    p, o = e["pts"], e["oppPts"]
    def base(x, ot):
        if key == "total":
            return sum(x[:4]) + (ot or 0)
        return {"q1": x[0], "q2": x[1], "q3": x[2], "q4": x[3], "h1": x[0] + x[1],
                "h2": x[2] + x[3], "reg": sum(x[:4])}[key]
    own, opp = base(p, e.get("ot")), base(o, e.get("oppOt"))
    return own if side == "for" else opp if side == "against" else own + opp


def weights(n, recency):
    return [0.5 ** (i / HALF_LIFE) if recency else 1.0 for i in range(n)]


def wmean(vals, recency):
    """vals do mais recente para o mais antigo."""
    if not vals:
        return None
    w = weights(len(vals), recency)
    return sum(v * x for v, x in zip(vals, w)) / sum(w)


def sd(vals):
    if len(vals) < 2:
        return None
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def summarize(rows, key, recency=False):
    f = [value(e, key, "for") for e in rows]
    a = [value(e, key, "against") for e in rows]
    t = [value(e, key, "sum") for e in rows]
    return {"n": len(rows), "for": wmean(f, recency), "against": wmean(a, recency),
            "total": wmean(t, recency), "sd": sd(t), "totals": t}


def cross(A, B):
    if not A["n"] or not B["n"]:
        return None
    return (A["for"] + B["against"]) / 2 + (B["for"] + A["against"]) / 2


def shrunk_sd(A, B, prior):
    """Dispersão do total combinada das duas equipes, puxada para o padrão da liga quando há poucos jogos."""
    sds = [x["sd"] for x in (A, B) if x["sd"] is not None]
    if not sds:
        return prior
    pooled2 = sum(s * s for s in sds) / len(sds)
    dof = sum(max(x["n"] - 1, 0) for x in (A, B) if x["sd"] is not None)
    return math.sqrt((dof * pooled2 + SHRINK_K * prior * prior) / (dof + SHRINK_K))


def norm_cdf(z):
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def prob_over(mean, s, line):
    if not s:
        return None
    return 1 - norm_cdf((line - mean) / s)


def central_line(mean):
    return math.floor(mean) + 0.5


def freq_over(totals, line):
    if not totals:
        return None
    return sum(1 for t in totals if t > line) / len(totals)


# =====================================================================================
# Modelo v2 (liga + equipe com encolhimento). O modelo original acima continua intacto
# e é avaliado lado a lado no backtest, como referência e para reversão.
#
# Ideia: com no máximo poucos jogos por equipe, a média própria de uma equipe é muito
# ruidosa. O v2 parte da média da liga no período e soma o desvio de cada equipe só na
# proporção da evidência: n / (n + K). Para o TOTAL do período, a projeção cruzada original
# é algebricamente igual à média dos totais das duas equipes; o v2 mantém essa estrutura,
# mas ancorada na liga. A dispersão vem da liga (não da equipe) e inclui a incerteza das
# próprias médias estimadas.
# =====================================================================================

# Médias de partida, usadas só antes de existir qualquer jogo armazenado (início absoluto da coleta).
DEFAULT_MEAN = {"q1": 40.0, "q2": 40.0, "q3": 40.0, "q4": 40.0, "h1": 80.0, "h2": 80.0, "reg": 160.0, "total": 161.0}


def is_women(cname):
    """Liga feminina pelo nome (as APIs não informam o gênero)."""
    low = f" {(cname or '').lower()} "
    return any(t in low for t in ("women", " w ", " w(", "wcba", "wkbl", "wnba", "femenin", "feminin"))


# Escolhidos no backtest walk-forward (período de ajuste 15 a 18/11/2026) e conferidos fora da
# amostra (19 a 22/11/2026). Ver relatorio/03_backtest.md. Não mude sem rodar o backtest de novo.
V2 = {
    "k_team": 4.0,   # jogos "virtuais" da liga somados à amostra da equipe
    "k_comp": 3.0,   # jogos "virtuais" da referência global (por gênero) somados à liga
    "k_sd": 40.0,    # graus de liberdade virtuais da dispersão agrupada dentro das ligas
}
SD_SCALE_K = 100   # encolhimento da escala de dispersão aprendida no backtest em direção a 1


def league_mean(L, k_comp):
    """Média do período na liga, encolhida para a média global do mesmo gênero."""
    n = L.get("n") or 0
    m = L.get("mean") if n else 0.0
    return (n * m + k_comp * L["gmean"]) / (n + k_comp)


def league_sd(L, k_sd):
    """Desvio do total dentro da liga, encolhido para o desvio agrupado de todas as ligas."""
    n = L.get("n") or 0
    dof = max(n - 1, 0)
    var = (L.get("sd") or 0.0) ** 2
    pooled = L["pooled"]
    return math.sqrt((dof * var + k_sd * pooled * pooled) / (dof + k_sd))


def team_totals(rows, key):
    """Totais do período nos jogos da amostra que valem para esse período (do mais recente ao mais antigo)."""
    return [value(e, key, "sum") for e in rows if usable(e, key)]


def sd_scale(n, sum_z2):
    """Fator que corrige a dispersão pelo que o backtest observou: raiz da média dos z², encolhida para 1."""
    return math.sqrt((sum_z2 + SD_SCALE_K) / (n + SD_SCALE_K))


def project_v2(rows_a, rows_b, key, L, params=None, recency=False):
    """Projeção do total do período e sua dispersão preditiva.

    L: {"n", "mean", "sd", "gmean", "pooled"} da liga no período (sem olhar o futuro, no backtest).
    """
    p = {**V2, **(params or {})}
    lm = league_mean(L, p["k_comp"])
    s = league_sd(L, p["k_sd"])
    ta, tb = team_totals(rows_a, key), team_totals(rows_b, key)
    na, nb = len(ta), len(tb)
    kt = p["k_team"]
    da = (wmean(ta, recency) - lm) if na else 0.0
    db = (wmean(tb, recency) - lm) if nb else 0.0
    sa, sb = na / (na + kt), nb / (nb + kt)
    mean = lm + 0.5 * (sa * da + sb * db)
    nl = L.get("n") or 0
    var = s * s * (1 + 1 / (nl + p["k_comp"]) + 0.25 * (1 / (na + kt) + 1 / (nb + kt)))
    sd = math.sqrt(var) * (L.get("scale") or 1.0)
    return {"mean": mean, "sd": sd, "league": lm, "leagueSd": s, "nA": na, "nB": nb,
            "shrinkA": sa, "shrinkB": sb}


# ---------------- Ao vivo (v2) ----------------
# Peso do ritmo observado, escolhido no backtest (era 20/30/40%, sem calibração).
LIVE_WEIGHT_V2 = {1: 0.1, 2: 0.2, 3: 0.3}


def split_points(rows_a, rows_b, key, lm, params=None):
    """Divide a projeção do total entre os dois times (ataque de um contra a defesa do outro, encolhidos)."""
    p = {**V2, **(params or {})}
    kt = p["k_team"]
    fa = [value(e, key, "for") for e in rows_a if usable(e, key)]
    aa = [value(e, key, "against") for e in rows_a if usable(e, key)]
    fb = [value(e, key, "for") for e in rows_b if usable(e, key)]
    ab = [value(e, key, "against") for e in rows_b if usable(e, key)]
    na, nb = len(fa), len(fb)
    half = lm / 2
    off_a = sum(fa) / na - half if na else 0.0
    def_a = sum(aa) / na - half if na else 0.0
    off_b = sum(fb) / nb - half if nb else 0.0
    def_b = sum(ab) / nb - half if nb else 0.0
    sa, sb = na / (na + kt), nb / (nb + kt)
    return half + 0.5 * (sa * off_a + sb * def_b), half + 0.5 * (sb * off_b + sa * def_a)


def live_v2(quarters, played, margin_sd=None, weight=None):
    """Projeção ao vivo a partir das projeções pré-jogo de cada quarto.

    quarters: 4 dicionários {"a", "b", "sd"} (pontos esperados de cada time e dispersão do total do quarto).
    played: lista de (pontos A, pontos B) dos quartos encerrados, em ordem (1 a 3).
    margin_sd: dispersão do saldo de um quarto (para a chance de vitória). Padrão: igual à do total.
    weight: peso do ritmo, para ligas em tempos (2 períodos); padrão: LIVE_WEIGHT_V2 pelo nº de quartos.
    """
    k = len(played)
    if not 1 <= k <= len(quarters) - 1:
        return None
    obs = sum(a + b for a, b in played)
    exp = sum(q["a"] + q["b"] for q in quarters[:k])
    pace = obs / exp if exp else 1.0
    w = weight if weight is not None else LIVE_WEIGHT_V2[k]
    mult = 1 + w * (pace - 1)
    rest = [{"a": q["a"] * mult, "b": q["b"] * mult, "total": (q["a"] + q["b"]) * mult, "sd": q["sd"]}
            for q in quarters[k:]]
    pa, pb = sum(a for a, _ in played), sum(b for _, b in played)
    ra, rb = sum(q["a"] for q in rest), sum(q["b"] for q in rest)
    sd_rest = math.sqrt(sum(q["sd"] ** 2 for q in rest))
    msd = math.sqrt(sum((margin_sd if margin_sd else q["sd"]) ** 2 for q in rest))
    margin = (pa + ra) - (pb + rb)
    return {"pace": pace, "mult": mult, "weight": w, "rest": rest, "restTotal": ra + rb, "sdRest": sd_rest,
            "finalA": pa + ra, "finalB": pb + rb, "finalTotal": obs + ra + rb, "margin": margin,
            "winA": norm_cdf(margin / msd) if msd else None}
