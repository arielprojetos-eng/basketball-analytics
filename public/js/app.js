import { DEMO, CONFIGURED, getMetas, cachedMetas, getTeam } from "./data.js";
import { PERIODS, sample, summarize, overPct, lineGrid, projections, liveProjection, probOver, shrunkSd, priorFor, centralLine } from "./stats.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f1 = (x) => (x == null ? "–" : x.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
const pc = (x) => (x == null ? "–" : Math.round(x) + "%");
const NS = [5, 10, 20];

const state = { comp: null, a: null, b: null, period: "q3", n: 20, venue: "all", scope: "comp", recency: false };
let index = null;
let agenda = null;
let priors = null;
let backtestRes = null;
const jstate = { day: 0, q: "", minN: 0 };

try { Object.assign(state, JSON.parse(localStorage.getItem("ba-state") || "{}")); } catch {}
const save = () => { try { localStorage.setItem("ba-state", JSON.stringify(state)); } catch {} };

// ---------- inicialização ----------
const META_NAMES = ["index", "status", "backfill", "status_apisports", "backfill_apisports", "agenda", "priors", "backtest"];
const TITLES = { jogos: "Jogos", vs: "Confronto", live: "Ao vivo", cov: "Dados" };
let currentTab = "jogos";
let filtersOpen = false;
let wired = false;

async function init() {
  $("demoBanner").hidden = !DEMO;
  document.querySelectorAll(".dk").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));
  $("btnFilters").addEventListener("click", () => { filtersOpen = !filtersOpen; switchTab(currentTab, true); });
  switchTab("jogos", true);

  if (!CONFIGURED && !DEMO) {
    const n = $("setupNotice");
    n.hidden = false;
    n.innerHTML = "Firebase ainda não configurado. Edite <b>public/js/firebase-config.js</b> ou abra <b>?demo</b> para ver o painel com dados fictícios.";
    $("statusChip").textContent = "sem conexão";
    return;
  }

  // 1) abre na hora com a última versão guardada no aparelho
  const cached = cachedMetas();
  if (cached) {
    applyData(cached);
    $("statusChip").classList.add("syncing");
  }
  // 2) busca a versão atual em uma única requisição
  try {
    applyData(await getMetas(META_NAMES));
  } catch (e) {
    if (!cached) {
      $("statusChip").textContent = "sem conexão";
      $("jList").innerHTML = `<div class="empty">Não foi possível carregar os dados (${esc(e.message)}). Verifique a internet e abra de novo.</div>`;
    } else {
      $("statusChip").textContent = "offline · dados salvos";
    }
  } finally {
    $("statusChip").classList.remove("syncing");
  }
}

function applyData(m) {
  index = m.index;
  agenda = m.agenda;
  priors = m.priors;
  backtestRes = m.backtest;
  const runs = [m.status, m.status_apisports].filter((x) => x && x.lastRun).sort((x, y) => (x.lastRun < y.lastRun ? 1 : -1));
  renderStatusChip(runs[0]);
  renderCoverage(index, backtestRes, [
    { name: "API-Sports", status: m.status_apisports, backfill: m.backfill_apisports },
    { name: "Basketball API", status: m.status, backfill: m.backfill },
  ]);
  if (!wired) { setupAgenda(); wireControls(); wired = true; }
  else renderAgenda();
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
  $("screenTitleText").textContent = TITLES[t];
  for (const [k, id] of [["jogos", "tab-jogos"], ["vs", "tab-vs"], ["live", "tab-live"], ["cov", "tab-cov"]]) {
    const el = $(id);
    el.hidden = k !== t;
    if (k === t && changed && !instant) { el.classList.remove("enter"); void el.offsetWidth; el.classList.add("enter"); }
  }
  const match = t === "vs" || t === "live";
  $("matchBar").hidden = !match;
  $("controlsPanel").hidden = !(match && filtersOpen);
  $("btnFilters").classList.toggle("on", filtersOpen);
  $("btnFilters").setAttribute("aria-expanded", String(filtersOpen));
  $("fieldPeriod").hidden = t === "live";
  if (changed && !instant) window.scrollTo({ top: 0 });
}

function renderStatusChip(s) {
  const chip = $("statusChip");
  if (!s || !s.lastRun) { chip.textContent = "sem coleta"; return; }
  const mins = Math.max(0, Math.round((Date.now() - new Date(s.lastRun).getTime()) / 60000));
  const txt = mins < 90 ? `coleta há ${mins} min` : mins < 2880 ? `coleta há ${Math.round(mins / 60)} h` : `coleta há ${Math.round(mins / 1440)} dias`;
  chip.textContent = txt;
  chip.classList.toggle("ok", mins < 60 * 12);
}

