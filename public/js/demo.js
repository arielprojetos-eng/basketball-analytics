// Dados FICTÍCIOS apenas para pré-visualizar o painel (?demo). Nada aqui vem de API.
function rng(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}

const COMPS = [
  { id: "cp_demo1", name: "Liga Demo A", teams: ["Atlas", "Bravos", "Cometas", "Dragões", "Estrelas", "Falcões", "Gigantes", "Heróis"] },
  { id: "cp_demo2", name: "Copa Demo B", teams: ["Ícaros", "Jaguares", "Kodiaks", "Lobos", "Mares", "Nortes"] },
];

const teams = new Map();
const index = { competitions: {}, updatedAt: "2026-11-15T09:00:00+00:00" };

COMPS.forEach((c, ci) => {
  index.competitions[c.id] = { name: c.name, src: ci ? "basketballapi" : "apisports", teams: {} };
  c.teams.forEach((name, ti) => {
    const id = `tm_demo${ci}_${ti}`;
    const r = rng(1000 * (ci + 1) + ti * 37 + 11);
    const strength = 20 + r() * 6;
    const games = [];
    const n = ti === c.teams.length - 1 ? 7 : 26;
    for (let g = 0; g < n; g++) {
      const home = g % 2 === 0;
      const q = () => Math.round(strength + (r() - 0.5) * 14);
      const day = String(28 - g).padStart(2, "0");
      const opp = c.teams[(ti + 1 + (g % (c.teams.length - 1))) % c.teams.length];
      const pts = [q(), q(), q(), q()];
      const oppPts = [q(), q(), q(), q()];
      const tie = pts.reduce((a, b) => a + b) === oppPts.reduce((a, b) => a + b);
      games.push({
        gid: `gm_demo${ci}_${ti}_${g}`, date: `2026-10-${day}`, sortKey: `2026-10-${day}|${g}`,
        cid: c.id, cname: c.name, home, oppId: "x", oppName: opp,
        pts, oppPts, ot: tie ? 5 : 0, oppOt: tie ? 4 : 0,
      });
    }
    teams.set(id, { id, name, games, n });
    index.competitions[c.id].teams[id] = { name, n };
  });
});

function demoAgenda() {
  const now = new Date(); now.setMinutes(0, 0, 0);
  const base = Math.floor(now.getTime() / 1000);
  const games = [];
  let k = 0;
  const st = ["FT", "Q3", "NS", "NS", "HT", "NS", "FT", "NS"];
  COMPS.forEach((c, ci) => {
    for (let i = 0; i + 1 < c.teams.length; i += 2) {
      const s = st[k % st.length];
      const off = s === "FT" ? -3 : s === "NS" ? 1 + (k % 4) : 0;
      const r = rng(500 + k);
      const q = () => 18 + Math.round(r() * 10);
      // quartos parciais: Q3 em andamento (2 encerrados + parcial), intervalo, encerrado
      const n = s === "FT" ? 4 : s === "Q3" ? 3 : s === "HT" ? 2 : 0;
      const hq = [0, 1, 2, 3].map((i) => (i < n ? q() : null));
      const aq = [0, 1, 2, 3].map((i) => (i < n ? q() : null));
      if (s === "Q3") { hq[2] = 9; aq[2] = 7; }
      const sum = (a) => a.reduce((t, x) => t + (x || 0), 0);
      games.push({ id: `gm_ag_${k}`, t: base + off * 3600, st: s, lg: c.id, ln: c.name, tier: ci,
        h: `tm_demo${ci}_${i}`, hn: c.teams[i], a: `tm_demo${ci}_${i + 1}`, an: c.teams[i + 1],
        hs: s === "NS" ? null : sum(hq), as: s === "NS" ? null : sum(aq), ...(n ? { hq, aq } : {}) });
      k++;
    }
  });
  games.push({ id: "gm_ag_novo", t: base + 7200, st: "NS", lg: "cp_demo3", ln: "Liga Demo C", tier: 1,
    h: "tm_x1", hn: "Orcas", a: "tm_x2", an: "Pumas", hs: null, as: null });
  return { updatedAt: new Date().toISOString(), games: games.sort((x, y) => x.t - y.t) };
}

// meta/priors.v2 calculado dos jogos fictícios, no mesmo formato que o backtest grava.
function demoPriors() {
  const keys = { q1: (x) => x[0], q2: (x) => x[1], q3: (x) => x[2], q4: (x) => x[3], h1: (x) => x[0] + x[1],
    h2: (x) => x[2] + x[3], reg: (x) => x[0] + x[1] + x[2] + x[3] };
  const stat = (v) => {
    const m = v.reduce((a, b) => a + b, 0) / v.length;
    return { n: v.length, mean: m, sd: Math.sqrt(v.reduce((a, b) => a + (b - m) ** 2, 0) / (v.length - 1)) };
  };
  const comps = {}, all = {};
  for (const c of COMPS) {
    comps[c.id] = {};
    const games = [...teams.values()].flatMap((t) => t.games.filter((g) => g.cid === c.id));
    for (const [k, f] of Object.entries(keys)) {
      const v = games.map((g) => f(g.pts) + f(g.oppPts));
      const d = games.map((g) => f(g.pts) - f(g.oppPts));
      comps[c.id][k] = { ...stat(v), home: 1, msd: stat(d).sd };
      (all[k] ||= []).push(...v);
    }
  }
  comps[COMPS[0].id].total = comps[COMPS[0].id].reg;
  const g = Object.fromEntries(Object.entries(all).map(([k, v]) => [k, stat(v).mean]));
  const pooled = Object.fromEntries(Object.entries(all).map(([k, v]) => [k, stat(v).sd]));
  return { v2: { comps, gmean: { m: g, w: g }, pooled, msd: pooled, sdScale: { q1: 0.95, q2: 0.95, q3: 0.94, q4: 0.96, h1: 0.92, h2: 0.93, reg: 0.93 } } };
}

