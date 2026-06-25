// Gaelic Shadowing Practice — app-shell service worker.
// Bump CACHE_VERSION whenever this file or the cached shell assets change.
const CACHE_VERSION = 'gshadow-shell-v1';
const SHELL_ASSETS = [
  '/',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Network-first for navigations (so logged-in/admin pages and fresh content
// always win when online), falling back to the cached shell when offline.
// Audio (/audio/*) and login/upload/admin are never cached — always go to
// the network so auth state and large media aren't stored.
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  const bypass = url.pathname.startsWith('/audio/') ||
                 url.pathname.startsWith('/login') ||
                 url.pathname.startsWith('/logout') ||
                 url.pathname.startsWith('/upload') ||
                 url.pathname.startsWith('/admin') ||
                 url.pathname.startsWith('/import') ||
                 url.pathname.startsWith('/split');
  if (bypass) return;

  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => caches.match('/').then((r) => r || Response.error()))
    );
    return;
  }

  // Cache-first for the small set of static shell assets.
  if (SHELL_ASSETS.includes(url.pathname)) {
    event.respondWith(
      caches.match(req).then((cached) => cached || fetch(req))
    );
  }
});
