import { DEMO, CONFIGURED, getMetas, cachedMetas, getTeam } from "./data.js";
import {
  PERIODS, sample, summarize, overPct, lineGrid, projections, shrunkSd, priorFor, centralLine,
  usable, leagueInfo, projectV2, liveV2, pOver, LIVE_WEIGHT_V2,
} from "./stats.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f1 = (x) => (x == null || Number.isNaN(x) ? "–" : x.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
const f2 = (x) => (x == null ? "–" : x.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const pc = (x) => (x == null ? "–" : Math.round(x) + "%");
const fl = (x) => x.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const hhmm = (d) => d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
const NS = [5, 10, 20];
const MODEL_N = 20; // jogos por equipe na projeção (configuração validada no backtest)

const state = { comp: null, a: null, b: null, period: "q3", n: 20, venue: "all", scope: "comp", recency: false, liveId: null };
let index = null, agenda = null, priors = null, backtestRes = null, statusLive = null;
const jstate = { day: 0, q: "", minN: 0 };

try { Object.assign(state, JSON.parse(localStorage.getItem("ba-state") || "{}")); } catch {}
const save = () => { try { localStorage.setItem("ba-state", JSON.stringify(state)); } catch {} };

// ---------- inicialização ----------
const META_NAMES = ["index", "status", "backfill", "status_apisports", "backfill_apisports", "agenda", "priors", "backtest", "status_live"];
const TABS = { jogos: ["tab-jogos", "Jogos"], vs: ["tab-vs", "Confronto"], live: ["tab-live", "Ao vivo"], modelo: ["tab-modelo", "Modelo"], cov: ["tab-cov", "Dados"] };
let currentTab = "jogos";
let filtersOpen = false;
let wired = false;

async function init() {
  $("demoBanner").hidden = !DEMO;
  document.querySelectorAll(".dk").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
  $("btnFilters").addEventListener("click", () => { filtersOpen = !filtersOpen; switchTab(currentTab, true); });
  const closeSheet = () => { filtersOpen = false; switchTab(currentTab, true); };
  $("sheetBackdrop").addEventListener("click", closeSheet);
  $("btnSheetDone").addEventListener("click", closeSheet);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && filtersOpen) closeSheet(); });
  setupKeyboardFix();
  switchTab("jogos", true);

  if (!CONFIGURED && !DEMO) {
    const n = $("setupNotice");
    n.hidden = false;
    n.innerHTML = "Firebase ainda não configurado. Edite <b>public/js/firebase-config.js</b> ou abra <b>?demo</b> para ver o painel com dados fictícios.";
    $("statusChip").textContent = "sem conexão";
    return;
  }
  const cached = cachedMetas();
  if (cached) { applyData(cached); $("statusChip").classList.add("syncing"); }
  try {
    applyData(await getMetas(META_NAMES));
  } catch (e) {
    if (!cached) {
      $("statusChip").textContent = "sem conexão";
      $("jList").innerHTML = `<div class="empty">Não foi possível carregar os dados (${esc(e.message)}). Verifique a internet e abra de novo.</div>`;
    } else $("statusChip").textContent = "offline, dados salvos";
  } finally {
    $("statusChip").classList.remove("syncing");
  }
  // placares ao vivo: a coleta grava a cada 10 a 30 min; o painel confere a cada 3 min enquanto está aberto
  setInterval(refreshLive, 180000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshLive(); });
}

let lastLiveFetch = 0;
async function refreshLive() {
  if (document.hidden || DEMO || Date.now() - lastLiveFetch < 120000) return;
  lastLiveFetch = Date.now();
  try {
    const m = await getMetas(["agenda", "status_live"]);
    agenda = m.agenda || agenda;
    statusLive = m.status_live || statusLive;
    renderAgenda();
    renderLiveGames();
    if (currentTab === "live") renderLive();
  } catch { /* sem rede: segue com o que tem */ }
}

function applyData(m) {
  index = m.index; agenda = m.agenda; priors = m.priors; backtestRes = m.backtest; statusLive = m.status_live;
  const runs = [m.status, m.status_apisports].filter((x) => x && x.lastRun).sort((x, y) => (x.lastRun < y.lastRun ? 1 : -1));
  renderStatusChip(runs[0]);
  renderCoverage(index, [
    { name: "API-Sports", status: m.status_apisports, backfill: m.backfill_apisports, live: m.status_live },
    { name: "Basketball API", status: m.status, backfill: m.backfill },
  ]);
  renderModel(backtestRes);
  if (!wired) { setupAgenda(); wireControls(); wired = true; } else renderAgenda();
  renderLiveGames();
  if (!index || !Object.keys(index.competitions || {}).length) {
    $("result").innerHTML = `<div class="empty">Ainda não há jogos com placar por quarto armazenados. Rode o coletor e volte em alguns minutos.</div>`;
    return;
  }
  fillControls();
  render();
}

function switchTab(t, instant) {
  const changed = t !== currentTab;
  currentTab = t;
  document.querySelectorAll(".dk").forEach((b) => {
    const on = b.dataset.tab === t;
    b.classList.toggle("on", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  $("sectionName").textContent = TABS[t][1];
  document.title = `${TABS[t][1]} · Basketball Analytics`;
  for (const [k, [id]] of Object.entries(TABS)) $(id).hidden = k !== t;
  const match = t === "vs" || t === "live";
  $("matchBar").hidden = !match || (t === "live" && !lastRows);
  $("controlsPanel").hidden = !(match && filtersOpen);
  $("sheetBackdrop").hidden = $("controlsPanel").hidden;
  document.body.classList.toggle("sheet-open", !$("controlsPanel").hidden);
  $("btnFilters").classList.toggle("on", filtersOpen);
  $("btnFilters").setAttribute("aria-expanded", String(filtersOpen));
  $("fieldPeriod").hidden = t === "live";
  if (t === "live") renderLive();
  if (changed && !instant) window.scrollTo({ top: 0 });
}

function renderStatusChip(s) {
  const chip = $("statusChip");
  const last = [s?.lastRun, statusLive?.lastRun].filter(Boolean).sort().pop();
  if (!last) { chip.textContent = "sem coleta"; return; }
  const mins = Math.max(0, Math.round((Date.now() - new Date(last).getTime()) / 60000));
  chip.textContent = mins < 90 ? `atualizado há ${mins} min` : mins < 2880 ? `atualizado há ${Math.round(mins / 60)} h` : `atualizado há ${Math.round(mins / 1440)} dias`;
  chip.classList.toggle("ok", mins < 60 * 12);
}

// ---------- controles ----------
const SRC = { apisports: "API-Sports", basketballapi: "Basketball API" };
function compEntries() {
  const list = Object.entries(index?.competitions || {}).filter(([, c]) => Object.values(c.teams || {}).some((t) => t.n > 0));
  const count = {};
  list.forEach(([, c]) => { count[c.name] = (count[c.name] || 0) + 1; });
  return list
    .map(([id, c]) => [id, { ...c, label: count[c.name] > 1 ? `${c.name} (${SRC[c.src || "basketballapi"]})` : c.name }])
    .sort((x, y) => x[1].label.localeCompare(y[1].label, "pt-BR"));
}
const compName = () => index?.competitions?.[state.comp]?.name || state.compName || "";

function teamOptions(cid) {
  const t = index.competitions[cid]?.teams || {};
  return Object.entries(t).sort((x, y) => x[1].name.localeCompare(y[1].name, "pt-BR"));
}

function fillControls() {
  const comps = index ? compEntries() : [];
  if (!comps.length) return;
  if (!comps.some(([id]) => id === state.comp) && !state.compName) state.comp = comps[0][0];
  const sel = $("selComp");
  sel.innerHTML = comps.map(([id, c]) => `<option value="${esc(id)}">${esc(c.label)}</option>`).join("");
  if (comps.some(([id]) => id === state.comp)) sel.value = state.comp;
  const keepA = state.a, keepB = state.b;
  refillTeams();
  if (keepA && state.a !== keepA && state.aName) state.a = keepA;
  if (keepB && state.b !== keepB && state.bName) state.b = keepB;
  $("selVenue").value = state.venue;
  $("selScope").value = state.scope;
  $("selRecency").value = state.recency ? "1" : "0";
  syncChips();
}

function wireControls() {
  $("chipsPeriod").innerHTML = PERIODS.map((p) => `<button class="chipbtn" role="tab" data-v="${p.key}">${p.label}</button>`).join("");
  $("chipsN").innerHTML = NS.map((n) => `<button class="chipbtn" data-v="${n}">${n} jogos</button>`).join("");
  $("selRecency").addEventListener("change", (e) => { state.recency = e.target.value === "1"; render(); });
  $("selComp").addEventListener("change", (e) => { state.comp = e.target.value; state.aName = state.bName = state.compName = null; state.liveId = null; refillTeams(true); render(); });
  $("selA").addEventListener("change", (e) => { state.a = e.target.value; state.aName = null; state.liveId = null; render(); });
  $("selB").addEventListener("change", (e) => { state.b = e.target.value; state.bName = null; state.liveId = null; render(); });
  $("selVenue").addEventListener("change", (e) => { state.venue = e.target.value; render(); });
  $("selScope").addEventListener("change", (e) => { state.scope = e.target.value; render(); });
  $("chipsPeriod").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { state.period = b.dataset.v; syncChips(); render(); } });
  $("chipsN").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { state.n = +b.dataset.v; syncChips(); render(); } });
  syncChips();
}

