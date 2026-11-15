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