// ---------- controles ----------
const SRC = { apisports: "API-Sports", basketballapi: "Basketball API" };
function compEntries() {
  const list = Object.entries(index?.competitions || {})
    .filter(([, c]) => Object.values(c.teams || {}).some((t) => t.n > 0));
  const count = {};
  list.forEach(([, c]) => { count[c.name] = (count[c.name] || 0) + 1; });
  return list
    .map(([id, c]) => [id, { ...c, label: count[c.name] > 1 ? `${c.name} · ${SRC[c.src || "basketballapi"]}` : c.name }])
    .sort((x, y) => x[1].label.localeCompare(y[1].label, "pt-BR"));
}

function teamOptions(cid) {
  const t = index.competitions[cid]?.teams || {};
  return Object.entries(t).sort((x, y) => x[1].name.localeCompare(y[1].name, "pt-BR"));
}

function fillSelect(sel, items, current, label) {
  sel.innerHTML = items.map(([id, name]) => `<option value="${esc(id)}">${esc(label ? label(id, name) : name)}</option>`).join("");
  if (items.some(([id]) => id === current)) sel.value = current;
  return sel.value;
}

function fillControls() {
  const comps = index ? compEntries() : [];
  if (!comps.length) return;
  if (!comps.some(([id]) => id === state.comp)) state.comp = comps[0][0];
  fillSelect($("selComp"), comps.map(([id, c]) => [id, c.label]), state.comp);
  const keepA = state.a, keepB = state.b;
  refillTeams();
  // equipes vindas da tela de jogos podem não estar na lista: mantém a escolha
  if (keepA && state.a !== keepA && state.aName) state.a = keepA;
  if (keepB && state.b !== keepB && state.bName) state.b = keepB;
  $("selVenue").value = state.venue;
  $("selScope").value = state.scope;
  $("selRecency").value = state.recency ? "1" : "0";
  syncChips();
}

function wireControls() {
  $("chipsPeriod").innerHTML = PERIODS.map((p) => `<button class="chipbtn" data-v="${p.key}">${p.label}</button>`).join("");
  $("chipsN").innerHTML = NS.map((n) => `<button class="chipbtn" data-v="${n}">${n}</button>`).join("");
  $("selRecency").addEventListener("change", (e) => { state.recency = e.target.value === "1"; render(); });
  $("selComp").addEventListener("change", (e) => { state.comp = e.target.value; state.aName = state.bName = null; refillTeams(true); render(); });
  $("selA").addEventListener("change", (e) => { state.a = e.target.value; state.aName = null; render(); });
  $("selB").addEventListener("change", (e) => { state.b = e.target.value; state.bName = null; render(); });
  $("selVenue").addEventListener("change", (e) => { state.venue = e.target.value; render(); });
  $("selScope").addEventListener("change", (e) => { state.scope = e.target.value; render(); });
  $("chipsPeriod").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { state.period = b.dataset.v; syncChips(); render(); } });
  $("chipsN").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { state.n = +b.dataset.v; syncChips(); render(); } });
  syncChips();
}

function refillTeams(reset) {
  const opts = teamOptions(state.comp);
  const label = (id, t) => `${t.name} (${t.n})`;
  const items = opts.map(([id, t]) => [id, t]);
  const mk = (sel, cur) => {
    sel.innerHTML = items.map(([id, t]) => `<option value="${esc(id)}">${esc(label(id, t))}</option>`).join("");
    if (!reset && items.some(([id]) => id === cur)) sel.value = cur;
    return sel.value;
  };
  state.a = mk($("selA"), state.a);
  state.b = mk($("selB"), state.b);
  if (state.a === state.b && items.length > 1) { $("selB").selectedIndex = Math.min(1, items.length - 1); state.b = $("selB").value; }
}

function syncChips() {
  document.querySelectorAll("#chipsPeriod .chipbtn").forEach((b) => b.classList.toggle("on", b.dataset.v === state.period));
  document.querySelectorAll("#chipsN .chipbtn").forEach((b) => b.classList.toggle("on", +b.dataset.v === state.n));
}

// ---------- render ----------
let token = 0;
let lastRows = null;
const liveVals = [{ a: "", b: "" }, { a: "", b: "" }, { a: "", b: "" }];
function setMatchBar(ta, tb) {
  const comp = index?.competitions?.[state.comp];
  $("mbComp").textContent = comp?.name || state.compName || "";
  $("mbA").textContent = ta?.name || state.aName || "Equipe A";
  $("mbB").textContent = tb?.name || state.bName || "Equipe B";
}