function refillTeams(reset) {
  const items = teamOptions(state.comp);
  const mk = (sel, cur) => {
    sel.innerHTML = items.map(([id, t]) => `<option value="${esc(id)}">${esc(`${t.name} (${t.n})`)}</option>`).join("");
    if (!reset && items.some(([id]) => id === cur)) sel.value = cur;
    return sel.value;
  };
  state.a = mk($("selA"), state.a);
  state.b = mk($("selB"), state.b);
  if (state.a === state.b && items.length > 1) { $("selB").selectedIndex = 1; state.b = $("selB").value; }
}

function syncChips() {
  document.querySelectorAll("#chipsPeriod .chipbtn").forEach((b) => {
    const on = b.dataset.v === state.period;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on));
  });
  document.querySelectorAll("#chipsN .chipbtn").forEach((b) => b.classList.toggle("on", +b.dataset.v === state.n));
}

// ---------- modelo ----------
// Linhas da projeção: mesma liga, até 20 jogos, jogos válidos para o período (configuração do backtest).
const modelRows = (team, key) => sample((team?.games || []).filter((e) => usable(e, key)), { n: MODEL_N, cid: state.comp });

function modelFor(ta, tb, key) {
  const rA = modelRows(ta, key), rB = modelRows(tb, key);
  const L = leagueInfo(priors, state.comp, compName(), key);
  if (L) {
    const p = projectV2(rA, rB, key, L);
    return { v2: true, mean: p.mean, sd: p.sd, pa: p.pointsA, pb: p.pointsB, nA: p.nA, nB: p.nB, wA: p.shrinkA, wB: p.shrinkB, league: p.league, L };
  }
  // meta/priors ainda sem o v2 (antes da primeira coleta com o código novo): modelo original
  const A = summarize(rA, key), B = summarize(rB, key);
  if (!A.n || !B.n) return null;
  const P = projections(A, B);
  return { v2: false, mean: P.cruzada, sd: shrunkSd(A, B, priorFor(priors, state.comp, key)), pa: P.pontosA, pb: P.pontosB, nA: A.n, nB: B.n };
}

// ---------- confronto ----------
let token = 0;
let lastRows = null;
function setMatchBar(ta, tb) {
  $("mbComp").textContent = compName();
  $("mbA").textContent = ta?.name || state.aName || "Equipe A";
  $("mbB").textContent = tb?.name || state.bName || "Equipe B";
}

async function render() {
  save();
  const my = ++token;
  setMatchBar(null, null);
  let ta, tb;
  try { [ta, tb] = await Promise.all([getTeam(state.a), getTeam(state.b)]); } catch (e) {
    if (my === token) $("result").innerHTML = `<div class="empty">Sem conexão para carregar as equipes (${esc(e.message)}).</div>`;
    return;
  }
  if (my !== token) return;
  // equipe sem histórico ainda: segue com histórico vazio (a projeção v2 usa a liga)
  ta = ta || (state.a ? { id: state.a, name: state.aName || "Equipe A", games: [] } : null);
  tb = tb || (state.b ? { id: state.b, name: state.bName || "Equipe B", games: [] } : null);
  setMatchBar(ta, tb);
  if (!ta || !tb) { $("result").innerHTML = `<div class="empty">Escolha as duas equipes em Filtros.</div>`; lastRows = null; return; }

  const k = state.period;
  const cid = state.scope === "comp" ? state.comp : null;
  const vA = state.venue === "ah" ? "home" : state.venue === "ha" ? "away" : "all";
  const vB = state.venue === "ah" ? "away" : state.venue === "ha" ? "home" : "all";
  const hist = (team, venue) => sample((team.games || []).filter((e) => usable(e, k)), { n: state.n, venue, cid });
  const rowsA = hist(ta, vA), rowsB = hist(tb, vB);
  const A = summarize(rowsA, k, state.recency), B = summarize(rowsB, k, state.recency);
  const label = PERIODS.find((p) => p.key === k).label;
  const P = modelFor(ta, tb, k);
  const halvesOnly = ["q1", "q2", "q3", "q4"].includes(k) && modelRows(ta, k).length === 0 && modelRows(ta, "h1").length > 0;

  $("result").innerHTML = `<div class="board">
    ${halvesOnly ? `<div class="note warn">Esta liga chega com placar por tempo, não por quarto. Use 1º tempo, 2º tempo ou jogo.</div>` : ""}
    <div class="split2">${heroCard(P, label, ta, tb)}${linesCard(P, A, B, ta, tb)}</div>
    ${scoreboard(ta, tb, A, B, label)}
    <section class="group"><div class="group-h"><h3>Pontos marcados no ${esc(label.toLowerCase())}, jogo a jogo</h3></div>
      <div class="charts">${chartCard(ta.name, A, rowsA, "a", label)}${chartCard(tb.name, B, rowsB, "b", label)}</div></section>
    ${gamesCard(ta.name, rowsA, "a")}${gamesCard(tb.name, rowsB, "b")}
  </div>`;
  lastRows = { ta, tb };
  if (currentTab === "live") { $("matchBar").hidden = false; renderLive(); }
}

