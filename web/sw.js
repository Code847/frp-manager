/* FRP Manager Service Worker（v1.15.0）
 * 策略：
 *  - 面板主文档与静态资源走「网络优先，失败回落缓存」：服务端一更新就能看到新版；
 *  - 离线时回落缓存，保证断线也能看状态页；
 *  - API 一律不缓存，永远打真实后端。
 */
const CACHE = 'frp-manager-' + (self.registration ? 'sw' : 'sw');
const ASSETS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // 单个失败不该让整体安装失败
    await Promise.allSettled(ASSETS.map((u) => cache.add(new Request(u, {cache: 'reload'}))));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'skip-waiting') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (!req || req.method !== 'GET') return;

  const url = new URL(req.url);
  // API 与登录页不缓存
  if (url.pathname.startsWith('/api/') || url.pathname === '/login' || url.protocol === 'file:') {
    return;
  }

  // 导航请求：网络优先，离线回落缓存版本
  if (req.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(CACHE);
        cache.put('./index.html', fresh.clone());
        return fresh;
      } catch (e) {
        const cache = await caches.open(CACHE);
        return (await cache.match('./index.html')) || (await cache.match('./')) || Response.error();
      }
    })());
    return;
  }

  // 静态资源：内存+缓存命中优先，否则回源并写入缓存
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req);
    if (hit) return hit;
    try {
      const res = await fetch(req);
      if (res && res.ok && res.type === 'basic') cache.put(req, res.clone());
      return res;
    } catch (e) {
      return hit || Response.error();
    }
  })());
});
