const CACHE = 'mvs-v1';
const ASSETS = [
  '/mvs-bot/',
  '/mvs-bot/index.html',
  '/mvs-bot/manifest.json',
  '/mvs-bot/icon-192.png',
  '/mvs-bot/icon-512.png',
  '/mvs-bot/apple-touch-icon.png'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  // API запросы — только сеть, не кешировать
  if (e.request.url.includes('amvera.io') || e.request.url.includes('api.github.com')) {
    e.respondWith(fetch(e.request).catch(() => new Response('offline', {status: 503})));
    return;
  }
  // Остальное — сначала сеть, при ошибке — кеш
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const clone = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