function rangeSvg(mean, sd, line) {
  const W = 340, H = 74, base = 52, lo = mean - 2.6 * sd, hi = mean + 2.6 * sd;
  const x = (v) => 6 + ((v - lo) / (hi - lo)) * (W - 12);
  const dens = (v) => Math.exp(-0.5 * ((v - mean) / sd) ** 2);
  const pts = Array.from({ length: 61 }, (_, i) => lo + (i / 60) * (hi - lo));
  const path = (from, to) => {
    const xs = pts.filter((v) => v >= from && v <= to);
    return `M${x(xs[0]).toFixed(1)},${base} ` + xs.map((v) => `L${x(v).toFixed(1)},${(base - dens(v) * 40).toFixed(1)}`).join(" ") + ` L${x(xs.at(-1)).toFixed(1)},${base} Z`;
  };
  const z = 1.2816, a = mean - z * sd, b = mean + z * sd;
  return `<svg class="range" viewBox="0 0 ${W} ${H}" role="img" aria-label="Distribuição prevista: 80% de chance entre ${fl(a)} e ${fl(b)} pontos">
    <path d="${path(lo, hi)}" fill="#e3efe8"/>
    <path d="${path(a, b)}" fill="#bcd9c9"/>
    <line x1="${x(line)}" x2="${x(line)}" y1="6" y2="${base}" stroke="#16221c" stroke-width="1.2" stroke-dasharray="3 3"/>
    <line x1="0" x2="${W}" y1="${base}" y2="${base}" stroke="#d3dad6"/>
    <text x="${x(a)}" y="${H - 6}" text-anchor="middle">${fl(a)}</text>
    <text x="${x(b)}" y="${H - 6}" text-anchor="middle">${fl(b)}</text>
    <text x="${Math.min(Math.max(x(line), 40), W - 40)}" y="12" text-anchor="${x(line) > W - 60 ? "end" : "start"}" dx="${x(line) > W - 60 ? -5 : 5}">linha ${fl(line)}</text>
  </svg>`;
}

function heroCard(P, label, ta, tb) {
  if (!P) return `<div class="group pad"><h3 style="margin:0">Projeção do ${esc(label.toLowerCase())}</h3><div class="hint">Sem amostra suficiente para projetar.</div></div>`;
  const line = centralLine(P.mean);
  const shr = (w, n) => (P.v2 ? `${n} jogo${n === 1 ? "" : "s"}, peso ${Math.round(w * 100)}%` : `${n} jogo${n === 1 ? "" : "s"}`);
  const tag = P.v2
    ? (["calibrado", "aceitável"].includes(backtestRes?.calibrationStatus) ? `<span class="tag green">modelo v2 validado</span>` : `<span class="tag warn">modelo v2, calibração pendente</span>`)
    : `<span class="tag warn">modelo original</span>`;
  const how = P.v2
    ? `Média da liga (${fl(P.league)}) ajustada pelo histórico das equipes na proporção da amostra: com poucos jogos, a equipe pesa pouco. ${P.nA + P.nB === 0 ? "Sem jogos das equipes nesta liga: vale só a média da liga." : ""}`
    : `Projeção cruzada do modelo original. O v2 entra quando a coleta gravar os dados da liga.`;
  return `<section class="group hero">
    <div class="hero-top"><div class="hero-l">Total projetado, ${esc(label.toLowerCase())}</div>${tag}</div>
    <div class="hero-k">${fl(P.mean)}<small>± ${fl(P.sd)} pts</small></div>
    ${rangeSvg(P.mean, P.sd, line)}
    <div class="hero-split">
      <div><b class="a">${f1(P.pa)}</b><small>${esc(ta.name)}</small></div>
      <div><b class="b">${f1(P.pb)}</b><small>${esc(tb.name)}</small></div>
      ${P.v2 ? `<div><b>${f1(P.league)}</b><small>média da liga</small></div>` : `<div><b>${f1(P.sd)}</b><small>dispersão</small></div>`}
    </div>
    <p class="hint">Amostra: ${esc(ta.name)} ${shr(P.wA, P.nA)}; ${esc(tb.name)} ${shr(P.wB, P.nB)}. ${how}</p>
  </section>`;
}

function pbar(p, cls = "") {
  return p == null ? `<div class="pbar na"><i></i><span>–</span></div>` : `<div class="pbar ${cls}" style="--w:${Math.max(0, Math.min(100, p))}%"><i></i><span>${pc(p)}</span></div>`;
}

function linesCard(P, A, B, ta, tb) {
  if (!P) return "";
  const center = centralLine(P.mean);
  const rows = lineGrid(P.mean, 3).map((line) => {
    const p = pOver(P.mean, P.sd, line) * 100;
    return `<tr class="${line === center ? "mid" : ""}"><td>${fl(line)}</td><td>${pbar(p)}</td>
      <td class="r freq">${pc(overPct(A.totalSeries, line))}</td><td class="r freq">${pc(overPct(B.totalSeries, line))}</td></tr>`;
  }).join("");
  const ok = ["calibrado", "aceitável"].includes(backtestRes?.calibrationStatus);
  return `<section class="group"><div class="group-h"><h3>Chance de Over</h3><span>linha central destacada</span></div>
    <div class="tw"><table class="lines"><thead><tr><th>Linha</th><th>Chance estimada</th>
      <th class="r" title="Frequência no histórico de ${esc(ta.name)}">Freq. A</th><th class="r" title="Frequência no histórico de ${esc(tb.name)}">Freq. B</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <div style="padding:0 16px 16px">
      ${ok ? "" : `<div class="note warn" style="margin-top:10px">Chances ainda não validadas pelo backtest. Use como referência.</div>`}
      <p class="hint"><b>Chance estimada</b>: curva normal com a dispersão da liga e a incerteza da amostra. <b>Freq. A e B</b>: em quantos jogos do histórico filtrado a soma passou da linha. Com poucos jogos, frequência não é probabilidade: no backtest ela errou muito mais que a chance estimada (aba Modelo).</p>
    </div></section>`;
}

function nCell(S) {
  const cls = S.n >= state.n ? "" : S.n < 5 ? "bad" : "warn";
  return `<span class="n ${cls}">${S.n}${S.n < state.n ? ` de ${state.n}` : ""}</span>`;
}

function scoreboard(ta, tb, A, B, label) {
  const row = (l, a, b, best) => {
    const ca = best && a != null && b != null && best(a, b) ? "lead" : "";
    const cb = best && a != null && b != null && best(b, a) ? "lead" : "";
    return `<tr><td>${l}</td><td class="r a ${ca}">${f1(a)}</td><td class="r b ${cb}">${f1(b)}</td></tr>`;
  };
  return `<section class="group"><div class="group-h"><h3>Histórico no ${esc(label.toLowerCase())}</h3><span>${state.recency ? "mais peso aos recentes" : "peso igual"}</span></div>
    <div class="tw"><table class="cmp"><thead><tr><th></th><th class="r">${esc(ta.name)}</th><th class="r">${esc(tb.name)}</th></tr></thead><tbody>
      ${row("Marcados, média", A.forAvg, B.forAvg, (x, y) => x > y)}
      ${row("Sofridos, média", A.againstAvg, B.againstAvg, (x, y) => x < y)}
      ${row("Soma no jogo", A.totalAvg, B.totalAvg)}
      ${row("Desvio da soma", A.totalStd, B.totalStd)}
      <tr><td>Menor e maior soma</td><td class="r">${A.totalMin ?? "–"} a ${A.totalMax ?? "–"}</td><td class="r">${B.totalMin ?? "–"} a ${B.totalMax ?? "–"}</td></tr>
      <tr><td>Jogos na amostra</td><td class="r">${nCell(A)}</td><td class="r">${nCell(B)}</td></tr>
    </tbody></table></div></section>`;
}

