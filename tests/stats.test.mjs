import test from "node:test";
import assert from "node:assert/strict";
import { value, sample, mean, std, overPct, summarize, lineGrid, projections } from "../public/js/stats.js";

const e = (n, pts, oppPts, extra = {}) => ({
  gid: "g" + n, sortKey: `2026-11-${String(n).padStart(2, "0")}|g${n}`, cid: "c1", home: n % 2 === 0,
  pts, oppPts, ot: 0, oppOt: 0, ...extra,
});

const rows = [
  e(1, [20, 22, 25, 18], [19, 21, 20, 22]),
  e(2, [25, 20, 30, 20], [22, 24, 21, 19]),
  e(3, [18, 24, 22, 26], [20, 20, 27, 18], { ot: 5, oppOt: 3 }),
  e(4, [22, 21, 28, 19], [18, 25, 24, 21]),
];

test("value por período e lado", () => {
  assert.equal(value(rows[0], "q3", "for"), 25);
  assert.equal(value(rows[0], "q3", "against"), 20);
  assert.equal(value(rows[0], "q3", "sum"), 45);
  assert.equal(value(rows[0], "h2", "for"), 43);
  assert.equal(value(rows[0], "reg", "sum"), 85 + 82);
  assert.equal(value(rows[2], "reg", "for"), 90);
  assert.equal(value(rows[2], "total", "for"), 95);
  assert.equal(value(rows[2], "total", "against"), 85 + 3);
  assert.throws(() => value(rows[0], "xx", "for"));
});

test("amostra: ordem, corte, mando e competição", () => {
  assert.deepEqual(sample(rows, { n: 2 }).map((r) => r.gid), ["g4", "g3"]);
  assert.deepEqual(sample(rows, { n: 20, venue: "home" }).map((r) => r.gid), ["g4", "g2"]);
  assert.deepEqual(sample(rows, { n: 20, venue: "away" }).map((r) => r.gid), ["g3", "g1"]);
  assert.equal(sample(rows, { cid: "outra" }).length, 0);
  assert.equal(sample(rows, { n: 20 }).length, 4); // nunca inventa jogos
});

test("média e desvio", () => {
  assert.equal(mean([]), null);
  assert.equal(mean([2, 4, 6]), 4);
  assert.equal(std([5]), null);
  assert.ok(Math.abs(std([2, 4, 4, 4, 5, 5, 7, 9]) - 2.138089935) < 1e-6); // amostral
});

test("over é estritamente acima da linha", () => {
  assert.equal(overPct([40, 41, 42, 43], 41.5), 50);
  assert.equal(overPct([40, 41, 42, 43], 41), 50); // 41 não conta
  assert.equal(overPct([], 41.5), null);
});

test("resumo do 3º quarto", () => {
  const s = summarize(rows, "q3");
  assert.equal(s.n, 4);
  assert.equal(s.forAvg, (25 + 30 + 22 + 28) / 4);
  assert.equal(s.againstAvg, (20 + 21 + 27 + 24) / 4);
  assert.equal(s.totalAvg, s.forAvg + s.againstAvg);
  assert.deepEqual(s.totalSeries, [45, 51, 49, 52]);
  assert.equal(s.totalMin, 45);
  assert.equal(s.totalMax, 52);
});

test("grade de linhas", () => {
  assert.deepEqual(lineGrid(46.2), [43.5, 44.5, 45.5, 46.5, 47.5, 48.5, 49.5]);
  assert.deepEqual(lineGrid(null), []);
});

test("projeções", () => {
  const A = { n: 20, forAvg: 45, againstAvg: 43 };
  const B = { n: 20, forAvg: 47, againstAvg: 44 };
  const p = projections(A, B);
  assert.equal(p.somaOfensiva, 92);
  assert.equal(p.pontosA, (45 + 44) / 2);
  assert.equal(p.pontosB, (47 + 43) / 2);
  assert.equal(p.cruzada, 44.5 + 45);
  assert.equal(projections({ n: 0 }, B).cruzada, null);
});

import { normCdf, liveProjection, probOver } from "../public/js/stats.js";

test("normal acumulada", () => {
  assert.ok(Math.abs(normCdf(0) - 0.5) < 1e-6);
  assert.ok(Math.abs(normCdf(1.96) - 0.975) < 1e-3);
  assert.ok(Math.abs(normCdf(-1) - 0.158655) < 1e-3);
});

function mk(n, base, spread) {
  return Array.from({ length: n }, (_, i) => {
    const d = (i % 5) - 2; // variação determinística
    return e(i + 1, [base + d * spread, base - d, base + d, base], [base - d, base + d * spread, base, base + d]);
  });
}

