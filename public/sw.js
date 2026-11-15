// Service worker: guarda a casca do app (HTML, CSS, JS, ícones) para abrir na hora, inclusive sem rede.
// Os dados (Firestore) não passam por aqui: o app guarda a última versão por conta própria.
const VERSION = "ba-v5";
const SHELL = [
  "./", "index.html", "css/style.css", "manifest.webmanifest",
  "js/app.js", "js/data.js", "js/stats.js", "js/firebase-config.js",
  "icons/icon-192.png", "icons/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Mesma origem: responde do cache na hora e atualiza o cache em segundo plano.
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith(
    caches.open(VERSION).then(async (cache) => {
      const hit = await cache.match(req, { ignoreSearch: true });
      const net = fetch(req).then((res) => {
        if (res.ok) cache.put(req, res.clone());
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
