const CACHE_NAME = "evidence-atlas-root-v1";
const ASSETS = [
  "/",
  "/index.html",
  "/docs/app.js",
  "/docs/styles.css",
  "/manifest.webmanifest",
  "/library/index.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
});

self.addEventListener("fetch", (event) => {
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