test("projeção ao vivo: ritmo igual ao esperado não muda a média", () => {
  const rows = mk(20, 22, 1);
  const q1 = summarize(rows, "q1");
  const exp = (q1.forAvg + q1.againstAvg);
  const played = [{ a: q1.forAvg, b: q1.againstAvg }];
  const r = liveProjection(rows, rows, played);
  assert.ok(Math.abs(r.pace - exp / exp) < 1e-9 || Math.abs(r.pace - 1) < 1e-9);
  assert.ok(Math.abs(r.mult - 1) < 1e-9);
  assert.equal(r.rest.length, 3);
  assert.equal(r.nextQuarter.quarter, 2);
});

test("projeção ao vivo: jogo mais rápido eleva só parcialmente", () => {
  const rows = mk(20, 22, 1);
  const base = liveProjection(rows, rows, [{ a: 22, b: 22 }]);
  const hot = liveProjection(rows, rows, [{ a: 33, b: 33 }]); // ritmo 50% acima
  assert.ok(hot.pace > 1.4);
  assert.ok(hot.mult > 1 && hot.mult < hot.pace); // peso parcial
  assert.ok(Math.abs(hot.mult - (1 + 0.2 * (hot.pace - 1))) < 1e-9);
  assert.ok(hot.rest[0].total > base.rest[0].total);
  assert.ok(Math.abs(hot.finalTotal - (hot.playedTotal + hot.rest.reduce((s, q) => s + q.total, 0))) < 1e-9);
});

test("projeção ao vivo: sem amostra ou dispersão devolve null", () => {
  assert.equal(liveProjection([], [], [{ a: 20, b: 20 }]), null);
  // com 1 jogo não há desvio próprio: usa o padrão da liga em vez de recusar
  assert.equal(liveProjection(mk(1, 22, 1), mk(1, 22, 1), [{ a: 20, b: 20 }]).rest[0].sd, 7.5);
  assert.equal(liveProjection(mk(20, 22, 1), mk(20, 22, 1), []), null);
  assert.equal(liveProjection(mk(20, 22, 1), mk(20, 22, 1), [{ a: 1, b: 1 }, { a: 1, b: 1 }, { a: 1, b: 1 }, { a: 1, b: 1 }]), null);
});

test("probOver", () => {
  assert.ok(Math.abs(probOver(100, 10, 100) - 50) < 0.01);
  assert.ok(probOver(100, 10, 80.5) > 95);
  assert.equal(probOver(100, 0, 90), null);
});

import { wmean, shrunkSd, centralLine, priorFor, HALF_LIFE } from "../public/js/stats.js";

test("recência igual ao Python", () => {
  assert.equal(wmean([10, 0], false), 5);
  const w1 = 0.5 ** (1 / HALF_LIFE);
  assert.ok(Math.abs(wmean([10, 0], true) - 10 / (1 + w1)) < 1e-12);
});

test("dispersão ajustada e priors", () => {
  const few = { n: 2, totalStd: 1 }, many = { n: 60, totalStd: 1 };
  assert.ok(shrunkSd(few, few, 7.5) > shrunkSd(many, many, 7.5));
  assert.equal(shrunkSd({ n: 1, totalStd: null }, { n: 1, totalStd: null }, 7.5), 7.5);
  assert.equal(centralLine(46.2), 46.5);
  assert.equal(priorFor({ comps: { c1: { q3: 9 } }, global: { q3: 8 } }, "c1", "q3"), 9);
  assert.equal(priorFor({ global: { q3: 8 } }, "c2", "q3"), 8);
  assert.equal(priorFor(null, "c2", "q3"), 7.5);
});

test("pré-jogo na projeção ao vivo", () => {
  const rows = mk(20, 22, 1);
  const r = liveProjection(rows, rows, [{ a: 22, b: 22 }]);
  assert.ok(r.pregameTotal > 0);
  assert.ok(Math.abs(r.pregameTotal - (r.expected + r.rest.reduce((s, q) => s + q.total, 0) / r.mult)) < 1e-9);
});

// ---------------------------------------------------------------- modelo v2
import { shape, usable, isWomen, leagueInfo, leagueMean, leagueSd, projectV2, liveV2, pOver, V2, LIVE_WEIGHT_V2 } from "../public/js/stats.js";

const RA = [
  { pts: [22, 20, 25, 21], oppPts: [20, 19, 22, 24], ot: 0, oppOt: 0, home: true },
  { pts: [18, 24, 20, 19], oppPts: [21, 22, 18, 20], ot: 0, oppOt: 0, home: false },
  { pts: [25, 23, 21, 26], oppPts: [24, 20, 23, 22], ot: 6, oppOt: 4, home: true },
];
const RB = [
  { pts: [19, 21, 18, 20], oppPts: [17, 22, 19, 21], ot: 0, oppOt: 0, home: false },
  { pts: [0, 38, 0, 41], oppPts: [0, 35, 0, 37], ot: 0, oppOt: 0, home: true }, // jogo em tempos
];
const LQ = { n: 12, mean: 42.5, sd: 8.2, gmean: 40, pooled: 7.8, scale: 0.95 };
const LR = { n: 12, mean: 170, sd: 16, gmean: 160, pooled: 15, scale: 0.93 };
const close = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test("v2: parâmetros iguais ao Python", () => {
  assert.deepEqual(V2, { k_team: 4, k_comp: 3, k_sd: 40 });
  assert.deepEqual(LIVE_WEIGHT_V2, { 1: 0.1, 2: 0.2, 3: 0.3 });
});

