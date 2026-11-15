import { DEMO, CONFIGURED, getMeta, getTeam } from "./data.js";
import { PERIODS, sample, summarize, overPct, lineGrid, projections, liveProjection, probOver } from "./stats.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const f1 = (x) => (x == null ? "–" : x.toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
const pc = (x) => (x == null ? "–" : Math.round(x) + "%");
const NS = [5, 10, 20];

const state = { comp: null, a: null, b: null, period: "q3", n: 20, venue: "all", scope: "comp" };
let index = null;

try { Object.assign(state, JSON.parse(localStorage.getItem("ba-state") || "{}")); } catch {}
const save = () => { try { localStorage.setItem("ba-state", JSON.stringify(state)); } catch {} };

// ---------- inicialização ----------
async function init() {
  $("demoBanner").hidden = !DEMO;
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => switchTab(t.dataset.tab)));

  if (!CONFIGURED && !DEMO) {
    const n = $("setupNotice");
    n.hidden = false;
    n.innerHTML = "Firebase ainda não configurado. Edite <b>public/js/firebase-config.js</b> ou abra <b>?demo</b> para ver o painel com dados fictícios.";
    $("statusChip").textContent = "sem conexão";
    return;
  }

  try {
    const [idx, s1, b1, s2, b2] = await Promise.all([getMeta("index"), getMeta("status"), getMeta("backfill"),
      getMeta("status_apisports"), getMeta("backfill_apisports")]);
    index = idx;
    const runs = [s1, s2].filter((x) => x && x.lastRun).sort((x, y) => (x.lastRun < y.lastRun ? 1 : -1));
    renderStatusChip(runs[0]);
    renderCoverage(idx, [
      { name: "API-Sports", status: s2, backfill: b2 },
      { name: "Basketball API", status: s1, backfill: b1 },
    ]);
  } catch (e) {
    $("statusChip").textContent = "erro ao ler dados";
    $("result").innerHTML = `<div class="empty">Não foi possível ler o Firestore (${esc(e.message)}). Confira a configuração e as regras.</div>`;
    return;
  }

  if (!index || !Object.keys(index.competitions || {}).length) {
    $("result").innerHTML = `<div class="empty">Ainda não há jogos com placar por quarto armazenados. Rode o coletor e volte em alguns minutos.</div>`;
    buildControls();
    return;
  }
  buildControls();
  render();
}

function switchTab(t) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === t));
  $("tab-vs").hidden = t !== "vs";
  $("tab-live").hidden = t !== "live";
  $("tab-cov").hidden = t !== "cov";
  document.querySelector(".controls").hidden = t === "cov";
  $("fieldPeriod").hidden = t === "live";
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