function chartCard(name, S, rows, k, label) {
  const vals = S.forSeries.slice().reverse();
  if (!vals.length) return `<div class="chart"><div class="chart-h"><b class="${k}">${esc(name)}</b></div><div class="n">Sem jogos no histórico filtrado.</div></div>`;
  const chrono = [...rows].reverse();
  const W = 340, H = 112, padT = 8, padB = 20, step = (W - 4) / vals.length, bw = Math.max(4, Math.min(22, step * 0.6));
  const max = Math.max(...vals, S.forAvg) * 1.12;
  const x = (i) => 2 + i * step + (step - bw) / 2;
  const y = (v) => padT + (H - padT - padB) * (1 - v / max);
  const color = k === "a" ? "var(--a)" : "var(--b)";
  const bars = vals.map((v, i) => `<rect x="${x(i).toFixed(1)}" y="${y(v).toFixed(1)}" width="${bw.toFixed(1)}" height="${(H - padB - y(v)).toFixed(1)}" rx="3" fill="${color}" opacity="${i === vals.length - 1 ? 1 : 0.45}"><title>${v} pontos</title></rect>`).join("");
  const ay = y(S.forAvg).toFixed(1);
  const d = (e) => e?.date?.slice(5).split("-").reverse().join("/") || "";
  return `<div class="chart"><div class="chart-h"><b class="${k}">${esc(name)}</b><span>média ${f1(S.forAvg)}</span></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Pontos marcados no ${esc(label.toLowerCase())} nos últimos ${vals.length} jogos de ${esc(name)}">
      <line x1="0" x2="${W}" y1="${H - padB}" y2="${H - padB}" stroke="#e2e7e4"/>${bars}
      <line x1="0" x2="${W}" y1="${ay}" y2="${ay}" stroke="#16221c" stroke-dasharray="3 4" opacity=".45"/>
      <text x="0" y="${H - 5}">${esc(d(chrono[0]))}</text><text x="${W}" y="${H - 5}" text-anchor="end">${esc(d(chrono.at(-1)))}, mais recente</text>
    </svg></div>`;
}

function gamesCard(name, rows, k) {
  if (!rows.length) return "";
  const key = state.period;
  const pv = (arr, ot) => ({ q1: arr[0], q2: arr[1], q3: arr[2], q4: arr[3], h1: arr[0] + arr[1], h2: arr[2] + arr[3],
    reg: arr.reduce((s, x) => s + x, 0), total: arr.reduce((s, x) => s + x, 0) + (ot || 0) }[key]);
  const body = rows.map((e) => {
    const m = pv(e.pts, e.ot), o = pv(e.oppPts, e.oppOt);
    return `<tr><td>${e.date.split("-").reverse().slice(0, 2).join("/")}</td><td>${e.home ? "casa" : "fora"}</td><td>${esc(e.oppName)}</td>
      <td class="r"><b>${m}</b> x ${o}</td><td class="r">${m + o}</td></tr>`;
  }).join("");
  return `<details class="glist-d"><summary class="${k}">Jogos de ${esc(name)} <span class="n">${rows.length}</span></summary><div class="tw">
    <table><thead><tr><th>Data</th><th>Mando</th><th>Adversário</th><th class="r">Placar</th><th class="r">Soma</th></tr></thead>
    <tbody>${body}</tbody></table></div></details>`;
}

// ---------- ao vivo ----------
const LIVE = new Set(["Q1", "Q2", "Q3", "Q4", "OT", "BT", "HT"]);
const DONE = new Set(["FT", "AOT"]);
const OFF = { POST: "Adiado", CANC: "Cancelado", SUSP: "Suspenso", AWD: "W.O.", ABD: "Abandonado" };
const liveVals = [{ a: "", b: "" }, { a: "", b: "" }, { a: "", b: "" }];
let manualLive = false;

const liveNow = () => (agenda?.games || []).filter((g) => LIVE.has(g.st)).sort((a, b) => a.t - b.t);
function agendaGameFor() {
  const gs = agenda?.games || [];
  return gs.find((g) => g.id === state.liveId) || gs.find((g) => g.h === state.a && g.a === state.b && (LIVE.has(g.st) || DONE.has(g.st)));
}

// Quartos (ou tempos) já encerrados, pelo status da partida. O quarto em andamento não entra.
function completedFromAgenda(g, halves) {
  if (!g?.hq || !g?.aq) return null;
  const st = g.st;
  if (halves) {
    const n = st === "HT" || st === "Q3" || st === "Q4" || (st === "BT" && g.hq[2] != null) ? 1 : 0;
    return n ? [{ a: (g.hq[0] || 0) + (g.hq[1] || 0), b: (g.aq[0] || 0) + (g.aq[1] || 0) }] : [];
  }
  const byStatus = { Q1: 0, Q2: 1, HT: 2, Q3: 2, Q4: 3 }[st];
  let n = byStatus;
  if (st === "BT") n = g.hq.filter((x) => x != null).length;
  if (n == null) return null;
  const out = [];
  for (let i = 0; i < Math.min(n, 3); i++) {
    if (g.hq[i] == null || g.aq[i] == null) break;
    out.push({ a: g.hq[i], b: g.aq[i] });
  }
  return out;
}

function renderLiveGames() {
  const box = $("liveGames");
  const list = liveNow();
  $("liveDot").hidden = !list.length;
  if (!list.length) {
    const nxt = (agenda?.games || []).filter((g) => g.st === "NS" && g.t * 1000 > Date.now()).sort((a, b) => a.t - b.t)[0];
    box.innerHTML = `<div class="note warn">Nenhum jogo ao vivo na última coleta${statusLive?.lastRun ? ` (${hhmm(new Date(statusLive.lastRun))})` : ""}.${nxt ? ` Próximo: ${esc(nxt.hn)} x ${esc(nxt.an)} às ${hhmm(new Date(nxt.t * 1000))}.` : ""} Você ainda pode preencher os quartos à mão para o confronto escolhido.</div>`;
    return;
  }
  const cur = agendaGameFor()?.id;
  box.innerHTML = `<div class="sec-h"><h2>Ao vivo agora</h2><span>${list.length} jogo${list.length > 1 ? "s" : ""}</span></div>
    <div class="livelist">${list.map((g) => `<button class="lv ${g.id === cur ? "on" : ""}" data-id="${esc(g.id)}">
      <div class="lv-top"><span>${esc(g.ln)}</span><span class="tag live">${g.st === "HT" ? "Intervalo" : g.st === "BT" ? "Pausa" : g.st}</span></div>
      <div class="lv-row"><b>${esc(g.hn)}</b><span>${g.hs ?? "–"}</span></div>
      <div class="lv-row"><b>${esc(g.an)}</b><span>${g.as ?? "–"}</span></div></button>`).join("")}</div>`;
  box.onclick = (e) => {
    const b = e.target.closest(".lv"); if (!b) return;
    const g = list.find((x) => x.id === b.dataset.id);
    if (g) openMatch(g, "live");
  };
}

function isHalvesLeague() {
  if (!lastRows) return false;
  const { ta, tb } = lastRows;
  const q = modelRows(ta, "q1").length + modelRows(tb, "q1").length;
  const h = modelRows(ta, "h1").length + modelRows(tb, "h1").length;
  const Lq = leagueInfo(priors, state.comp, compName(), "q1"), Lh = leagueInfo(priors, state.comp, compName(), "h1");
  return q === 0 && (h > 0 || (Lq && Lq.n === 0 && Lh && Lh.n >= 5));
}