async function render() {
  save();
  const my = ++token;
  setMatchBar(null, null);
  let ta, tb;
  try {
    [ta, tb] = await Promise.all([getTeam(state.a), getTeam(state.b)]);
  } catch (e) {
    if (my === token) $("result").innerHTML = `<div class="empty">Sem conexão para carregar as equipes (${esc(e.message)}).</div>`;
    return;
  }
  if (my !== token) return;
  setMatchBar(ta, tb);
  if (!ta || !tb) {
    const miss = [!ta && (state.aName || "Equipe A"), !tb && (state.bName || "Equipe B")].filter(Boolean).join(" e ");
    $("result").innerHTML = `<div class="empty">${esc(miss)} ainda sem jogos com placar por quarto armazenados. O histórico cresce a cada coleta.</div>`;
    lastRows = null;
    $("liveResult").innerHTML = "";
    return;
  }

  const cid = state.scope === "comp" ? state.comp : null;
  const vA = state.venue === "ah" ? "home" : state.venue === "ha" ? "away" : "all";
  const vB = state.venue === "ah" ? "away" : state.venue === "ha" ? "home" : "all";
  const rowsA = sample(ta.games, { n: state.n, venue: vA, cid });
  const rowsB = sample(tb.games, { n: state.n, venue: vB, cid });
  const A = summarize(rowsA, state.period, state.recency);
  const B = summarize(rowsB, state.period, state.recency);
  const P = projections(A, B);
  const label = PERIODS.find((p) => p.key === state.period).label;
  const sd = shrunkSd(A, B, priorFor(priors, state.comp, state.period));
  const warn = Math.min(A.n, B.n) < 5
    ? `<div class="alert">Amostra pequena (${Math.min(A.n, B.n)} jogo${Math.min(A.n, B.n) === 1 ? "" : "s"} na equipe com menos dados). Os números indicam tendência, não confiabilidade.</div>` : "";

  $("result").innerHTML = `<div class="board">
    ${warn}
    ${projectionCard(A, B, P, label, sd)}
    ${linesCard(A, B, P, sd)}
    ${scoreboard(ta, tb, A, B, label)}
    <div class="charts">
      ${chartCard(ta.name, rowsA, A, "a", label)}
      ${chartCard(tb.name, rowsB, B, "b", label)}
    </div>
    ${gamesCard(ta.name, rowsA, "a")}
    ${gamesCard(tb.name, rowsB, "b")}
  </div>`;
  lastRows = { ta, tb, rowsA, rowsB };
  renderLive();
}

function nBadge(sum) {
  const cls = sum.n >= state.n ? "" : sum.n < 5 ? "bad" : "warn";
  const txt = sum.n === 0 ? "nenhum jogo na amostra" : sum.n >= state.n ? `${sum.n} jogos analisados` : `${sum.n} jogos (pedido: ${state.n})`;
  return `<div class="n ${cls}">${txt}</div>`;
}

function scoreboard(ta, tb, A, B, label) {
  const side = (t, S, k) => `<div class="side ${k}">
      <h3>${esc(t.name)}</h3>${nBadge(S)}
      <div class="big">${f1(S.forAvg)}<small>marcados no ${esc(label.toLowerCase())}</small></div>
      <div class="mini">
        <div>${f1(S.againstAvg)}<small>sofridos</small></div>
        <div>${f1(S.totalAvg)}<small>soma no jogo</small></div>
      </div></div>`;
  return `<div class="score">${side(ta, A, "a")}${side(tb, B, "b")}</div>`;
}

function projectionCard(A, B, P, label, sd) {
  if (P.cruzada == null) return `<div class="card"><h4>Projeção do ${esc(label.toLowerCase())}</h4><div class="empty">Sem amostra suficiente para projetar.</div></div>`;
  const z = 1.2816; // faixa de 80%
  const lo = P.cruzada - z * sd, hi = P.cruzada + z * sd;
  return `<div class="card hero"><h4>Projeção do ${esc(label.toLowerCase())} · os dois times</h4>
    <div class="hero-k">${f1(P.cruzada)}</div>
    <div class="hero-range">Faixa provável (80%): <b>${f1(lo)}</b> a <b>${f1(hi)}</b></div>
    <div class="hero-sub">
      <div><b>${f1(P.pontosA)}</b><small>esperado para A</small></div>
      <div><b>${f1(P.pontosB)}</b><small>esperado para B</small></div>
      <div><b>${f1(P.somaOfensiva)}</b><small>soma das médias marcadas</small></div>
    </div>
    <p class="hint">Projeção cruzada: ataque de cada time combinado com a defesa do adversário${state.recency ? ", com mais peso aos jogos recentes" : ""}. Estimativa estatística, não garante resultado.</p></div>`;
}

function pctCell(v, k) {
  return v == null ? `<div class="pct na"><span>–</span></div>` : `<div class="pct ${k}"><i style="width:${v}%"></i><span>${pc(v)}</span></div>`;
}

