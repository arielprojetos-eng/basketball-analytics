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
      games.push({ id: `gm_ag_${k}`, t: base + off * 3600, st: s, lg: c.id, ln: c.name, tier: ci,
        h: `tm_demo${ci}_${i}`, hn: c.teams[i], a: `tm_demo${ci}_${i + 1}`, an: c.teams[i + 1],
        hs: s === "NS" ? null : 60 + k * 3, as: s === "NS" ? null : 58 + k * 2 });
      k++;
    }
  });
  games.push({ id: "gm_ag_novo", t: base + 7200, st: "NS", lg: "cp_demo3", ln: "Liga Demo C", tier: 1,
    h: "tm_x1", hn: "Orcas", a: "tm_x2", an: "Pumas", hs: null, as: null });
  return { updatedAt: new Date().toISOString(), games: games.sort((x, y) => x.t - y.t) };
}

export const demoMeta = (name) => {
  if (name === "agenda") return demoAgenda();
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
