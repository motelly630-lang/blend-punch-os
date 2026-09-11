---
id: IS-005
type: issue
title: static/logo.png 이 존재하지 않는데 템플릿 10곳 이상이 참조한다
status: active
tags: [static, 자산, logo, favicon, 404, 로그인, 포털, 브랜딩]
paths: ["static/**", "app/templates/auth/**", "app/templates/portal_base.html", "app/templates/base.html"]
updated: 2026-09-11
---

`static/logo.png` 는 **로컬에도 EC2 에도 없고 git 에 추적되지도 않는다**(`static/` 추적 파일 36개 중 없음).
그런데 아래에서 참조한다:

```
app/templates/base.html:10            <link rel="icon" type="image/png">
app/templates/auth/login.html:8,28    favicon + 로그인 화면 로고 <img>
app/templates/auth/portal_login.html:7,18
app/templates/auth/signup.html:16
app/templates/portal_base.html:7,47
app/templates/portal/select.html:7,15
```

대부분의 `<img>` 에 `onerror="this.style.display='none'"` 가 있어 깨진 아이콘 대신 사라지지만,
**로고가 아예 안 보이는 상태**이고 페이지마다 404 요청이 한 번씩 더 발생했다.

2026-09-11 이전에는 uvicorn 이 스타일된 404 HTML(2,658바이트)을 돌려줘서 눈에 안 띄었다.
nginx 직접 서빙으로 바뀐 뒤에는 평범한 404(162바이트)가 나간다 — **이 변경이 원인이 아니라
원래 없던 파일이 드러난 것**이다.

**선택지 (사용자 결정 필요):**
1. 실제 로고 파일을 `static/logo.png` 로 추가하고 커밋 — 브랜딩이 살아난다
2. 참조를 이미 있는 `static/icons/icon.svg` 로 바꾼다 — 파일 추가 없이 해결
3. 그대로 둔다 — 동작에는 문제없다(404 왕복 1회만 낭비)

쓸 수 있는 기존 자산: `static/icons/icon.svg`, `static/og-image.png`(46KB).