function buildControls() {
  const comps = index ? compEntries() : [];
  if (!comps.length) return;
  if (!comps.some(([id]) => id === state.comp)) state.comp = comps[0][0];
  fillSelect($("selComp"), comps.map(([id, c]) => [id, c.label]), state.comp);
  refillTeams();

  $("chipsPeriod").innerHTML = PERIODS.map((p) => `<button class="chipbtn" data-v="${p.key}">${p.label}</button>`).join("");
  $("chipsN").innerHTML = NS.map((n) => `<button class="chipbtn" data-v="${n}">${n}</button>`).join("");
  $("selVenue").value = state.venue;
  $("selScope").value = state.scope;
  syncChips();

  $("selComp").addEventListener("change", (e) => { state.comp = e.target.value; refillTeams(true); render(); });
  $("selA").addEventListener("change", (e) => { state.a = e.target.value; render(); });
  $("selB").addEventListener("change", (e) => { state.b = e.target.value; render(); });
  $("selVenue").addEventListener("change", (e) => { state.venue = e.target.value; render(); });
  $("selScope").addEventListener("change", (e) => { state.scope = e.target.value; render(); });
  $("chipsPeriod").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { state.period = b.dataset.v; syncChips(); render(); } });
  $("chipsN").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { state.n = +b.dataset.v; syncChips(); render(); } });
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
async function render() {
  save();
  const my = ++token;
  const [ta, tb] = await Promise.all([getTeam(state.a), getTeam(state.b)]);
  if (my !== token) return;
  if (!ta || !tb) { $("result").innerHTML = `<div class="empty">Equipe sem dados armazenados.</div>`; return; }

  const cid = state.scope === "comp" ? state.comp : null;
  const vA = state.venue === "ah" ? "home" : state.venue === "ha" ? "away" : "all";
  const vB = state.venue === "ah" ? "away" : state.venue === "ha" ? "home" : "all";
  const rowsA = sample(ta.games, { n: state.n, venue: vA, cid });
  const rowsB = sample(tb.games, { n: state.n, venue: vB, cid });
  const A = summarize(rowsA, state.period);
  const B = summarize(rowsB, state.period);
  const P = projections(A, B);
  const label = PERIODS.find((p) => p.key === state.period).label;

  $("result").innerHTML = `<div class="board">
    ${scoreboard(ta, tb, A, B, label)}
    ${projectionCard(A, B, P, label)}
    ${linesCard(A, B, P)}
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

function projectionCard(A, B, P, label) {
  if (P.cruzada == null) return `<div class="card"><h4>Projeção do ${esc(label.toLowerCase())}</h4><div class="empty">Sem amostra suficiente para projetar.</div></div>`;
  return `<div class="card"><h4>Projeção de pontos combinados</h4>
    <div class="proj">
      <div><div class="k">${f1(P.cruzada)}</div><small>Cruzada: ataque de um time com a defesa do outro</small></div>
      <div><div class="k">${f1(P.somaOfensiva)}</div><small>Soma das médias marcadas</small></div>
    </div>
    <p class="hint">Pontos esperados por equipe na projeção cruzada: ${f1(P.pontosA)} e ${f1(P.pontosB)}. Estimativa estatística a partir do histórico, não garante resultado.</p></div>`;
}

function pctCell(v, k) {
  return v == null ? `<div class="pct na"><span>–</span></div>` : `<div class="pct ${k}"><i style="width:${v}%"></i><span>${pc(v)}</span></div>`;
}

function linesCard(A, B, P) {
  const centers = [A.totalAvg, B.totalAvg].filter((x) => x != null);
  if (!centers.length) return "";
  const center = centers.reduce((s, x) => s + x, 0) / centers.length;
  const grid = lineGrid(center, 3);
  const rows = grid.map((line) => {
    const pa = overPct(A.totalSeries, line), pb = overPct(B.totalSeries, line);
    const both = pa != null && pb != null ? (pa + pb) / 2 : null;
    const mid = Math.abs(line - center) < 0.5 ? "mid" : "";
    return `<tr class="${mid}"><td>${line.toLocaleString("pt-BR", { minimumFractionDigits: 1 })}</td>
      <td>${pctCell(pa, "a")}</td><td>${pctCell(pb, "b")}</td><td class="r">${pc(both)}</td></tr>`;
  }).join("");
  return `<div class="card"><h4>Over do total no período (os dois times somados)</h4>
    <table class="lines"><thead><tr><th>Linha</th><th>Jogos de A</th><th>Jogos de B</th><th class="r">Média</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="hint">Percentual dos jogos de cada equipe em que a soma dos pontos dos dois times superou a linha. Desvio padrão do total: A ${f1(A.totalStd)} e B ${f1(B.totalStd)}.</p></div>`;
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
      <text x="${W - 6}" y="11" text-anchor="end">--- média ${f1(S.forAvg)}</text>
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
function renderCoverage(idx, sources) {
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
    <div class="card"><h4>Por competição</h4><div class="tw"><table>
      <thead><tr><th>Competição</th><th class="r">Equipes</th><th class="r">Jogos</th><th class="r">Com 20+</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4">Sem dados ainda.</td></tr>`}</tbody></table></div></div>`;
}

init();


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
  const R = liveProjection(rowsA, rowsB, played);
  if (!R) {
    out.innerHTML = `<div class="empty" style="margin-top:14px">Amostra insuficiente para projetar: cada equipe precisa de pelo menos 2 jogos com placar por quarto nos filtros escolhidos.</div>`;
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
