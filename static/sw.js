"use strict";

const CACHE_NAME = "handball-shell-v6";
const SHELL = [
  "/app",
  "/app/presencas",
  "/static/styles.css",
  "/static/platform.js",
  "/static/app.js",
  "/static/manifest.webmanifest",
  "/static/icon-192.png",
  "/static/icon-512.png",
];
const CACHEABLE_PATHS = new Set(SHELL);
const OFFLINE_NAVIGATIONS = new Map([
  ["/app", "/app"],
  ["/app/presencas", "/app/presencas"],
]);

function isNetworkOnly(pathname) {
  return pathname === "/login"
    || pathname === "/logout"
    || pathname === "/app/estatisticas"
    || pathname.startsWith("/app/estatisticas/")
    || pathname === "/app/calendario"
    || pathname.startsWith("/app/calendario/")
    || pathname === "/app/consultas"
    || pathname.startsWith("/app/consultas/")
    || pathname === "/roberto"
    || pathname.startsWith("/roberto/")
    || pathname.startsWith("/api/");
}

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys
        .filter((key) => key.startsWith("handball-shell-") && key !== CACHE_NAME)
        .map((key) => caches.delete(key)),
    )),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || isNetworkOnly(url.pathname)) return;
  if (request.mode === "navigate" && OFFLINE_NAVIGATIONS.has(url.pathname)) {
    const fallback = OFFLINE_NAVIGATIONS.get(url.pathname);
    event.respondWith(fetch(request).catch(() => caches.match(fallback)));
    return;
  }
  if (url.pathname.startsWith("/static/") && CACHEABLE_PATHS.has(url.pathname)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request)),
    );
  }
});
