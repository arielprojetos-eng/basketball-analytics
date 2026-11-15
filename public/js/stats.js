// Estatísticas do painel. Funções puras, sem acesso à rede, testáveis em Node.

export const PERIODS = [
  { key: "q1", label: "1º quarto" },
  { key: "q2", label: "2º quarto" },
  { key: "q3", label: "3º quarto" },
  { key: "q4", label: "4º quarto" },
  { key: "h1", label: "1º tempo" },
  { key: "h2", label: "2º tempo" },
  { key: "reg", label: "Tempo regulamentar" },
  { key: "total", label: "Jogo com prorrogação" },
];

const sum = (a) => a.reduce((s, x) => s + x, 0);

function base(p, ot, key) {
  switch (key) {
    case "q1": return p[0];
    case "q2": return p[1];
    case "q3": return p[2];
    case "q4": return p[3];
    case "h1": return p[0] + p[1];
    case "h2": return p[2] + p[3];
    case "reg": return sum(p.slice(0, 4));
    case "total": return sum(p.slice(0, 4)) + (ot || 0);
    default: throw new Error("período inválido: " + key);
  }
}

// side: "for" (marcados), "against" (sofridos) ou "sum" (total dos dois times no período)
export function value(entry, key, side) {
  const own = base(entry.pts, entry.ot, key);
  const opp = base(entry.oppPts, entry.oppOt, key);
  return side === "for" ? own : side === "against" ? opp : own + opp;
}

// Seleciona a amostra: filtra por competição e mando, ordena do mais recente e corta em n.
export function sample(entries, { n = 20, venue = "all", cid = null } = {}) {
  let rows = (entries || []).filter((e) => !cid || e.cid === cid);
  if (venue === "home") rows = rows.filter((e) => e.home);
  if (venue === "away") rows = rows.filter((e) => !e.home);
  rows = [...rows].sort((a, b) => (a.sortKey < b.sortKey ? 1 : -1));
  return rows.slice(0, n);
}

export const mean = (v) => (v.length ? sum(v) / v.length : null);

// Desvio padrão amostral (n-1). Com menos de 2 jogos não há dispersão calculável.
export function std(v) {
  if (v.length < 2) return null;
  const m = mean(v);
  return Math.sqrt(sum(v.map((x) => (x - m) ** 2)) / (v.length - 1));
}

// Percentual de jogos estritamente acima da linha. Linhas com .5 nunca empatam.
export function overPct(v, line) {
  if (!v.length) return null;
  return (v.filter((x) => x > line).length / v.length) * 100;
}

export function summarize(rows, key) {
  const f = rows.map((e) => value(e, key, "for"));
  const a = rows.map((e) => value(e, key, "against"));
  const t = rows.map((e) => value(e, key, "sum"));
  return {
    n: rows.length,
    forAvg: mean(f), againstAvg: mean(a), totalAvg: mean(t),
    totalStd: std(t), forStd: std(f),
    totalMin: t.length ? Math.min(...t) : null,
    totalMax: t.length ? Math.max(...t) : null,
    forSeries: f, againstSeries: a, totalSeries: t,
  };
}

// Linhas de meio ponto em torno da média combinada das duas equipes.
export function lineGrid(center, span = 3) {
  if (center == null) return [];
  const mid = Math.floor(center) + 0.5;
  return Array.from({ length: span * 2 + 1 }, (_, i) => mid - span + i);
}

// Duas projeções do total combinado:
//  somaOfensiva: média marcada de A + média marcada de B.
//  cruzada: média entre (ataque de A + defesa de B) e (ataque de B + defesa de A), por equipe.
export function projections(a, b) {
  if (!a.n || !b.n) return { somaOfensiva: null, cruzada: null, pontosA: null, pontosB: null };
  const pontosA = (a.forAvg + b.againstAvg) / 2;
  const pontosB = (b.forAvg + a.againstAvg) / 2;
  return { somaOfensiva: a.forAvg + b.forAvg, cruzada: pontosA + pontosB, pontosA, pontosB };
}

// ---------- Projeção ao vivo ----------

// Função de distribuição acumulada da normal padrão (aproximação de Abramowitz e Stegun).
export function normCdf(z) {
  const t = 1 / (1 + 0.2316419 * Math.abs(z));
  const d = 0.3989423 * Math.exp((-z * z) / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return z > 0 ? 1 - p : p;
}

// Peso dado ao ritmo observado no jogo, conforme quantos quartos já foram jogados.
// A correlação entre o ritmo de um quarto e o dos seguintes é fraca, por isso o peso é baixo (ver README).
export const LIVE_WEIGHT = { 1: 0.2, 2: 0.3, 3: 0.4 };

// played: [{a, b}] com os quartos já encerrados, em ordem (1 a 3 quartos).
// Devolve null se faltar amostra em algum quarto necessário.
export function liveProjection(rowsA, rowsB, played) {
  const k = played.length;
  if (k < 1 || k > 3 || !rowsA.length || !rowsB.length) return null;
  const keys = ["q1", "q2", "q3", "q4"];
  const per = keys.map((key) => {
    const A = summarize(rowsA, key), B = summarize(rowsB, key);
    const pa = (A.forAvg + B.againstAvg) / 2;
    const pb = (B.forAvg + A.againstAvg) / 2;
    const sdA = A.totalStd, sdB = B.totalStd;
    const sd = sdA == null || sdB == null ? null : Math.sqrt((sdA * sdA + sdB * sdB) / 2);
    return { pa, pb, total: pa + pb, sd };
  });
  if (per.some((q) => q.sd == null)) return null;

  const observed = played.reduce((s, q) => s + q.a + q.b, 0);
  const expected = per.slice(0, k).reduce((s, q) => s + q.total, 0);
  const pace = observed / expected;
  const w = LIVE_WEIGHT[k];
  const mult = 1 + w * (pace - 1);

  const rest = per.slice(k).map((q, i) => ({
    quarter: k + i + 1, a: q.pa * mult, b: q.pb * mult, total: q.total * mult, sd: q.sd,
  }));
  const playedA = played.reduce((s, q) => s + q.a, 0);
  const playedB = played.reduce((s, q) => s + q.b, 0);
  const remTotal = rest.reduce((s, q) => s + q.total, 0);
  const sdRest = Math.sqrt(rest.reduce((s, q) => s + q.sd * q.sd, 0));
  return {
    pace, mult, weight: w, observed, expected, rest,
    finalA: playedA + rest.reduce((s, q) => s + q.a, 0),
    finalB: playedB + rest.reduce((s, q) => s + q.b, 0),
    finalTotal: observed + remTotal,
    sdFinal: sdRest,           // incerteza só dos quartos restantes
    playedTotal: observed,
    nextQuarter: rest[0],
  };
}

// Probabilidade de o total superar a linha, com aproximação normal.
export function probOver(mean, sd, line) {
  if (!sd) return null;
  return (1 - normCdf((line - mean) / sd)) * 100;
}
