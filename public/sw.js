// Service worker: guarda a casca do app (HTML, CSS, JS, ícones) para abrir na hora, inclusive sem rede.
// Os dados (Firestore) não passam por aqui: o app guarda a última versão por conta própria.
// Regra importante: HTML e JS precisam ser sempre da MESMA versão. Por isso:
//  - na instalação, tudo é baixado direto do servidor (cache: "reload"), nunca do cache HTTP do navegador;
//  - a página (navegação) vem primeiro da rede, com fallback para o cache se a rede demorar ou faltar.
const VERSION = "ba-v9";
const SHELL = [
  "index.html", "css/style.css", "manifest.webmanifest",
  "js/app.js", "js/data.js", "js/stats.js", "js/firebase-config.js",
  "icons/icon-192.png", "icons/apple-touch-icon.png", "icons/favicon-48.png",
];
const NAV_TIMEOUT = 3000;

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(VERSION)
      .then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: "reload" }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function fresh(req) {
  return fetch(req, { cache: "no-cache" });
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;

  // Página: rede primeiro (até 3 s), depois o index.html guardado.
  if (req.mode === "navigate") {
    e.respondWith(
      caches.open(VERSION).then((cache) => {
        const net = fresh(new Request("index.html")).then((res) => {
          if (res.ok) cache.put("index.html", res.clone());
          return res;
        });
        const timeout = new Promise((resolve) => setTimeout(resolve, NAV_TIMEOUT));
        const fallback = () => cache.match("index.html");
        return Promise.race([net.catch(() => null), timeout])
          .then((res) => res || fallback().then((hit) => hit || net));
      })
    );
    return;
  }

  // Demais arquivos: responde do cache na hora e atualiza em segundo plano.
  e.respondWith(
    caches.open(VERSION).then(async (cache) => {
      const hit = await cache.match(req, { ignoreSearch: true });
      const net = fresh(req).then((res) => {
        if (res.ok) cache.put(req, res.clone());
        return res;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