function renderLive() {
  renderLiveGames();
  const form = $("liveForm");
  if (!lastRows) { form.innerHTML = `<div class="hint" style="margin:0">Escolha um jogo ao vivo acima ou um confronto em Jogos.</div>`; $("liveResult").innerHTML = ""; return; }
  $("matchBar").hidden = currentTab !== "live" && currentTab !== "vs";
  const { ta, tb } = lastRows;
  const halves = isHalvesLeague();
  const g = agendaGameFor();
  const auto = !manualLive ? completedFromAgenda(g, halves) : null;
  const slots = halves ? 1 : 3;
  if (auto) {
    for (let i = 0; i < 3; i++) liveVals[i] = auto[i] ? { a: String(auto[i].a), b: String(auto[i].b) } : { a: "", b: "" };
  }
  const typing = form.contains(document.activeElement);
  if (!typing) {
    const labels = halves ? ["1º tempo"] : ["1º quarto", "2º quarto", "3º quarto"];
    const cur = g && LIVE.has(g.st) && g.hq ? currentPartial(g, halves) : "";
    const head = auto
      ? `<div class="auto-line"><span class="tag live">Placar automático, coleta das ${hhmm(new Date(agenda?.liveAt || agenda?.updatedAt || Date.now()))}</span><button class="linkbtn" id="btnManual">Editar à mão</button></div>`
      : g?.hq ? `<div class="auto-line"><span class="tag">Edição manual</span><button class="linkbtn" id="btnAuto">Voltar ao automático</button></div>` : "";
    form.innerHTML = head + `<div class="live-head"><span></span><span class="a">${esc(ta.name)}</span><span class="b">${esc(tb.name)}</span></div>` +
      labels.slice(0, slots).map((l, i) => `<div class="live-row"><label for="la${i}">${l}</label>
        <input id="la${i}" data-i="${i}" data-s="a" class="sc a" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="3" autocomplete="off" placeholder="–" value="${esc(liveVals[i].a)}" ${auto ? "readonly" : ""}>
        <input id="lb${i}" data-i="${i}" data-s="b" class="sc b" type="text" inputmode="numeric" pattern="[0-9]*" maxlength="3" autocomplete="off" placeholder="–" value="${esc(liveVals[i].b)}" ${auto ? "readonly" : ""}></div>`).join("") +
      (cur ? `<p class="hint">${cur}</p>` : "") +
      `<p class="hint">${halves ? "Liga com placar por tempo: informe o 1º tempo." : "Só entram períodos encerrados, em ordem."} A projeção usa o modelo validado no backtest.</p>`;
    form.oninput = (e) => {
      const el = e.target.closest("input"); if (!el) return;
      el.value = el.value.replace(/\D/g, "").slice(0, 3);
      liveVals[+el.dataset.i][el.dataset.s] = el.value;
      renderLiveResult(halves);
    };
    form.onclick = (e) => {
      if (e.target.id === "btnManual") { manualLive = true; renderLive(); }
      if (e.target.id === "btnAuto") { manualLive = false; renderLive(); }
    };
  }
  renderLiveResult(halves);
}

function currentPartial(g, halves) {
  if (halves || !["Q1", "Q2", "Q3", "Q4"].includes(g.st)) return "";
  const i = +g.st[1] - 1;
  if (g.hq[i] == null) return "";
  return `${i + 1}º quarto em andamento: ${g.hq[i]} x ${g.aq[i]} (ainda não entra na projeção).`;
}

function periodModels(halves) {
  const { ta, tb } = lastRows;
  const keys = halves ? ["h1", "h2"] : ["q1", "q2", "q3", "q4"];
  const per = keys.map((k) => {
    const P = modelFor(ta, tb, k);
    return P ? { a: P.pa, b: P.pb, sd: P.sd, msd: P.L?.msd ?? null } : null;
  });
  return per.some((x) => !x) ? null : per;
}

function renderLiveResult(halves) {
  const out = $("liveResult");
  if (!lastRows) { out.innerHTML = ""; return; }
  const { ta, tb } = lastRows;
  const played = [];
  for (const v of liveVals.slice(0, halves ? 1 : 3)) {
    const a = v.a === "" ? NaN : Number(v.a), b = v.b === "" ? NaN : Number(v.b);
    if (!Number.isInteger(a) || !Number.isInteger(b) || a < 0 || b < 0) break;
    played.push({ a, b });
  }
  if (!played.length) { out.innerHTML = `<div class="empty">Assim que ${halves ? "o 1º tempo" : "o 1º quarto"} terminar, as chances aparecem aqui.</div>`; return; }
  const per = periodModels(halves);
  if (!per) { out.innerHTML = `<div class="empty">Amostra insuficiente para projetar este confronto.</div>`; return; }
  const msd = per.map((q) => q.msd).filter(Boolean);
  const marginSd = msd.length ? Math.sqrt(msd.reduce((s, x) => s + x * x, 0) / msd.length) : null;
  const R = liveV2(per, played, marginSd, halves ? LIVE_WEIGHT_V2[2] : null);
  if (!R) { out.innerHTML = ""; return; }
  const k = played.length;
  const pregame = per.reduce((s, q) => s + q.a + q.b, 0);
  const restLabel = halves ? "2º tempo" : k === 2 ? "2º tempo (3º e 4º quartos)" : k === 1 ? "2º ao 4º quarto" : "4º quarto";
  const ladder = (title, mean, sd, cls) => `<section class="group"><div class="group-h"><h3>${title}</h3><span>projeção ${fl(mean)} ± ${fl(sd)}</span></div>
    <div class="tw"><table class="lines"><thead><tr><th>Linha</th><th>Over</th><th class="r">Under</th></tr></thead><tbody>
    ${lineGrid(mean, 3).map((line) => { const p = pOver(mean, sd, line) * 100; return `<tr class="${line === centralLine(mean) ? "mid" : ""}"><td>${fl(line)}</td><td>${pbar(p, cls)}</td><td class="r freq">${pc(100 - p)}</td></tr>`; }).join("")}
    </tbody></table></div></section>`;
  const win = R.winA == null ? null : R.winA * 100;
  const ok = ["calibrado", "aceitável"].includes(backtestRes?.calibrationStatus);
  out.innerHTML = `<div class="board">
    <div class="score">
      <div class="side a"><h3>${esc(ta.name)}</h3><div class="n">${R.playedA} pts até agora</div><div class="big num">${fl(R.finalA)}<small>projeção final</small></div></div>
      <div class="side b"><h3>${esc(tb.name)}</h3><div class="n">${R.playedB} pts até agora</div><div class="big num">${fl(R.finalB)}<small>projeção final</small></div></div>
    </div>
    ${win == null ? "" : `<section class="group pad"><div class="group-h" style="padding:0 0 6px"><h3>Chance de vitória no tempo normal</h3></div>
      <div class="winbar"><i class="a" style="width:${win}%"></i><i class="b" style="width:${100 - win}%"></i></div>
      <div style="display:flex;justify-content:space-between;font-weight:650"><span style="color:var(--a)">${esc(ta.name)} ${pc(win)}</span><span style="color:var(--b)">${pc(100 - win)} ${esc(tb.name)}</span></div>
      <p class="hint">Saldo projetado ${R.margin >= 0 ? "+" : ""}${fl(R.margin)} para ${esc(ta.name)}. Empate no tempo normal leva à prorrogação, que não entra aqui.</p></section>`}
    <section class="group"><div class="kpis">
      <div class="kpi"><div class="k num">${fl(R.finalTotal)}</div><small>total final projetado</small></div>
      <div class="kpi"><div class="k num">${fl(R.restTotal)}</div><small>${restLabel}</small></div>
      <div class="kpi"><div class="k num">${(R.pace - 1 >= 0 ? "+" : "") + Math.round((R.pace - 1) * 100)}%</div><small>ritmo vs. esperado</small></div>
      <div class="kpi"><div class="k num">${Math.round(R.weight * 100)}%</div><small>peso do ritmo</small></div>
    </div><div class="delta">Projeção pré-jogo <b>${fl(pregame)}</b>, agora <b>${fl(R.finalTotal)}</b> (${R.finalTotal - pregame >= 0 ? "+" : ""}${fl(R.finalTotal - pregame)})</div></section>
    <div class="split2">
      ${ladder(`Over do ${restLabel.split(" (")[0]}`, R.restTotal, R.sdRest, "")}
      ${ladder("Over do jogo (tempo normal)", R.finalTotal, R.sdRest, "b")}
    </div>
    ${!halves && k < 3 && R.rest.length > 1 ? ladder(`Over do ${R.nextQuarter.quarter}º quarto`, R.nextQuarter.total, R.nextQuarter.sd, "") : ""}
    ${ok ? "" : `<div class="note warn">Chances ainda não validadas pelo backtest.</div>`}
    <p class="hint">O ritmo observado entra com peso de ${Math.round(R.weight * 100)}%, escolhido no backtest: o que acontece num período prevê pouco o seguinte. O restante vem da projeção pré-jogo. Prorrogação não entra. Estimativa estatística, sujeita a erro.</p>
  </div>`;
}

