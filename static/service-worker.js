const CACHE_NAME = "devis-sbbm-v1";
const URLS_TO_CACHE = [
  "/",
  "/devis/form",
  "/devis/historique",
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

// Fetch : stratégie "network first puis cache"
self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return;
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        // on met en cache la réponse
        const cloned = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(request, cloned));
        return response;
      })
      .catch(() => {
        // si offline → on sert la version cache si dispo
        return caches.match(request);
      })
  );
});