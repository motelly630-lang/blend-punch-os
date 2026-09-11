// BLEND PUNCH OS — Service Worker
//
// 이 SW 는 "오프라인 폴백" 하나만 담당한다. 자산 캐싱은 하지 않는다.
// 이유(2026-09-11 성능 조사):
//   - v1 은 /static/ 을 Cache-First 로 영구 저장했고 CACHE_NAME 이 한 번도 안 바뀌어,
//     8849ad2 의 app.css 1.34MB → 263KB(gzip 27KB) 개선이 기존 방문자에게 전혀 전달되지 않았다.
//     캐시 무효화 수단이 없는 Cache-First 는 nginx 의 Cache-Control 보다 나쁘다.
//   - 모든 GET 을 respondWith 로 가로채면 요청마다 SW 를 깨우는 비용이 선행된다.
//     내비게이션은 navigationPreload 로 SW 기동과 네트워크를 겹쳐서 이 비용을 없앤다.
// CACHE_NAME 을 올리면 activate 가 옛 캐시를 지운다. v1 잔재 제거가 v2 의 핵심 목적이다.
const CACHE_NAME = 'bpos-v2';

// ── Install ──────────────────────────────────────────────────────────────────
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

// ── Activate ─────────────────────────────────────────────────────────────────
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // 옛 버전 캐시 전부 제거 (v1 에 박혀 있던 구 app.css 포함)
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)));
    // 내비게이션 요청을 SW 기동과 동시에 보낸다 — 클릭당 SW 웜업 지연 제거
    if (self.registration.navigationPreload) {
      await self.registration.navigationPreload.enable();
    }
    await self.clients.claim();
  })());
});

// ── Fetch ────────────────────────────────────────────────────────────────────
self.addEventListener('fetch', (event) => {
  const req = event.request;

  // 내비게이션(주소 이동)만 처리한다. 나머지(/static/·API·이미지)는 건드리지 않아야
  // 브라우저 HTTP 캐시와 nginx 의 Cache-Control 이 그대로 동작한다.
  if (req.mode !== 'navigate') return;

  event.respondWith((async () => {
    try {
      // navigationPreload 가 이미 띄워 둔 응답이 있으면 그대로 쓴다
      const preloaded = await event.preloadResponse;
      if (preloaded) return preloaded;
      return await fetch(req);
    } catch (e) {
      return offlinePage();
    }
  })());
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
