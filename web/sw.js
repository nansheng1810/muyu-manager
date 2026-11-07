/* AstrBot 舰队管理器 PWA：缓存静态壳，API 始终走网络。 */
const CACHE_NAME = "fleet-shell-v1.23.12e";
const SHELL = [
  "/",
  "/assets/style.css",
  "/assets/consoles.css",
  "/assets/memory.css",
  "/assets/dsh.css",
  "/assets/health.css",
  "/assets/approvals.css",
  "/assets/automation.css",
  "/assets/guard.css",
  "/assets/insight.css",
  "/assets/deploy.css",
  "/assets/consoles.js",
  "/assets/brain.js",
  "/assets/memory.js",
  "/assets/dsh.js",
  "/assets/health.js",
  "/assets/approvals.js",
  "/assets/tasks.js",
  "/assets/digest.js",
  "/assets/duet.js",
  "/assets/eval.js",
  "/assets/ops.js",
  "/assets/inbox.js",
  "/assets/mood.js",
  "/assets/human.js",
  "/assets/presence.js",
  "/assets/guard.js",
  "/assets/review.js",
  "/assets/fix.js",
  "/assets/owner.js",
  "/assets/release.js",
  "/assets/life.js",
  "/assets/people.js",
  "/assets/memes.js",
  "/assets/vision.js",
  "/assets/hub.js",
  "/assets/ia.js",
  "/assets/automation_center.js",
  "/assets/deploy.js",
  "/assets/app.js"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL))
      .catch(() => undefined)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith("fleet-shell-") && key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put("/", copy)).catch(() => undefined);
          return response;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy)).catch(() => undefined);
        }
        return response;
      });
    }),
  );
});