// ---------- modelo (backtest) ----------
const CAL_TXT = {
  "calibrado": ["ok", "Chances calibradas", "O previsto bate com o que aconteceu, fora da amostra."],
  "aceitável": ["warn", "Chances aceitáveis", "Pequeno desvio entre previsto e realizado."],
  "descalibrado": ["bad", "Chances descalibradas", "Não use os percentuais como probabilidade."],
  "amostra insuficiente": ["warn", "Calibração pendente", "Ainda não há jogos suficientes para verificar."],
  "sem dados": ["warn", "Calibração pendente", "Nenhum jogo avaliado ainda."],
};
const PLABEL = { q1: "1º quarto", q2: "2º quarto", q3: "3º quarto", q4: "4º quarto", h1: "1º tempo", h2: "2º tempo", reg: "Tempo normal" };

function calibrationSvg(cal) {
  const W = 320, H = 240, p = 34;
  const x = (v) => p + v * (W - p - 10), y = (v) => H - p - v * (H - p - 10);
  const pts = cal.filter((c) => c.n && c.p != null);
  const max = Math.max(...pts.map((c) => c.n));
  const grid = [0, 0.25, 0.5, 0.75, 1].map((v) => `<line x1="${x(0)}" x2="${x(1)}" y1="${y(v)}" y2="${y(v)}" stroke="#eef1ef"/><text x="${p - 6}" y="${y(v) + 4}" text-anchor="end">${v * 100}%</text><text x="${x(v)}" y="${H - p + 16}" text-anchor="middle">${v * 100}%</text>`).join("");
  const line = pts.map((c, i) => `${i ? "L" : "M"}${x(c.p).toFixed(1)},${y(c.freq).toFixed(1)}`).join(" ");
  const dots = pts.map((c) => `<circle cx="${x(c.p).toFixed(1)}" cy="${y(c.freq).toFixed(1)}" r="${(3 + 6 * Math.sqrt(c.n / max)).toFixed(1)}" fill="#12603e" fill-opacity=".85"><title>previsto ${pc(c.p * 100)}, aconteceu ${pc(c.freq * 100)} (${c.n} casos)</title></circle>`).join("");
  return `<svg class="calsvg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Diagrama de calibração: chance prevista contra frequência observada">
    ${grid}<line x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}" stroke="#a8581c" stroke-dasharray="4 4"/>
    <path d="${line}" fill="none" stroke="#12603e" stroke-width="1.6"/>${dots}
    <text x="${x(0.5)}" y="${H - 4}" text-anchor="middle">chance prevista</text>
    <text x="10" y="${y(0.5)}" text-anchor="middle" transform="rotate(-90 10 ${y(0.5)})">aconteceu</text></svg>`;
}

function renderModel(bt) {
  const box = $("modelo");
  if (!bt || !bt.games) {
    box.innerHTML = `<div class="empty">Ainda sem jogos avaliados. O backtest roda uma vez por dia, na primeira coleta completa.</div>`;
    return;
  }
  const st = bt.calibrationStatus || "sem dados";
  const [cls, title, sub] = CAL_TXT[st] || CAL_TXT["sem dados"];
  const ece = bt.ece != null ? (bt.ece * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 }) : "–";
  if (bt.model !== "v2") { box.innerHTML = legacyModel(bt, cls, title, sub, ece); return; }
  const rows = Object.entries(PLABEL).map(([k, l]) => {
    const d = bt.periods?.[k];
    if (!d || !d.n) return "";
    const best = Math.min(d.mae, d.maeLiga);
    return `<tr><td>${l}</td><td class="r">${d.n}</td><td class="r ${d.mae === best ? "best" : ""}">${f2(d.mae)}</td><td class="r ${d.maeLiga === best && d.mae !== best ? "best" : "worse"}">${f2(d.maeLiga)}</td>
      <td class="r">${d.nOrig ? `${f2(d.maeOrig)} <span class="n">vs ${f2(d.maeV2Same)}</span>` : "–"}</td>
      <td class="r">${d.brier.toFixed(3).replace(".", ",")}</td><td class="r hide-sm">${d.brierOrig != null ? d.brierOrig.toFixed(3).replace(".", ",") : "–"}</td>
      <td class="r hide-sm">${d.bias > 0 ? "+" : ""}${f2(d.bias)}</td></tr>`;
  }).join("");
  const comps = (bt.byComp || []).filter((c) => c.n >= 10).map((c) => `<tr><td>${esc(c.name)}</td><td class="r">${c.n}</td><td class="r ${c.mae <= c.maeLiga ? "best" : ""}">${f2(c.mae)}</td><td class="r">${f2(c.maeLiga)}</td></tr>`).join("");
  const ref = bt.reference;
  const lw = bt.params?.liveWeights || {};
  box.innerHTML = `
    <section class="group verdict ${cls}"><div class="vk">${ece}</div><b>${title}</b><span>${sub} Erro de calibração de ${ece} p.p. em ${bt.calibrationGames} jogos (mínimo ${bt.params?.minCalibGames ?? 300}).</span></section>
    <section class="group"><div class="statgrid">
      <div class="stat"><b>${bt.games}</b><small>jogos avaliados</small></div>
      <div class="stat"><b>${f2(bt.periods?.q1?.mae)}</b><small>erro médio no 1º quarto, pontos</small></div>
      <div class="stat"><b>${bt.duplicatesSkipped ?? 0}</b><small>duplicatas entre fontes ignoradas</small></div>
      <div class="stat"><b>${esc(new Date(bt.updatedAt).toLocaleDateString("pt-BR"))}</b><small>última avaliação</small></div>
    </div></section>
    <section class="group"><div class="group-h"><h3>Erro por período</h3><span>menor é melhor</span></div>
      <div class="tw"><table><thead><tr><th>Período</th><th class="r">Jogos</th><th class="r">Erro v2</th><th class="r">Erro liga</th><th class="r">Erro original</th><th class="r">Brier v2</th><th class="r hide-sm">Brier original</th><th class="r hide-sm">Viés v2</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="hint" style="padding:0 16px 16px">Erro: diferença média, em pontos, entre a projeção e o total real. A coluna do original compara só os jogos em que ele projetava (o número ao lado é o v2 nesses mesmos jogos). Brier mede as chances de Over: 0 é perfeito e 0,25 é o mesmo que chutar 50%. Cada jogo foi previsto só com jogos anteriores a ele.</p></section>
    <div class="split2">
      <section class="group pad"><h3 style="margin:0 0 6px;font-size:15px">Calibração das chances (quartos)</h3>${calibrationSvg(bt.calibration || [])}
        <p class="hint">Cada ponto é uma faixa de chance prevista; quanto mais perto da diagonal, mais confiável o percentual. O tamanho mostra quantos casos há na faixa.</p></section>
      <section class="group"><div class="group-h"><h3>Erro por liga (quartos)</h3><span>ligas com 10+ jogos</span></div>
        <div class="tw"><table><thead><tr><th>Liga</th><th class="r">Jogos</th><th class="r">v2</th><th class="r">Liga</th></tr></thead><tbody>${comps || `<tr><td colspan="4">Sem ligas com amostra suficiente.</td></tr>`}</tbody></table></div></section>
    </div>
    <section class="group pad"><h3 style="margin:0 0 4px;font-size:15px">Como o modelo funciona</h3>
      <p class="hint">Parte da média da liga no período (encolhida para a média global do mesmo gênero quando a liga tem poucos jogos) e soma o desvio de cada equipe na proporção n/(n + ${bt.params?.k_team ?? 4}): com 4 jogos a equipe pesa 50%. A dispersão vem da liga, corrigida pelo que o backtest observou. Ao vivo, o ritmo do jogo pesa ${Math.round((lw["1"] ?? 0.1) * 100)}%, ${Math.round((lw["2"] ?? 0.2) * 100)}% e ${Math.round((lw["3"] ?? 0.3) * 100)}% após o 1º, 2º e 3º quartos.</p>
      ${ref && !ref.error ? `<p class="hint">Referência, modelo original no mesmo dia: ${ref.games} jogos avaliáveis, calibração ${esc(ref.calibrationStatus)}${ref.ece != null ? ` (${(ref.ece * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} p.p.)` : ""}.</p>` : ""}</section>`;
}