export const demoMeta = (name) => {
  if (name === "agenda") { const a = demoAgenda(); a.liveAt = a.updatedAt; return a; }
  if (name === "priors") return demoPriors();
  if (name === "status_live") return { lastRun: new Date().toISOString(), live: 2, plan: "free" };
  if (name === "backtest") return { model: "v2", games: 420, updatedAt: "2026-11-15T08:20:00+00:00", calibrationGames: 420,
    calibrationCases: 2400, ece: 0.021, calibrationStatus: "calibrado", duplicatesSkipped: 0,
    params: { k_team: 4, k_comp: 3, k_sd: 40, minCalibGames: 300, liveWeights: { 1: 0.1, 2: 0.2, 3: 0.3 } },
    periods: Object.fromEntries(["q1", "q2", "q3", "q4", "h1", "h2", "reg"].map((k, i) => [k, { n: 120, mae: 5.8 + i * 0.4, maeLiga: 6 + i * 0.45,
      bias: 0.2, brier: 0.224, brierLiga: 0.231, nOrig: 80, maeOrig: 6.6 + i * 0.4, maeV2Same: 5.9 + i * 0.4, brierOrig: 0.241, brierV2Same: 0.223 }])),
    calibration: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8].map((p, i) => ({ lo: p, hi: p + 0.1, n: 100 + 60 * (4 - Math.abs(i - 3.5)), p: p + 0.05, freq: p + 0.05 + (i % 2 ? 0.015 : -0.01) })),
    byComp: [{ name: "Liga Demo A", n: 70, mae: 5.8, maeLiga: 6.1 }, { name: "Copa Demo B", n: 50, mae: 6.2, maeLiga: 6.3 }],
    reference: { games: 40, ece: 0.064, calibrationStatus: "descalibrado" } };
  if (name === "backtest_antigo") return { games: 120, date: "2026-11-15", updatedAt: "2026-11-15T08:20:00+00:00",
    params: { lastN: 10, minPrior: 3, halfLife: 8 },
    periods: { q1: { n: 120, maeSimple: 5.9, maeRecency: 6.1, bias: 0.4, brierModel: 0.232, brierFreq: 0.268 },
      q2: { n: 120, maeSimple: 6.0, maeRecency: 5.8, bias: -0.2, brierModel: 0.236, brierFreq: 0.271 },
      q3: { n: 120, maeSimple: 5.7, maeRecency: 5.9, bias: 0.6, brierModel: 0.229, brierFreq: 0.262 },
      q4: { n: 120, maeSimple: 6.4, maeRecency: 6.3, bias: -0.9, brierModel: 0.241, brierFreq: 0.275 },
      h1: { n: 120, maeSimple: 8.6, maeRecency: 8.7, bias: 0.2, brierModel: 0.238, brierFreq: 0.27 },
      h2: { n: 120, maeSimple: 8.9, maeRecency: 8.8, bias: -0.3, brierModel: 0.24, brierFreq: 0.273 },
      reg: { n: 120, maeSimple: 12.4, maeRecency: 12.6, bias: 0.1, brierModel: 0.239, brierFreq: 0.28 } },
    calibration: [{ lo: 0, hi: 0.2, n: 400, p: 0.12, freq: 0.15 }, { lo: 0.2, hi: 0.4, n: 600, p: 0.3, freq: 0.33 },
      { lo: 0.4, hi: 0.6, n: 800, p: 0.5, freq: 0.49 }, { lo: 0.6, hi: 0.8, n: 600, p: 0.7, freq: 0.66 }, { lo: 0.8, hi: 1, n: 400, p: 0.88, freq: 0.84 }],
    byComp: [{ name: "Liga Demo A", n: 70, mae: 5.8 }, { name: "Copa Demo B", n: 50, mae: 6.2 }],
    calibrationCases: 2800, ece: 0.024, calibrationStatus: "calibrado", leakFree: true };
  if (name === "index") return index;
  if (name === "status") {
    return { lastRun: "2026-11-15T08:17:00+00:00", callsThisRun: 31, usedToday: 62, pending: 38,
      lastSummary: { new: 14, details: 29, backfill: "blocked", note: "dados de demonstração" } };
  }
  if (name === "backfill") return { blocked: true, reason: "demonstração" };
  if (name === "status_apisports") return { lastRun: "2026-11-15T08:17:00+00:00", callsThisRun: 25, usedToday: 50 };
  if (name === "backfill_apisports") return { nextDate: "2026-08-20" };
  return null;
};
export const demoTeam = (id) => teams.get(id) || null;
