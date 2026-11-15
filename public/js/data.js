// Camada de dados: Firestore (produção) ou dados fictícios (?demo).
import { firebaseConfig } from "./firebase-config.js";

export const DEMO = new URLSearchParams(location.search).has("demo");
export const CONFIGURED = !String(firebaseConfig.projectId).startsWith("SEU-");

const SDK = "https://www.gstatic.com/firebasejs/10.14.1";
let fs = null;
const teamCache = new Map();

async function firestore() {
  if (fs) return fs;
  const [{ initializeApp }, lib] = await Promise.all([
    import(`${SDK}/firebase-app.js`),
    import(`${SDK}/firebase-firestore.js`),
  ]);
  fs = { db: lib.getFirestore(initializeApp(firebaseConfig)), doc: lib.doc, getDoc: lib.getDoc };
  return fs;
}

export async function getMeta(name) {
  if (DEMO) return (await import("./demo.js")).demoMeta(name);
  const { db, doc, getDoc } = await firestore();
  const snap = await getDoc(doc(db, "meta", name));
  return snap.exists() ? snap.data() : null;
}

export async function getTeam(id) {
  if (teamCache.has(id)) return teamCache.get(id);
  let data;
  if (DEMO) data = (await import("./demo.js")).demoTeam(id);
  else {
    const { db, doc, getDoc } = await firestore();
    const snap = await getDoc(doc(db, "teams", id));
    data = snap.exists() ? snap.data() : null;
  }
  teamCache.set(id, data);
  return data;
}
