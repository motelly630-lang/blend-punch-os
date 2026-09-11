---
id: DE-004
type: decision
title: 정적 파일은 nginx 가 직접 서빙하고, 압축은 nginx 에서 켠다
status: active
tags: [nginx, 성능, 정적파일, static, gzip, 압축, 캐시, uvicorn, 워커, 스케줄러]
paths: ["static/**", "app/main.py"]
updated: 2026-09-11
---

운영 nginx 의 `server` 블록에 압축 설정과 `location /static/` 을 둔다 (2026-09-11 적용).

```nginx
gzip_proxied any;   # ← 이것이 없으면 프록시 응답은 압축되지 않는다
gzip_vary on;  gzip_comp_level 5;  gzip_min_length 1024;
gzip_types text/plain text/css application/json application/javascript
           text/javascript application/xml image/svg+xml;

location /static/ {
    alias /home/ubuntu/blend-punch-os/static/;
    access_log off;
    expires 1h;
    add_header Cache-Control "public, max-age=3600, must-revalidate";
}
```

**근거:** `nginx.conf` 에 `gzip on` 은 있었지만 `gzip_types`·`gzip_proxied` 가 주석 처리돼 있었다.
기본값은 `text/html` + 프록시 응답 미압축인데 이 서버는 전부 `proxy_pass` 라, **결과적으로
HTML·CSS·JS 어느 것도 압축되지 않았다.** 또 `/static` 전용 location 이 없어 정적 파일 28MB 가
전부 uvicorn 단일 워커를 거쳤다.

측정 결과 — CSS 262,920 → **27,008 바이트 전송**, htmx 47,755 → 15,746,
`/public/products` HTML 97,485 → 11,251(8.7배). uvicorn 이 처리하는 `/static` 요청은 0건이 됐다.

**주의 — `www-data` 권한:** `/home/ubuntu` 가 `drwxr-x---` 라 nginx 워커가 통과하지 못한다.
`usermod -aG ubuntu www-data` 로 해결했다. 이 단계를 빠뜨리면 **모든 정적 파일이 403** 이 된다.

**보안 확인:** `/static` 은 `app/main.py` 미들웨어에서 인증 예외(항상 허용)인 공개 경로이고,
권한이 필요한 파일은 `private_uploads/` 에서 별도 인증 라우트(`cs.py`, `portal_cs.py` 의
`FileResponse`)로 나간다. 따라서 직접 서빙해도 **우회되는 권한 검사가 없다.**

**같이 검토했으나 하지 않은 것 — uvicorn 워커 증설.**
`app/main.py:68` 의 lifespan 이 `start_scheduler()` 를 무조건 호출한다. `--workers` 를 늘리면
스케줄러가 워커 수만큼 떠서 **S3 백업·시트 동기화(10분마다 쓰기)·CS 스캔이 중복 실행**된다.
워커를 늘리려면 스케줄러를 별도 프로세스로 분리하는 작업이 선행돼야 한다.
현재 load 0.00, RDS 왕복 1.4ms 이므로 급하지 않다.

**`expires 1h` 의 대가:** 배포 후 최대 1시간 동안 이전 CSS 가 보일 수 있다. 파일명에 해시를
넣는 방식으로 바꾸면 이 제약 없이 영구 캐시가 가능하지만 템플릿 변경이 필요하다.

관련: [[RG-005]] safelist 앵커, [[IS-005]] logo.png 부재