function linesCard(A, B, P, sd) {
  if (P.cruzada == null) return "";
  const center = centralLine(P.cruzada);
  const rows = lineGrid(P.cruzada, 3).map((line) => {
    const pm = probOver(P.cruzada, sd, line);
    const pa = overPct(A.totalSeries, line), pb = overPct(B.totalSeries, line);
    const mid = line === center ? "mid" : "";
    return `<tr class="${mid}"><td>${line.toLocaleString("pt-BR", { minimumFractionDigits: 1 })}</td>
      <td>${pctCell(pm, "m")}</td><td class="r freq">${pc(pa)}</td><td class="r freq">${pc(pb)}</td></tr>`;
  }).join("");
  return `<div class="card"><h4>Over do total no período</h4>
    <div class="tw"><table class="lines"><thead><tr><th>Linha</th><th>Chance estimada</th><th class="r">Jogos de A</th><th class="r">Jogos de B</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <p class="hint"><b>Chance estimada</b>: curva normal centrada na projeção (linha destacada), com dispersão de ${f1(sd)} pontos, ajustada para o padrão da liga quando há poucos jogos. <b>Jogos de A/B</b>: frequência histórica, ou seja, em quantos jogos de cada equipe a soma passou da linha. Frequência não é probabilidade, e a aba Dados mostra qual das duas acerta mais.</p></div>`;
}

function chartCard(name, rows, S, k, label) {
  const chrono = [...rows].reverse();
  const vals = S.forSeries.slice().reverse();
  if (!vals.length) return `<div class="card chart"><h4>${esc(name)}</h4><div class="empty">Sem jogos.</div></div>`;
  const W = 340, H = 136, padT = 22, padB = 22, bw = Math.min(26, (W - 20) / vals.length - 4);
  const max = Math.max(...vals, S.forAvg) * 1.12, min = 0;
  const x = (i) => 10 + i * ((W - 20) / vals.length) + ((W - 20) / vals.length - bw) / 2;
  const y = (v) => padT + (H - padT - padB) * (1 - (v - min) / (max - min));
  const color = k === "a" ? "var(--a)" : "var(--b)";
  const bars = vals.map((v, i) => `<rect x="${x(i).toFixed(1)}" y="${y(v).toFixed(1)}" width="${bw.toFixed(1)}" height="${(H - padB - y(v)).toFixed(1)}" rx="2" fill="${color}" opacity=".85"/>
    ${vals.length <= 12 ? `<text class="val" x="${(x(i) + bw / 2).toFixed(1)}" y="${(y(v) - 4).toFixed(1)}" text-anchor="middle">${v}</text>` : ""}`).join("");
  const ay = y(S.forAvg).toFixed(1);
  return `<div class="card chart"><h4>${esc(name)}</h4>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Pontos marcados no ${esc(label.toLowerCase())} nos últimos ${vals.length} jogos de ${esc(name)}">
      ${bars}
      <line x1="6" x2="${W - 6}" y1="${ay}" y2="${ay}" stroke="var(--text)" stroke-dasharray="4 4" opacity=".7"/>
      <text x="${W - 6}" y="11" text-anchor="end">--- ${state.recency ? "média ponderada" : "média"} ${f1(S.forAvg)}</text>
      <text x="10" y="${H - 6}">${esc(chrono[0]?.date.slice(5).split("-").reverse().join("/") || "")}</text>
      <text x="${W - 10}" y="${H - 6}" text-anchor="end">${esc(chrono.at(-1)?.date.slice(5).split("-").reverse().join("/") || "")}</text>
    </svg>
    <p class="hint">Pontos marcados no ${esc(label.toLowerCase())}, do jogo mais antigo ao mais recente.</p></div>`;
}

function gamesCard(name, rows, k) {
  if (!rows.length) return "";
  const key = state.period;
  const body = rows.map((e) => {
    const own = e.pts, opp = e.oppPts;
    const pv = (arr, ot) => ({ q1: arr[0], q2: arr[1], q3: arr[2], q4: arr[3], h1: arr[0] + arr[1], h2: arr[2] + arr[3],
      reg: arr.reduce((s, x) => s + x, 0), total: arr.reduce((s, x) => s + x, 0) + (ot || 0) }[key]);
    const m = pv(own, e.ot), o = pv(opp, e.oppOt);
    const d = e.date.split("-").reverse().slice(0, 2).join("/");
    return `<tr><td>${d}</td><td>${e.home ? "casa" : "fora"}</td><td>${esc(e.oppName)}</td>
      <td class="r"><b>${m}</b> x ${o}</td><td class="r">${m + o}</td></tr>`;
  }).join("");
  return `<details><summary style="color:var(--${k === "a" ? "a" : "b"})">Jogos de ${esc(name)}</summary><div class="tw">
    <table class="glist"><thead><tr><th>Data</th><th>Mando</th><th>Adversário</th><th class="r">Marc. x sof.</th><th class="r">Total</th></tr></thead>
    <tbody>${body}</tbody></table></div></details>`;
}

