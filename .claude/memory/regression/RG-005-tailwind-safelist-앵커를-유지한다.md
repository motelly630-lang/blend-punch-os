---
id: RG-005
type: regression
title: tailwind safelist 정규식의 ^...$ 앵커를 제거하지 않는다
status: active
tags: [tailwind, css, safelist, 성능, 빌드, 정규식, 앵커, 용량, 렌더링]
paths: ["tailwind.config.js", "static/css/app.css", "package.json"]
updated: 2026-09-11
---

**지킬 조건:** `tailwind.config.js` 의 safelist `pattern` 은 `^...$` 로 앵커돼 있어야 한다.
변형(`hover:` 등)이 필요하면 패턴을 열지 말고 `variants: [...]` 로 **필요한 것만** 명시한다.

**깨지면 어떻게 되는가:** Tailwind 는 생성 후보 클래스명을 패턴에 대조한다. 앵커가 없으면
`hover:bg-red-500` 이 `bg-red-500` 을 **부분 문자열로 포함**하므로 매치되어, 색상 조합마다
모든 변형이 생성된다. 2026-09-11 실측 — 접두 하나당 4,840개씩 생성돼 셀렉터가 **24,997개**,
`app.css` 가 **1,404,821 바이트**까지 부풀어 있었다. 앵커를 넣자 2,929개 / 262,920 바이트
(**81% 절감**)가 됐고 화면은 동일했다.

조용히 틀리는 종류다 — 빌드도 성공하고 화면도 멀쩡해서, 용량을 재보기 전엔 아무도 모른다.

**검증 방법 (R2):**
```bash
wsl -- bash -lc "cd /home/blendpunch/blend-punch-os && npm run build:css && wc -c static/css/app.css"
```
**26만 바이트 근처가 정상. 100만을 넘으면 앵커가 빠진 것이다.**

회귀 여부를 정확히 보려면 빌드 전후 셀렉터 집합을 비교한다 — 이전 CSS 에는 있는데 새 CSS 에
없는 클래스 중 **소스에 실제로 등장하는 것**이 있으면 진짜 회귀다. 없으면 안전하다.

**변형을 safelist 에 추가해야 하는 경우:** 템플릿이 변형 접두사와 색상을 동적으로 조합할 때만이다.
현재 해당하는 곳은 두 군데뿐 —
`app/templates/companies/detail.html`, `app/templates/feature_flags/index.html` 의
`hover:border-{{ plan_color }}-200` / `hover:bg-{{ plan_color }}-50`.
정적으로 쓴 변형(`focus:ring-blue-500` 등)은 content 스캔이 잡으므로 safelist 에 넣지 않는다.

관련: [[DE-004]]
