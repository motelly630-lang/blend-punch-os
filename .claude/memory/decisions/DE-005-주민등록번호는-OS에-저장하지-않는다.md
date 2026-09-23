---
id: DE-005
type: decision
title: 인플루언서 주민등록번호는 OS 에 저장하지 않는다
status: active
supersedes:
tags: [개인정보, 주민등록번호, 인플루언서, 정산, 원천징수, 보안, 암호화, 프리랜서]
paths: ["app/models/influencer.py", "app/routers/influencers.py", "app/templates/influencers/**"]
updated: 2026-09-23
---

인플루언서(프리랜서)의 주민등록번호는 OS 에 입력받지도 저장하지도 않는다. 원천징수(3.3%) 신고에
필요한 주민번호는 세무 쪽 자료에서 별도로 관리한다 (2026-09-23 대표님 결정).
`influencers.resident_registration_number` 컬럼은 남아 있어도 값은 항상 비어 있어야 한다.

**근거 / 깨지면 어떻게 되는가:** 주민번호는 개인정보보호법상 암호화 저장 의무 대상인데, OS 는 평문으로
저장하고 있었다(2026-09-23 운영 2건 확인). 유출 시 법적 책임이 크고, OS 의 정산 계산에는 주민번호가
필요 없다(세율은 `business_type` 으로 정해진다).
**검증 방법:** 운영 `SELECT count(*) FROM influencers WHERE resident_registration_number IS NOT NULL
AND resident_registration_number <> ''` = 0. 등록·수정 폼과 라우터에 주민번호 입력이 없어야 한다.
**탈락 대안:** 암호화해서 저장 — 키 관리·복호화 권한·감사 로그까지 갖춰야 하고, OS 에서 쓰는 곳이 없어
보관할 이유보다 위험이 크다.

관련: [[RG-002]]
