"""Modelo estatístico do painel, em Python, para o backtest.

Mantém as mesmas fórmulas de public/js/stats.js. Se mudar uma, mude a outra
(os testes comparam valores de referência nas duas linguagens).
"""
import math

PERIODS = ["q1", "q2", "q3", "q4", "h1", "h2", "reg"]
# Desvio padrão padrão do total dos dois times no período, usado quando ainda não há dados da liga.
DEFAULT_SD = {"q1": 7.5, "q2": 7.5, "q3": 7.5, "q4": 7.5, "h1": 10.5, "h2": 10.5, "reg": 15.0}
HALF_LIFE = 8      # jogos: peso cai pela metade a cada 8 jogos de distância
SHRINK_K = 6       # força do ajuste da dispersão em direção ao padrão da liga


def value(e, key, side):
    p, o = e["pts"], e["oppPts"]
    def base(x):
        return {"q1": x[0], "q2": x[1], "q3": x[2], "q4": x[3], "h1": x[0] + x[1],
                "h2": x[2] + x[3], "reg": sum(x[:4])}[key]
    own, opp = base(p), base(o)
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
