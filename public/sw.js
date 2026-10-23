// Service worker : ce qui rend le jeu installable comme une app.
// Les fichiers du site passent toujours par le réseau d'abord (jamais de vieille
// version) ; la dernière copie sert seulement hors connexion. Les extraits et les
// pochettes, sur d'autres serveurs, ne passent pas par ici.
const CACHE = "musiquizqc-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(fetch(e.request)
    .then((res) => {
      if (res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return res;
    })
    // Hors connexion : la dernière copie, ou la page d'accueil pour une navigation.
    .catch(() => caches.match(e.request, { ignoreSearch: true })
      .then((hit) => hit || (e.request.mode === "navigate" ? caches.match("/") : Response.error()))));
});
