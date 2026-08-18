const CACHE_NAME = "devis-sbbm-static-v2";
const URLS_TO_CACHE = [
  "/static/style.css",
  "/static/logo_sbbm.jpg",
  "/static/icon-192.png",
  "/static/icon-512.png"
];

// Install : on met en cache les fichiers principaux
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(URLS_TO_CACHE);
    })
  );
});

// Activate : nettoyage des anciens caches si on change de version
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    )
  );
});

// Ne jamais mettre en cache les pages authentifiées, devis ou données clients.
// Seules les ressources statiques publiques peuvent être servies hors connexion.
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (
    request.method !== "GET" ||
    url.origin !== self.location.origin ||
    !url.pathname.startsWith("/static/")
  ) {
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok) {
          const cloned = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, cloned));
        }
        return response;
      });
    })
  );
});
