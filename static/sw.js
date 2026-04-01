// BLEND PUNCH OS — Service Worker
const CACHE_NAME = 'bpos-v1';

// ── Install ──────────────────────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

// ── Activate ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// ── Fetch ────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Cross-origin (CDN 등): 그냥 통과
  if (url.origin !== self.location.origin) return;

  // /static/ 자산: Cache-First
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.open(CACHE_NAME).then(cache =>
        cache.match(req).then(cached => {
          if (cached) return cached;
          return fetch(req).then(res => {
            if (res.ok) cache.put(req, res.clone());
            return res;
          }).catch(() => cached);
        })
      )
    );
    return;
  }

  // HTML 페이지 / API: Network-First, 오프라인 폴백
  event.respondWith(
    fetch(req).catch(() =>
      caches.match(req).then(cached => cached || offlinePage())
    )
  );
});

function offlinePage() {
  return new Response(
    `<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>오프라인 — BLEND PUNCH OS</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #111827; color: #f9fafb;
           display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
    .box { text-align: center; padding: 2rem; }
    svg { width: 48px; height: 48px; margin-bottom: 1rem; }
    h2 { font-size: 1.25rem; margin-bottom: .5rem; }
    p  { color: #9ca3af; font-size: .875rem; }
    a  { display: inline-block; margin-top: 1.5rem; padding: .625rem 1.25rem;
         background: #2563eb; color: #fff; border-radius: .5rem; text-decoration: none; font-size: .875rem; }
  </style>
</head>
<body>
  <div class="box">
    <svg viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="1.5">
      <path stroke-linecap="round" stroke-linejoin="round"
            d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z"/>
    </svg>
    <h2>인터넷 연결 없음</h2>
    <p>네트워크 연결을 확인한 후 다시 시도해주세요.</p>
    <a href="/">새로고침</a>
  </div>
</body>
</html>`,
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
  );
}
