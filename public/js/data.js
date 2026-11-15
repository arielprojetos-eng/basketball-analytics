// Camada de dados: Firestore via REST (produção) ou dados fictícios (?demo).
// Sem o SDK do Firebase: uma requisição traz todos os documentos gerais, e a última versão
// fica guardada no aparelho para o app abrir na hora, atualizando em segundo plano.
import { firebaseConfig } from "./firebase-config.js";

export const DEMO = new URLSearchParams(location.search).has("demo");
export const CONFIGURED = !String(firebaseConfig.projectId).startsWith("SEU-");

const PID = firebaseConfig.projectId;
const DB = `projects/${PID}/databases/(default)/documents`;
const API = `https://firestore.googleapis.com/v1/${DB}`;
const KEY = `key=${encodeURIComponent(firebaseConfig.apiKey)}`;
const META_CACHE = "ba-meta-v1";
const TEAM_CACHE = "ba-teams-v1";
const TEAM_CACHE_MAX = 30;

// ---------- conversão do formato tipado do Firestore REST ----------
export function fromValue(v) {
  if (v == null) return null;
  if ("stringValue" in v) return v.stringValue;
  if ("integerValue" in v) return Number(v.integerValue);
  if ("doubleValue" in v) return Number(v.doubleValue);
  if ("booleanValue" in v) return v.booleanValue;
  if ("nullValue" in v) return null;
  if ("timestampValue" in v) return v.timestampValue;
  if ("mapValue" in v) return fromFields(v.mapValue.fields || {});
  if ("arrayValue" in v) return (v.arrayValue.values || []).map(fromValue);
  return null;
}

export function fromFields(fields) {
  const out = {};
  for (const [k, v] of Object.entries(fields || {})) out[k] = fromValue(v);
  return out;
}

async function request(url, opts = {}, ms = 15000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { ...opts, signal: ctl.signal });
    return r;
  } finally {
    clearTimeout(timer);
  }
}

const read = (k) => { try { return JSON.parse(localStorage.getItem(k) || "null"); } catch { return null; } };
const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* cota cheia: segue sem cache */ } };

// ---------- documentos gerais (meta) ----------
export function cachedMetas() {
  if (DEMO) return null;
  return read(META_CACHE)?.data || null;
}

export async function getMetas(names) {
  if (DEMO) {
    const { demoMeta } = await import("./demo.js");
    return Object.fromEntries(names.map((n) => [n, demoMeta(n)]));
  }
  const r = await request(`${API}:batchGet?${KEY}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ documents: names.map((n) => `${DB}/meta/${n}`) }),
  });
  if (!r.ok) throw new Error(`Firestore respondeu ${r.status}`);
  const rows = await r.json();
  const out = Object.fromEntries(names.map((n) => [n, null]));
  for (const row of rows) {
    if (row.found) out[row.found.name.split("/").pop()] = fromFields(row.found.fields);
  }
  write(META_CACHE, { t: Date.now(), data: out });
  return out;
}

// ---------- equipes ----------
const teamMem = new Map();

export function cachedTeam(id) {
  if (teamMem.has(id)) return teamMem.get(id);
  const c = read(TEAM_CACHE) || {};
  return c[id]?.data || null;
}

export async function getTeam(id) {
  if (!id) return null;
  if (teamMem.has(id)) return teamMem.get(id);
  let data = null;
  if (DEMO) data = (await import("./demo.js")).demoTeam(id);
  else {
    const r = await request(`${API}/teams/${encodeURIComponent(id)}?${KEY}`);
    if (r.status === 404) data = null;
    else if (!r.ok) throw new Error(`Firestore respondeu ${r.status}`);
    else data = fromFields((await r.json()).fields);
    const c = read(TEAM_CACHE) || {};
    if (data) c[id] = { t: Date.now(), data };
    const keys = Object.keys(c).sort((a, b) => c[b].t - c[a].t);
    keys.slice(TEAM_CACHE_MAX).forEach((k) => delete c[k]);
    write(TEAM_CACHE, c);
  }
  teamMem.set(id, data);
  return data;
}