test("v2: formatos de placar", () => {
  assert.equal(shape({ pts: [20, 21, 22, 23], oppPts: [19, 0, 18, 20] }), "quarters");
  assert.equal(shape({ pts: [0, 45, 0, 63], oppPts: [0, 40, 0, 46] }), "halves");
  assert.equal(shape({ pts: [0, 0, 0, 0], oppPts: [0, 0, 0, 0] }), "invalid");
  assert.equal(shape({ pts: [27, 31, 28, 0], oppPts: [27, 24, 27, 0] }), "invalid");
  const halves = { pts: [0, 45, 0, 63], oppPts: [0, 40, 0, 46] };
  assert.equal(usable(halves, "q1"), false);
  assert.equal(usable(halves, "h2"), true);
  assert.equal(usable(halves, "total"), true);
  assert.equal(isWomen("NCAA Women (USA)"), true);
  assert.equal(isWomen("NBA (USA)"), false);
});

test("v2: valores de referência iguais ao Python", () => {
  const p = projectV2(RA, RB, "q2", LQ);
  close(p.mean, 42.24285714285714);
  close(p.sd, 8.044295449636701);
  assert.deepEqual([p.nA, p.nB], [3, 1]);
  close(p.pointsA, 21.385714285714286);
  close(p.pointsB, 20.857142857142858);
  const r = projectV2(RA, RB, "reg", LR);
  close(r.mean, 166.73809523809524);
  close(r.sd, 15.141020674275017);
  close(r.pointsA + r.pointsB, r.mean);
});

test("v2: sem amostra vale a liga; amostra grande vale a equipe", () => {
  const p = projectV2([], [], "q1", LQ);
  close(p.mean, leagueMean(LQ, V2.k_comp));
  const hot = Array.from({ length: 400 }, () => ({ pts: [30, 20, 20, 20], oppPts: [30, 20, 20, 20] }));
  const q = projectV2(hot, hot, "q1", LQ);
  assert.ok(q.mean > p.mean + 0.97 * (60 - p.mean));
  assert.ok(projectV2(hot.slice(0, 1), hot.slice(0, 1), "q1", LQ).mean < p.mean + 0.25 * (60 - p.mean));
  assert.ok(p.sd > q.sd);
  const L0 = { n: 0, mean: null, sd: null, gmean: 33, pooled: 7.8 };
  assert.equal(leagueMean(L0, 3), 33);
  assert.equal(leagueSd(L0, 40), 7.8);
});

test("v2: dados da liga a partir de meta/priors", () => {
  const priors = { v2: {
    comps: { c1: { q1: { n: 20, mean: 41, sd: 8, home: 1.2, msd: 9.5 } } },
    gmean: { m: { q1: 43 }, w: { q1: 33 } }, pooled: { q1: 7.8 }, msd: { q1: 9.9 }, sdScale: { q1: 0.94 },
  } };
  const L = leagueInfo(priors, "c1", "Liga X", "q1");
  assert.deepEqual([L.n, L.mean, L.gmean, L.scale, L.msd], [20, 41, 43, 0.94, 9.5]);
  const W = leagueInfo(priors, "nova", "Liga X Women", "q1");
  assert.deepEqual([W.n, W.gmean, W.msd], [0, 33, 9.9]);
  assert.equal(leagueInfo({}, "c1", "x", "q1"), null); // priors antigos: o painel cai no modelo original
});

test("v2: ao vivo no intervalo (50 x 40), igual ao Python", () => {
  const qs = [{ a: 21, b: 19.5, sd: 7.6 }, { a: 20.5, b: 20, sd: 7.4 }, { a: 21.2, b: 19.8, sd: 7.7 }, { a: 20.4, b: 20.6, sd: 8 }];
  const r = liveV2(qs, [{ a: 27, b: 23 }, { a: 23, b: 17 }], 9);
  assert.equal(r.weight, 0.2);
  close(r.finalTotal, 173.82222222222222);
  close(r.restTotal, 83.82222222222222);
  close(r.sdRest, 11.103603018840326);
  close(r.winA, 0.81112517941598, 1e-6);
  close(pOver(r.restTotal, r.sdRest, 80.5), 0.6176071067414353, 1e-6);
  assert.equal(r.rest.length, 2);
  assert.equal(liveV2(qs, []), null);
  // liga em tempos: 2 períodos, 1º tempo encerrado, peso explícito
  const h = liveV2([{ a: 40, b: 38, sd: 11 }, { a: 41, b: 39, sd: 11 }], [{ a: 45, b: 40 }], null, 0.2);
  close(h.mult, 1 + 0.2 * (85 / 78 - 1));
  assert.equal(h.rest.length, 1);
});
