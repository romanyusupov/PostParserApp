const CACHE_PREFIX = 'easypracticecalc-';
const CACHE_NAME = `${CACHE_PREFIX}2026-08-21-v12`;
const ASSETS = [
  './',
  './index.html',
  './timer_logic.js',
  './timer.js',
  './manifest.webmanifest',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
  './assets/history-running.webp',
  './assets/history-walking.webp',
  './assets/history-water.webp',
  './assets/timer-move-female.webp',
  './assets/timer-move-male.webp',
  './assets/timer-water-female.webp',
  './assets/timer-water-male.webp',
  './assets/button-play.webp',
  './assets/button-pause.webp',
  './assets/button-reset.webp',
  './assets/button-next.webp',
  './assets/button-next-active.webp'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(ASSETS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
          .map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  const requestUrl = new URL(event.request.url);
  const scopeUrl = new URL(self.registration.scope);
  if (
    requestUrl.origin !== self.location.origin
    || !requestUrl.pathname.startsWith(scopeUrl.pathname)
  ) return;

  const acceptsHtml = (event.request.headers.get('accept') || '')
    .includes('text/html');
  const isHtmlNavigation = event.request.mode === 'navigate' || acceptsHtml;

  event.respondWith(
    caches.match(event.request, {ignoreSearch:true}).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (!response || response.status !== 200 || response.type !== 'basic') return response;
        const copy = response.clone();
        return caches.open(CACHE_NAME)
          .then(cache => cache.put(event.request, copy))
          .then(() => response);
      }).catch(error => {
        if (isHtmlNavigation) return caches.match('./index.html');
        throw error;
      });
    })
  );
});
