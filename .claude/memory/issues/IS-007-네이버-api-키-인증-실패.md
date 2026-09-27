---
id: IS-007
type: issue
title: 네이버 오픈 API 키가 인증 실패 — 쇼핑 검색·데이터랩 모두 401 (024)
status: active
tags: [네이버, naver, api, 키, 인증, 데이터랩, datalab, 쇼핑검색, 트렌드, 소싱]
paths: ["app/sourcing/naver.py", "app/services/slack_standup.py"]
updated: 2026-09-27
---

2026-09-26 운영 서버에서 확인: `settings.naver_client_id/secret` 는 **설정돼 있지만** 호출하면
`401 {"errorCode":"024","errorMessage":"NID AUTH Result Invalid (2) : Authentication failed."}`.
쇼핑 검색(`/v1/search/shop.json`)과 데이터랩(검색어 트렌드·쇼핑인사이트) **둘 다** 같은 오류 → 키 자체 문제로 추정
(데이터랩만 안 켜진 경우라면 쇼핑 검색은 됐어야 한다 — 원인 확정은 못 함).

**영향:** 소싱 파이프라인의 네이버 가격 조회(`app/sourcing/pipeline.py`)가 조용히 빈 값, 트렌드 분석가에
'얼마나 뜨나'(데이터랩 검색량) 재료를 못 붙인다.
**해결 순서:** 대표님이 developers.naver.com/apps 로그인 → **화면 캡처 보고 한 단계씩**(bp-verify-guide) → Client ID/Secret 확인·재발급,
데이터랩(검색어 트렌드·쇼핑인사이트) 사용 API 추가 → 비밀값은 `! pbpaste > 파일` 로 받아 서버·맥북 `.env` 교체(백업 먼저).
**확인 방법:** 서버에서 쇼핑 검색 1건 + 데이터랩 1건 호출해 200.

**2026-09-27 보류:** 대표님 네이버 계정의 '내 애플리케이션' 목록이 비어 있음(서버 키는 다른 계정에서 만들었거나 삭제된 것으로 추정).
새로 등록하려 했더니 '사용 API' 목록에 검색·데이터랩이 안 보였고, 대표님 확인 결과 **제휴(계약·심사)가 필요**하다고 안내됨.
→ 네이버 연결은 보류. 트렌드 보고는 시즌 달력·우리 판매 실적·(예정) 젠스파크 트렌드로 간다. 소싱 파이프라인의 네이버 가격 조회도 계속 빈 값.