function legacyModel(bt, cls, title, sub, ece) {
  const rows = Object.entries(PLABEL).map(([k, l]) => {
    const d = bt.periods?.[k];
    if (!d || !d.n) return "";
    return `<tr><td>${l}</td><td class="r">${d.n}</td><td class="r">${f2(d.maeSimple)}</td><td class="r">${f2(d.bias)}</td><td class="r">${d.brierModel?.toFixed(3).replace(".", ",")}</td><td class="r">${d.brierFreq?.toFixed(3).replace(".", ",")}</td></tr>`;
  }).join("");
  return `<section class="group verdict ${cls}"><div class="vk">${ece}</div><b>${title}</b><span>${sub} Formato antigo do backtest: a próxima coleta completa grava a avaliação do modelo v2.</span></section>
    <section class="group"><div class="tw"><table><thead><tr><th>Período</th><th class="r">Jogos</th><th class="r">Erro</th><th class="r">Viés</th><th class="r">Brier modelo</th><th class="r">Brier frequência</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

// ---------- dados ----------
function renderCoverage(idx, sources) {
  const comps = Object.entries(idx?.competitions || {});
  const teamsAll = comps.flatMap(([, c]) => Object.values(c.teams || {}));
  const ten = teamsAll.filter((t) => t.n >= 10).length;
  const games = Math.round(teamsAll.reduce((s, t) => s + t.n, 0) / 2);
  const rows = comps.sort((x, y) => x[1].name.localeCompare(y[1].name, "pt-BR")).map(([, c]) => {
    const t = Object.values(c.teams || {});
    return `<tr><td>${esc(c.name)}<div class="n">${esc(SRC[c.src || "basketballapi"])}</div></td><td class="r">${t.length}</td><td class="r">${Math.round(t.reduce((s, x) => s + x.n, 0) / 2)}</td><td class="r">${t.filter((x) => x.n >= 10).length}</td></tr>`;
  }).join("");
  const bf = (b) => !b || !Object.keys(b).length ? "ainda não testado" : b.blocked ? "bloqueado pelo plano (o histórico cresce dia a dia)" : `retroagindo, próximo dia ${esc(b.nextDate || "")}`;
  const when = (iso) => (iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "nunca");
  const src = sources.map(({ name, status, backfill, live }) => `<div class="src">
    <div class="src-h"><b>${esc(name)}</b><span>${status?.usedToday ?? "–"} chamadas hoje</span></div>
    <div class="n">Última coleta completa: ${esc(when(status?.lastRun))}</div>
    ${live ? `<div class="n">Placar ao vivo: ${esc(when(live.lastRun))}, plano ${esc(live.plan === "pro" ? "pago" : "gratuito")}, ${live.live ?? 0} jogos em andamento</div>` : ""}
    <div class="n">Histórico retroativo: ${bf(backfill)}</div></div>`).join("");
  $("coverage").innerHTML = `
    <section class="group"><div class="statgrid">
      <div class="stat"><b>${comps.length}</b><small>competições</small></div>
      <div class="stat"><b>${teamsAll.length}</b><small>equipes</small></div>
      <div class="stat"><b>${games}</b><small>jogos com quartos (aprox.)</small></div>
      <div class="stat"><b>${ten}</b><small>equipes com 10+ jogos</small></div>
    </div></section>
    <section class="group"><div class="group-h"><h3>Fontes de dados</h3></div>${src}</section>
    <section class="group"><div class="group-h"><h3>Por competição</h3><span>${comps.length}</span></div><div class="tw"><table>
      <thead><tr><th>Competição</th><th class="r">Equipes</th><th class="r">Jogos</th><th class="r">10+</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4">Sem dados ainda.</td></tr>`}</tbody></table></div></section>`;
}

// ---------- jogos do dia ----------
const localDay = (d) => d.toLocaleDateString("sv-SE");
const teamN = (cid, tid) => index?.competitions?.[cid]?.teams?.[tid]?.n ?? 0;

function setupAgenda() {
  const days = [[-1, "Ontem"], [0, "Hoje"], [1, "Amanhã"]];
  $("chipsDay").innerHTML = days.map(([v, l]) => `<button class="segbtn" role="tab" data-v="${v}">${l}</button>`).join("");
  const sync = () => document.querySelectorAll("#chipsDay .segbtn").forEach((b) => {
    const on = +b.dataset.v === jstate.day;
    b.classList.toggle("on", on); b.setAttribute("aria-selected", String(on));
  });
  sync();
  $("chipsDay").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { jstate.day = +b.dataset.v; sync(); renderAgenda(); } });
  $("jSearch").addEventListener("input", (e) => { jstate.q = e.target.value.trim().toLowerCase(); renderAgenda(); });
  $("jMinN").addEventListener("change", (e) => { jstate.minN = +e.target.value; renderAgenda(); });
  $("jList").addEventListener("click", (e) => {
    const b = e.target.closest(".game"); if (!b) return;
    const g = (agenda?.games || []).find((x) => x.id === b.dataset.id);
    if (g) openMatch(g, LIVE.has(g.st) ? "live" : "vs");
  });
  renderAgenda();
}

