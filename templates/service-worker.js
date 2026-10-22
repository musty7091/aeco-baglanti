const CACHE_NAME = 'aeco-shell-v183';

const STATIC_ASSETS = [
  '/static/css/app.css?v=183',
  '/static/js/app.js?v=183',
  '/static/img/aeco-logo.png',
  '/static/img/icon-192.png'
];

self.addEventListener('install', event => {
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return Promise.allSettled(
        STATIC_ASSETS.map(url => cache.add(url))
      );
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  const request = event.request;

  if (request.method !== 'GET') {
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .catch(() => {
          return new Response(
            'İnternet bağlantısı kurulamadı. Lütfen bağlantınızı kontrol edip tekrar deneyin.',
            {
              status: 503,
              headers: {
                'Content-Type': 'text/plain; charset=utf-8'
              }
            }
          );
        })
    );
    return;
  }

  event.respondWith(
    fetch(request, { cache: 'no-store' })
      .then(response => {
        if (!response) {
          throw new Error('Sunucudan boş yanıt alındı.');
        }
        return response;
      })
      .catch(async () => {
        const cachedResponse = await caches.match(request);

        if (cachedResponse) {
          return cachedResponse;
        }

        return new Response('', {
          status: 504,
          statusText: 'Gateway Timeout'
        });
      })
  );
});
