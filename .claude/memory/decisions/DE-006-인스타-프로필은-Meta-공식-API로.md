---
id: DE-006
type: decision
title: 인스타 프로필(사진·팔로워) 자동 수집은 Meta 공식 Business Discovery API 로 한다
status: active
supersedes:
tags: [인스타그램, instagram, meta, graph-api, business-discovery, 인플루언서, 프로필, 크롤링, instagrapi]
paths: ["app/api/ai_influencer.py", "app/services/instagram.py", "app/services/influencer_enrich.py"]
updated: 2026-09-26
---

인플루언서 등록 시 인스타 URL → 아이디·프로필 사진·팔로워 수 자동 채우기, 그리고 기존 인플루언서 일괄
보강은 Meta 공식 Instagram Graph API 의 Business Discovery 로 한다 (2026-09-23 대표님 결정).
우리 인스타 프로페셔널 계정(페이스북 페이지 연결)의 토큰으로 다른 비즈니스·크리에이터 계정을 조회한다.
권한: `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`
(비즈니스 관리자 경유 페이지 권한이면 `ads_read` 추가). 개인 계정·연령 제한 계정은 조회되지 않는다.
토큰은 서버 `.env` 에만 둔다.

**근거 / 깨지면 어떻게 되는가:** 기존 "URL 가져오기"는 instagrapi 봇 로그인이 전제인데 운영에 설정이 없고,
대체 경로인 AI 파싱도 API 크레딧 소진으로 멈춰 아이디만 채워졌다(2026-09-23 확인, 사진 보유 111/1,260).
**검증 방법:** 토큰으로 `GET /v25.0/<IG user id>?fields=business_discovery.username(<대상>){username,name,profile_picture_url,followers_count}`
응답 확인 (문서: developers.facebook.com/docs/instagram-platform — Business Discovery).
**탈락 대안:** instagrapi 봇 계정 로그인 — 비공식이라 봇 계정 차단·AWS IP 차단 위험 (`influencer_enrich` 는
운영에서 한 번도 실행된 적 없음). HTML 긁기 + AI — 인스타 로그인 벽에 막히고 AI 비용·크레딧 의존.

**적용 현황 (2026-09-24):** Meta 앱 `BlendPunch OS`(개발 모드, 심사 불필요 — 앱 관리자 본인 사용), 조회 계정 @blend_punch
(YJ Company 페이지). 만료 없는 **페이지 토큰**을 서버·맥북 `.env` 의 `META_PAGE_TOKEN`·`META_IG_USER_ID` 에 둔다(값은 서버에만).
토큰 재발급: 그래프 API 탐색기(권한 5개 + business_management) → 액세스 토큰 도구 '연장' → 페이지 토큰 도출.
페이스북 '비즈니스 통합'에서 앱을 제거하면 모든 토큰이 무효가 된다(노출 시 대응 절차).
2026-09-26 재발급 실전: `ads_read` 는 권한 목록에 없어도 된다. 대표님이 연장 **사용자** 토큰을 복사해도 괜찮다 —
그 토큰으로 `me/accounts` 를 불러 @blend_punch 페이지 토큰을 꺼내면 된다. 토큰은 채팅 대신 `! pbpaste > 파일`(권한 600)로 받는다.

**일괄 보강 (2026-09-24, T4):** `app/services/influencer_enrich.py` 가 Meta 경로를 쓴다 (새벽 04:30 스케줄, `INFLUENCER_ENRICH`·`_LIMIT`).
실측: 5명 조회 = `X-App-Usage` 1% (한 명 약 0.2%, 약 4초). 사용량 50% 에서 스스로 멈추고, 한도·토큰·통신 오류는
기록하지 않고 멈춰 다음 실행에서 이어간다. 개인 계정은 `enrich_error` + 30일 제외. 로컬 5명 시험: 수집 4 · 조회불가 1.
수동 실행: `.venv/bin/python -m app.services.influencer_enrich --dry-run | --limit N`.

관련: [[DE-005]]