// ---------- cobertura ----------
function renderCoverage(idx, bt, sources) {
  const comps = Object.entries(idx?.competitions || {});
  const teamsAll = comps.flatMap(([, c]) => Object.values(c.teams || {}));
  const ready = teamsAll.filter((t) => t.n >= 20).length;
  const rows = comps.sort((x, y) => x[1].name.localeCompare(y[1].name, "pt-BR")).map(([, c]) => {
    const t = Object.values(c.teams || {});
    const games = Math.round(t.reduce((s, x) => s + x.n, 0) / 2);
    const full = t.filter((x) => x.n >= 20).length;
    return `<tr><td>${esc(c.name)}<div class="n">${esc(SRC[c.src || "basketballapi"])}</div></td><td class="r">${t.length}</td><td class="r">${games}</td><td class="r">${full}</td></tr>`;
  }).join("");
  const bfText = (b) => !b || !Object.keys(b).length ? "ainda não testado"
    : b.blocked ? "bloqueado pelo plano gratuito (acumula dia a dia)" : `retroagindo, próximo dia ${esc(b.nextDate || "")}`;
  const srcRows = sources.map(({ name, status, backfill }) => `<div class="src">
    <div class="src-h"><b>${esc(name)}</b><span>${status?.usedToday ?? "–"} de 100 chamadas hoje</span></div>
    <div class="n">Última coleta: ${status?.lastRun ? esc(new Date(status.lastRun).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })) : "nunca"}</div>
    <div class="n">Histórico retroativo: ${bfText(backfill)}</div></div>`).join("");
  const pending = sources.find((x) => x.name === "Basketball API")?.status?.pending;
  $("coverage").innerHTML = `
    <div class="covgrid">
      <div class="stat"><b>${comps.length}</b><small>competições com dados</small></div>
      <div class="stat"><b>${teamsAll.length}</b><small>equipes</small></div>
      <div class="stat"><b>${ready}</b><small>equipes com 20 jogos ou mais</small></div>
      <div class="stat"><b>${pending ?? "–"}</b><small>jogos na fila (Basketball API)</small></div>
    </div>
    <div class="card" style="margin-bottom:14px"><h4>Fontes de dados</h4>${srcRows}</div>
    ${precisionCard(bt)}
    <div class="card"><h4>Por competição</h4><div class="tw"><table>
      <thead><tr><th>Competição</th><th class="r">Equipes</th><th class="r">Jogos</th><th class="r">Com 20+</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4">Sem dados ainda.</td></tr>`}</tbody></table></div></div>`;
}



// ---------- ao vivo ----------
function renderLive() {
  if (!lastRows) return;
  const { ta, tb, rowsA, rowsB } = lastRows;
  const form = $("liveForm");
  const typing = form.contains(document.activeElement) && form.dataset.a === ta.name && form.dataset.b === tb.name;
  if (!typing) {
    form.dataset.a = ta.name; form.dataset.b = tb.name;
    form.innerHTML = `<div class="live-head"><span class="a">${esc(ta.name)}</span><span class="b">${esc(tb.name)}</span></div>` +
      liveVals.map((v, i) => `<div class="live-row"><label for="la${i}">${i + 1}º quarto</label>
        <input id="la${i}" data-i="${i}" data-s="a" class="sc a" type="number" inputmode="numeric" min="0" max="99" placeholder="A" value="${esc(v.a)}">
        <input id="lb${i}" data-i="${i}" data-s="b" class="sc b" type="number" inputmode="numeric" min="0" max="99" placeholder="B" value="${esc(v.b)}"></div>`).join("") +
      `<p class="hint" style="margin:10px 0 0">Preencha os quartos já encerrados, em ordem. A projeção usa a amostra e os filtros acima.</p>`;
    form.oninput = (e) => {
      const el = e.target.closest("input"); if (!el) return;
      liveVals[+el.dataset.i][el.dataset.s] = el.value;
      renderLiveResult();
    };
  }
  renderLiveResult();
}

function renderLiveResult() {
  const out = $("liveResult");
  const { ta, tb, rowsA, rowsB } = lastRows;
  const played = [];
  for (const v of liveVals) {
    const a = v.a === "" ? NaN : Number(v.a), b = v.b === "" ? NaN : Number(v.b);
    if (!Number.isInteger(a) || !Number.isInteger(b) || a < 0 || b < 0) break;
    played.push({ a, b });
  }
  if (!played.length) { out.innerHTML = `<div class="empty" style="margin-top:14px">Informe o placar do 1º quarto (os dois times) para ver a projeção.</div>`; return; }
  const R = liveProjection(rowsA, rowsB, played, { recency: state.recency, priors, cid: state.comp });
  if (!R) {
    out.innerHTML = `<div class="empty" style="margin-top:14px">Amostra insuficiente para projetar: cada equipe precisa de pelo menos 1 jogo com placar por quarto nos filtros escolhidos.</div>`;
    return;
  }
  const dev = (R.pace - 1) * 100;
  const sign = (x) => (x >= 0 ? "+" : "") + x.toLocaleString("pt-BR", { maximumFractionDigits: 0 }) + "%";
  const qrows = R.rest.map((q) => `<tr><td>${q.quarter}º quarto</td>
    <td class="r">${f1(q.a)}</td><td class="r">${f1(q.b)}</td><td class="r"><b>${f1(q.total)}</b> <span class="n">±${f1(q.sd)}</span></td></tr>`).join("");
  const lineRows = (mean, sd, center) => lineGrid(center, 3).map((line) => {
    const p = probOver(mean, sd, line);
    const mid = Math.abs(line - center) < 0.5 ? "mid" : "";
    return `<tr class="${mid}"><td>${line.toLocaleString("pt-BR", { minimumFractionDigits: 1 })}</td><td>${pctCell(p, "a")}</td></tr>`;
  }).join("");
  const nq = R.nextQuarter;
  out.innerHTML = `<div class="board" style="margin-top:14px">
    <div class="score">
      <div class="side a"><h3>${esc(ta.name)}</h3><div class="n">${played.reduce((s, q) => s + q.a, 0)} pts até agora</div>
        <div class="big">${f1(R.finalA)}<small>projeção final</small></div></div>
      <div class="side b"><h3>${esc(tb.name)}</h3><div class="n">${played.reduce((s, q) => s + q.b, 0)} pts até agora</div>
        <div class="big">${f1(R.finalB)}<small>projeção final</small></div></div>
    </div>
    <div class="card"><h4>Total final projetado</h4>
      <div class="proj"><div><div class="k">${f1(R.finalTotal)}</div><small>pontos somados, tempo regulamentar</small></div>
      <div><div class="k">${sign(dev)}</div><small>ritmo do jogo vs. esperado ${played.length === 1 ? "no quarto jogado" : `nos ${played.length} quartos jogados`}</small></div></div>
      <div class="delta">Projeção pré-jogo: <b>${f1(R.pregameTotal)}</b> → agora: <b>${f1(R.finalTotal)}</b> (${R.finalTotal - R.pregameTotal >= 0 ? "+" : ""}${f1(R.finalTotal - R.pregameTotal)})</div>
      <p class="hint">O ritmo observado entra com peso de ${Math.round(R.weight * 100)}% (o restante vem do histórico das equipes), porque o que acontece num quarto prevê pouco o seguinte. Faixas "±" são o desvio padrão do total de cada quarto.</p></div>
    <div class="card"><h4>Quartos restantes</h4><div class="tw"><table>
      <thead><tr><th>Quarto</th><th class="r">${esc(ta.name)}</th><th class="r">${esc(tb.name)}</th><th class="r">Total</th></tr></thead>
      <tbody>${qrows}</tbody></table></div></div>
    <div class="card"><h4>Over do ${nq.quarter}º quarto (total dos dois times)</h4>
      <table class="lines"><thead><tr><th>Linha</th><th>Chance estimada</th></tr></thead><tbody>${lineRows(nq.total, nq.sd, nq.total)}</tbody></table></div>
    <div class="card"><h4>Over do total final</h4>
      <table class="lines"><thead><tr><th>Linha</th><th>Chance estimada</th></tr></thead><tbody>${lineRows(R.finalTotal, R.sdFinal, R.finalTotal)}</tbody></table>
      <p class="hint">Probabilidade pela curva normal, com a incerteza dos quartos que faltam. Prorrogação não entra. É uma estimativa estatística e pode errar, sobretudo com poucos jogos na amostra.</p></div>
  </div>`;
}


// ---------- precisão do modelo (backtest) ----------
const PLABEL = { q1: "1º quarto", q2: "2º quarto", q3: "3º quarto", q4: "4º quarto", h1: "1º tempo", h2: "2º tempo", reg: "Jogo (regulamentar)" };

function precisionCard(bt) {
  const head = `<div class="card" style="margin-bottom:14px"><h4>Precisão do modelo (backtest)</h4>`;
  if (!bt || !bt.games) {
    return head + `<p class="hint" style="margin:0">Ainda sem jogos suficientes para avaliar. O teste roda uma vez por dia e só avalia jogos em que as duas equipes já tinham pelo menos ${bt?.params?.minPrior ?? 3} jogos anteriores na mesma liga. Com o histórico crescendo dia a dia, os primeiros números aparecem em alguns dias.</p></div>`;
  }
  const rows = Object.entries(PLABEL).map(([k, l]) => {
    const d = bt.periods?.[k];
    if (!d || !d.n) return `<div class="prow"><div class="pl">${l}</div><div class="ps"><span>sem jogos avaliados</span></div></div>`;
    const recBetter = d.maeRecency < d.maeSimple;
    const bm = d.brierModel <= d.brierFreq;
    const st = (v, lab, best) => `<span class="${best ? "best" : ""}"><b>${v}</b>${lab}</span>`;
    return `<div class="prow"><div class="pl">${l}<em>${d.n} jogos</em></div><div class="ps">
      ${st(f1(d.maeSimple), "erro simples", !recBetter)}${st(f1(d.maeRecency), "erro recência", recBetter)}
      ${st((d.bias > 0 ? "+" : "") + f1(d.bias), "viés", false)}
      ${st(d.brierModel.toFixed(3).replace(".", ","), "Brier modelo", bm)}${st(d.brierFreq.toFixed(3).replace(".", ","), "Brier frequência", !bm)}
    </div></div>`;
  }).join("");
  const cal = (bt.calibration || []).filter((c) => c.n).map((c) =>
    `<tr><td>${Math.round(c.lo * 100)}–${Math.round(c.hi * 100)}%</td><td class="r">${c.n}</td><td class="r">${pc(c.p * 100)}</td><td class="r">${pc(c.freq * 100)}</td></tr>`).join("");
  const comps = (bt.byComp || []).map((c) => `<tr><td>${esc(c.name)}</td><td class="r">${c.n}</td><td class="r">${f1(c.mae)}</td></tr>`).join("");
  return head + `<p class="hint" style="margin:0 0 10px">${bt.games} jogos avaliados. Cada projeção usou só os jogos anteriores ao jogo avaliado (últimos ${bt.params.lastN}, mesma liga). Atualizado em ${esc(new Date(bt.updatedAt).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }))}.</p>
    <div class="plist">${rows}</div>
    <p class="hint"><b>Erro médio</b>: diferença média, em pontos, entre a projeção e o total real (menor é melhor; o melhor método de cada linha fica em verde). <b>Viés</b> positivo indica que o modelo projeta acima do real. <b>Brier</b> mede a qualidade das chances de Over (0 é perfeito; 0,25 equivale a chutar 50%) e compara a chance estimada do modelo com a frequência histórica.</p>
    ${cal ? `<h4 style="margin-top:14px">Calibração das chances</h4><div class="tw"><table><thead><tr><th>Faixa prevista</th><th class="r">Casos</th><th class="r">Média prevista</th><th class="r">Aconteceu</th></tr></thead><tbody>${cal}</tbody></table></div>
    <p class="hint">Bem calibrado é quando "Média prevista" e "Aconteceu" ficam próximas.</p>` : ""}
    ${comps ? `<h4 style="margin-top:14px">Erro por liga (quartos)</h4><div class="tw"><table><thead><tr><th>Liga</th><th class="r">Jogos</th><th class="r">Erro médio</th></tr></thead><tbody>${comps}</tbody></table></div>` : ""}
  </div>`;
}

// ---------- jogos do dia ----------
const LIVE = new Set(["Q1", "Q2", "Q3", "Q4", "OT", "BT", "HT"]);
const DONE = new Set(["FT", "AOT"]);
const OFF = { POST: "Adiado", CANC: "Cancel.", SUSP: "Suspenso", AWD: "W.O.", ABD: "Abandon." };
const localDay = (d) => d.toLocaleDateString("sv-SE"); // AAAA-MM-DD no fuso do aparelho

function teamN(cid, tid) {
  return index?.competitions?.[cid]?.teams?.[tid]?.n ?? 0;
}

function setupAgenda() {
  const days = [[-1, "Ontem"], [0, "Hoje"], [1, "Amanhã"]];
  $("chipsDay").innerHTML = days.map(([v, l]) => `<button class="segbtn" role="tab" data-v="${v}">${l}</button>`).join("");
  const sync = () => document.querySelectorAll("#chipsDay .segbtn").forEach((b) => {
    const on = +b.dataset.v === jstate.day;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", String(on));
  });
  sync();
  $("chipsDay").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { jstate.day = +b.dataset.v; sync(); renderAgenda(); } });
  $("jSearch").addEventListener("input", (e) => { jstate.q = e.target.value.trim().toLowerCase(); renderAgenda(); });
  $("jMinN").addEventListener("change", (e) => { jstate.minN = +e.target.value; renderAgenda(); });
  $("jList").addEventListener("click", (e) => {
    const b = e.target.closest(".game");
    if (!b) return;
    const g = (agenda?.games || []).find((x) => x.id === b.dataset.id);
    if (g) openMatch(g);
  });
  renderAgenda();
}

function renderAgenda() {
  const out = $("jList");
  if (!agenda || !(agenda.games || []).length) {
    $("todayCard").innerHTML = "";
    out.innerHTML = `<div class="empty">A agenda de jogos aparece após a próxima coleta.</div>`;
    return;
  }
  const target = new Date(); target.setDate(target.getDate() + jstate.day);
  const day = localDay(target);
  const q = jstate.q;
  const ofDay = agenda.games.filter((g) => localDay(new Date(g.t * 1000)) === day);
  renderToday(ofDay, target);
  const games = ofDay.filter((g) => {
    if (q && !`${g.hn} ${g.an} ${g.ln}`.toLowerCase().includes(q)) return false;
    if (jstate.minN && Math.min(teamN(g.lg, g.h), teamN(g.lg, g.a)) < jstate.minN) return false;
    return true;
  });
  const meta = games.length === ofDay.length ? "" : `<p class="jmeta">${games.length} de ${ofDay.length} jogos com esses filtros.</p>`;
  if (!games.length) { out.innerHTML = meta + `<div class="empty">Nenhum jogo encontrado com esses filtros.</div>`; return; }

  const groups = new Map();
  for (const g of games) {
    if (!groups.has(g.lg)) groups.set(g.lg, { name: g.ln, tier: g.tier ?? 1, list: [] });
    groups.get(g.lg).list.push(g);
  }
  const ordered = [...groups.values()].sort((x, y) => x.tier - y.tier || x.name.localeCompare(y.name, "pt-BR"));
  out.innerHTML = meta + ordered.map((grp) => `<div class="league"><h4>${esc(grp.name)}<span>${grp.list.length}</span></h4>${
    grp.list.map(gameRow).join("")}</div>`).join("");
}

function renderToday(ofDay, target) {
  const label = ["Ontem", "Hoje", "Amanhã"][jstate.day + 1];
  const date = target.toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  const live = ofDay.filter((g) => LIVE.has(g.st)).length;
  const done = ofDay.filter((g) => DONE.has(g.st)).length;
  const ready = ofDay.filter((g) => Math.min(teamN(g.lg, g.h), teamN(g.lg, g.a)) >= 5).length;
  const next = ofDay.filter((g) => g.st === "NS" && g.t * 1000 > Date.now()).sort((a, b) => a.t - b.t)[0];
  const upd = agenda.updatedAt ? new Date(agenda.updatedAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "–";
  const stat = (v, l, cls = "") => `<div class="ts ${cls}"><b>${v}</b><span>${l}</span></div>`;
  $("todayCard").innerHTML = `
    <div class="td-head"><span class="td-day">${label}</span><span class="td-date">${esc(date)}</span></div>
    <div class="td-main"><b>${ofDay.length}</b><span>jogo${ofDay.length === 1 ? "" : "s"}${next && jstate.day === 0 ? ` · próximo às ${new Date(next.t * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}` : ""}</span></div>
    <div class="td-stats">
      ${stat(live, "ao vivo", live ? "live" : "")}${stat(done, "encerrados")}${stat(ready, "com 5+ jogos de histórico", ready ? "ready" : "")}
    </div>
    <p class="td-note">Placares atualizados na coleta das ${esc(upd)}; não é tempo real.</p>`;
}

function gameRow(g) {
  const when = new Date(g.t * 1000);
  let time = `<div class="gtime">${when.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}</div>`;
  if (LIVE.has(g.st)) time = `<div class="gtime live">${g.st === "HT" ? "Interv." : g.st}</div>`;
  else if (DONE.has(g.st)) time = `<div class="gtime off">Fim${g.st === "AOT" ? " (prorr.)" : ""}</div>`;
  else if (OFF[g.st]) time = `<div class="gtime off">${OFF[g.st]}</div>`;
  const nh = teamN(g.lg, g.h), na = teamN(g.lg, g.a);
  const hist = (n) => `<span class="hn ${n ? "ok" : ""}">${n ? n + " jogo" + (n > 1 ? "s" : "") : "sem histórico"}</span>`;
  const mn = Math.min(nh, na);
  const cov = mn >= 20 ? ["c20", "20+"] : mn >= 10 ? ["c10", "10+"] : mn >= 5 ? ["c5", "5+"] : ["c0", mn ? "<5" : "–"];
  const started = g.hs != null && g.as != null && (LIVE.has(g.st) || DONE.has(g.st));
  const score = started ? `<div class="gscore"><span class="${g.hs >= g.as ? "w" : "l"}">${g.hs}</span><span class="${g.as >= g.hs ? "w" : "l"}">${g.as}</span></div>` : "<div></div>";
  return `<button class="game" data-id="${esc(g.id)}" aria-label="${esc(g.hn)} contra ${esc(g.an)}, ver histórico">
    ${time}
    <div class="gteams"><div><b>${esc(g.hn)}</b>${hist(nh)}</div><div><b>${esc(g.an)}</b>${hist(na)}</div></div>
    <div class="gright">${score}<span class="cov ${cov[0]}" title="Menor histórico entre os dois times">${cov[1]}</span></div></button>`;
}

function openMatch(g) {
  const inIndex = !!index?.competitions?.[g.lg];
  state.a = g.h; state.b = g.a; state.aName = g.hn; state.bName = g.an; state.compName = g.ln;
  if (inIndex) {
    state.comp = g.lg;
    state.scope = "comp";
    $("selComp").value = g.lg;
    refillTeams();
    // equipes ainda fora do índice continuam selecionadas pelo id, mesmo sem opção na lista
    $("selA").value = g.h; $("selB").value = g.a;
    state.a = g.h; state.b = g.a;
  }
  $("selScope").value = state.scope;
  switchTab("vs");
  render();
}

// Inicia só depois de todo o módulo carregado (a abertura com dados guardados é síncrona).
init();
