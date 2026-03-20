const CACHE = 'hoamdosa-v1';
const ASSETS = ['/', '/static/style.css', '/static/app.js'];

self.addEventListener('install', e => {
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
    self.skipWaiting();
});

self.addEventListener('activate', e => {
    e.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', e => {
    if (e.request.method !== 'GET') return;
    if (e.request.url.includes('/api/')) return; // API는 캐시 안 함
    e.respondWith(
        fetch(e.request).catch(() => caches.match(e.request))
    );
});