function renderAgenda() {
  const out = $("jList");
  if (!agenda || !(agenda.games || []).length) { $("todayCard").innerHTML = ""; out.innerHTML = `<div class="empty">A agenda de jogos aparece após a próxima coleta.</div>`; return; }
  const target = new Date(); target.setDate(target.getDate() + jstate.day);
  const day = localDay(target);
  const ofDay = agenda.games.filter((g) => localDay(new Date(g.t * 1000)) === day);
  renderToday(ofDay, target);
  const q = jstate.q;
  const games = ofDay.filter((g) => (!q || `${g.hn} ${g.an} ${g.ln}`.toLowerCase().includes(q)) && (!jstate.minN || Math.min(teamN(g.lg, g.h), teamN(g.lg, g.a)) >= jstate.minN));
  const meta = games.length === ofDay.length ? "" : `<p class="jmeta">${games.length} de ${ofDay.length} jogos com esses filtros.</p>`;
  if (!games.length) { out.innerHTML = meta + `<div class="empty">Nenhum jogo encontrado com esses filtros.</div>`; return; }
  const leagues = (list) => {
    const groups = new Map();
    for (const g of list) {
      if (!groups.has(g.lg)) groups.set(g.lg, { name: g.ln, tier: g.tier ?? 1, list: [] });
      groups.get(g.lg).list.push(g);
    }
    return [...groups.values()].sort((x, y) => x.tier - y.tier || x.name.localeCompare(y.name, "pt-BR"))
      .map((grp) => `<div class="league-h">${esc(grp.name)}<span>${grp.list.length}</span></div>${grp.list.map(gameRow).join("")}`).join("");
  };
  const parts = [
    ["Ao vivo", games.filter((g) => LIVE.has(g.st))],
    ["Próximos", games.filter((g) => !LIVE.has(g.st) && !DONE.has(g.st) && !OFF[g.st])],
    ["Encerrados", games.filter((g) => DONE.has(g.st)).sort((a, b) => b.t - a.t)],
    ["Adiados e cancelados", games.filter((g) => OFF[g.st])],
  ].filter(([, l]) => l.length);
  out.innerHTML = meta + parts.map(([title, list]) => `<div class="sec-h"><h2>${title}</h2><span>${list.length}</span></div>
    <section class="group" style="margin-top:8px">${leagues(list)}</section>`).join("");
}

function renderToday(ofDay, target) {
  const date = target.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  const live = ofDay.filter((g) => LIVE.has(g.st)).length;
  const done = ofDay.filter((g) => DONE.has(g.st)).length;
  const ready = ofDay.filter((g) => Math.min(teamN(g.lg, g.h), teamN(g.lg, g.a)) >= 3).length;
  const next = ofDay.filter((g) => g.st === "NS" && g.t * 1000 > Date.now()).sort((a, b) => a.t - b.t)[0];
  const upd = agenda.liveAt || agenda.updatedAt;
  $("todayCard").innerHTML = `<div class="d-main"><b>${ofDay.length} jogo${ofDay.length === 1 ? "" : "s"}</b>, ${esc(date)}${next && jstate.day === 0 ? `, próximo às ${hhmm(new Date(next.t * 1000))}` : ""}</div>
    <div class="d-stats">${live ? `<span class="tag live">${live} ao vivo</span>` : ""}<span class="tag">${done} encerrados</span><span class="tag ${ready ? "green" : ""}">${ready} com 3+ jogos de histórico</span></div>
    <div class="d-note">Placares da coleta das ${upd ? hhmm(new Date(upd)) : "–"}; não é tempo real.</div>`;
}

function initials(name) {
  const w = String(name || "?").replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return ((w[0]?.[0] || "?") + (w.length > 1 ? w[w.length - 1][0] : w[0]?.[1] || "")).toUpperCase();
}
function crest(id, name) {
  const url = String(id || "").startsWith("as_tm_") ? `https://media.api-sports.io/basketball/teams/${encodeURIComponent(id.slice(6))}.png` : "";
  return `<span class="crest" aria-hidden="true"><span>${esc(initials(name))}</span>${url ? `<img src="${url}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : ""}</span>`;
}

function gameRow(g) {
  const when = new Date(g.t * 1000);
  let time = `<div class="gtime">${hhmm(when)}</div>`;
  if (LIVE.has(g.st)) time = `<div class="gtime live">${g.st === "HT" ? "Int." : g.st === "BT" ? "Pausa" : g.st}</div>`;
  else if (DONE.has(g.st)) time = `<div class="gtime off">Fim${g.st === "AOT" ? " (prorr.)" : ""}</div>`;
  else if (OFF[g.st]) time = `<div class="gtime off">${OFF[g.st]}</div>`;
  const nh = teamN(g.lg, g.h), na = teamN(g.lg, g.a);
  const hist = (n) => `<span class="hn">${n ? `${n} jogo${n > 1 ? "s" : ""}` : "sem histórico"}</span>`;
  const mn = Math.min(nh, na);
  const cov = mn >= 20 ? ["c20", "20+"] : mn >= 10 ? ["c10", "10+"] : mn >= 5 ? ["c5", "5+"] : ["c0", mn ? `${mn}` : "0"];
  const started = g.hs != null && g.as != null && (LIVE.has(g.st) || DONE.has(g.st));
  const score = started ? `<div class="gscore"><span class="${g.hs >= g.as ? "" : "l"}">${g.hs}</span><span class="${g.as >= g.hs ? "" : "l"}">${g.as}</span></div>` : "";
  const ql = g.hq && (LIVE.has(g.st) || DONE.has(g.st))
    ? `<div class="qline">${g.hq.map((h, i) => (h == null || g.aq[i] == null ? "" : `<span>Q${i + 1} ${h}-${g.aq[i]}</span>`)).join("")}</div>` : "";
  return `<button class="game" data-id="${esc(g.id)}" aria-label="${esc(g.hn)} contra ${esc(g.an)}, abrir ${LIVE.has(g.st) ? "ao vivo" : "confronto"}">
    ${time}
    <div class="gteams"><div>${crest(g.h, g.hn)}<b>${esc(g.hn)}</b>${hist(nh)}</div><div>${crest(g.a, g.an)}<b>${esc(g.an)}</b>${hist(na)}</div></div>
    <div class="gright">${score}<span class="cov ${cov[0]}" title="Menor histórico entre os dois times">${cov[1]}</span></div>${ql}</button>`;
}

function openMatch(g, tab) {
  state.a = g.h; state.b = g.a; state.aName = g.hn; state.bName = g.an; state.compName = g.ln; state.comp = g.lg; state.scope = "comp";
  state.liveId = g.id; manualLive = false;
  for (const v of liveVals) { v.a = ""; v.b = ""; }
  if (index?.competitions?.[g.lg]) {
    $("selComp").value = g.lg;
    refillTeams();
    $("selA").value = g.h; $("selB").value = g.a;
    state.a = g.h; state.b = g.a;
  }
  $("selScope").value = state.scope;
  lastRows = null;
  switchTab(tab || "vs");
  render();
}

// iPhone: esconde a barra fixa enquanto o teclado está aberto.
function setupKeyboardFix() {
  const isField = (el) => el && (el.tagName === "INPUT" || el.tagName === "SELECT" || el.tagName === "TEXTAREA");
  const vv = window.visualViewport;
  const update = () => document.body.classList.toggle("kb", isField(document.activeElement) && !!vv && vv.height < window.innerHeight - 120);
  vv?.addEventListener("resize", update);
  document.addEventListener("focusin", () => setTimeout(update, 250));
  document.addEventListener("focusout", () => setTimeout(() => {
    update();
    if (!isField(document.activeElement)) window.scrollTo(window.scrollX, window.scrollY);
  }, 80));
}

init();
