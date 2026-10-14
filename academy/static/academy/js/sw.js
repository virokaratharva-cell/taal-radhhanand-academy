/**
 * TAAL — Radhhanand Sangeet Vidyalaya
 * Service Worker for Progressive Web App (PWA)
 * Strategy: Network-first for dynamic academy data; Cache-first for static UI assets.
 * NEVER caches sensitive student, fee, or payment data insecurely.
 */

const CACHE_NAME = 'taal-rsv-v1.2';
const STATIC_ASSETS = [
    '/static/academy/css/taal.css',
    '/static/academy/js/taal.js',
    '/static/academy/icons/icon-192x192.png',
    '/static/academy/icons/icon-512x512.png',
    '/static/academy/icons/icon.svg',
    '/offline/'
];

// Install: Cache critical static shell
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(STATIC_ASSETS).catch(err => {
                console.warn('Some assets failed to cache during install:', err);
            });
        }).then(() => self.skipWaiting())
    );
});

// Activate: Clean up old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => {
            return Promise.all(
                keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch: Network-first for HTML pages; Cache-first for static assets
self.addEventListener('fetch', event => {
    const request = event.request;
    const url = new URL(request.url);

    // Only handle GET requests
    if (request.method !== 'GET') {
        return;
    }

    // Never cache admin, login, payments, receipts, or API requests
    if (url.pathname.includes('/login/') ||
        url.pathname.includes('/logout/') ||
        url.pathname.includes('/fees/') ||
        url.pathname.includes('/admin/') ||
        url.pathname.includes('/whatsapp/')) {
        return;
    }

    // Static assets: cache-first with network fallback
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(request).then(cached => {
                return cached || fetch(request).then(response => {
                    if (response.status === 200) {
                        const responseClone = response.clone();
                        caches.open(CACHE_NAME).then(cache => cache.put(request, responseClone));
                    }
                    return response;
                });
            })
        );
        return;
    }

    // HTML navigations: Network-first with offline fallback
    if (request.headers.get('accept') && request.headers.get('accept').includes('text/html')) {
        event.respondWith(
            fetch(request)
                .then(response => {
                    return response;
                })
                .catch(() => {
                    return caches.match('/offline/').then(offlineResp => {
                        return offlineResp || new Response(
                            '<div style="font-family:sans-serif;padding:30px;text-align:center;">' +
                            '<h2>Radhhanand Sangeet Vidyalaya</h2>' +
                            '<p>You are currently offline. Please reconnect to the internet to access live academy records.</p>' +
                            '</div>',
                            { headers: { 'Content-Type': 'text/html' } }
                        );
                    });
                })
        );
    }
});
