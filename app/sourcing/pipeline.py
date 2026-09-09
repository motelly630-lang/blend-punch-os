"""Sourcing orchestrator — 업로드된 행들을 추출→가격계산→Product 생성으로 처리.

MVP: 동기 처리(행 수 제한). 단계별 에러는 행 단위로 격리해 batch.error_log에 기록.
사람 승인(8단계)은 자동 통과 금지 — 생성된 Product는 review_status="structured"까지만.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

import json

from app.models import Product, SourcingBatch
from app.sourcing import brand_match, category_rules, naver, pricing
from app.sourcing.agents import compliance, copywriter, extractor, profiler, researcher

log = logging.getLogger(__name__)

MAX_PRODUCTS = 50  # MVP 동기 처리 상한


def _clamp(v, n: int):
    """짧은 VARCHAR 컬럼 초과 방지 — n자 초과 시 자른다."""
    if v is None:
        return None
    s = str(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def run_extraction(db: Session, batch: SourcingBatch, grid: list[list[str]], company_id: int = 1) -> SourcingBatch:
    """시트 전체(문서형 제안서)를 AI로 읽어 상품목록+공통정보 추출 → Product 생성.

    공동구매 제안서/계획서처럼 깔끔한 표가 아닌 양식도 처리한다.
    """
    batch.status = "extracting"
    batch.total_rows = len([r for r in grid if any(r)])
    db.commit()

    errors: list[dict] = []
    created = 0
    try:
        sheet = extractor.extract_sheet(grid, batch.source_filename or "")
    except Exception as e:
        log.exception("sheet extract failed")
        batch.status = "failed"
        batch.error_count = 1
        batch.error_log = [{"row": 0, "message": f"시트 추출 실패: {type(e).__name__}: {e}"}]
        db.commit()
        return batch

    products = (sheet or {}).get("products") or []
    # 공통(문서 전반) 정보 — 모든 상품에 공유 적용
    shared_benefits = sheet.get("selling_points") or []
    shared_notes_parts = []
    if sheet.get("settlement_terms"):
        shared_notes_parts.append("[정산] " + sheet["settlement_terms"])
    for c in (sheet.get("cautions") or []):
        shared_notes_parts.append("[안내] " + c)
    shared_notes = "\n".join(shared_notes_parts) or None

    for idx, pr in enumerate(products[:MAX_PRODUCTS]):
        try:
            product = _build_product(db, batch, sheet, pr, shared_benefits, shared_notes, company_id)
            if product is None:
                errors.append({"row": idx + 1, "message": "상품명 없음"})
                continue
            db.add(product)
            created += 1
        except Exception as e:
            log.exception("create product %s failed", idx + 1)
            errors.append({"row": idx + 1, "message": f"{type(e).__name__}: {e}"})

    batch.extracted_count = created
    batch.error_count = len(errors)
    batch.error_log = errors or None
    batch.status = "review" if created else "failed"
    db.commit()
    return batch


def _build_product(db, batch, sheet, pr, shared_benefits, shared_notes, company_id) -> "Product | None":
    """추출 상품 1건 → 16필드 풀 자동화로 Product 구성.

    엑셀추출 + 브랜드 OS매칭 + 네이버(URL/이미지) + AI프로파일 + 카테고리 규칙.
    """
    name = (pr.get("name") or "").strip()
    if not name:
        return None

    consumer = pr.get("consumer_price") or 0
    supplier = pr.get("supplier_price") or 0
    groupbuy = pr.get("groupbuy_price") or consumer or 0
    breakdown = pricing.compute(consumer_price=consumer, supplier_price=supplier, groupbuy_price=groupbuy)
    opt = pr.get("option_note")

    # ① 브랜드 OS 매칭
    bm = brand_match.match(db, sheet.get("brand") or "", company_id)
    brand = bm["name"] or "미상"

    # ② 네이버 쇼핑 검색 → 제품 URL + 이미지 (상품별 링크 우선, 제안서 URL은 폴백)
    nv = naver.search_product(name, brand) if naver.is_configured() else {}
    product_url = nv.get("url") or sheet.get("product_url") or None
    product_image = nv.get("image") or bm.get("logo") or None

    # ③ AI 프로파일 (설명·USP·혜택·앵글·포지셔닝·타겟·구조타입·태그)
    ref = nv.get("title") or ""
    prof = {}
    try:
        prof = profiler.generate(
            name, brand, sheet.get("category") or "",
            consumer_price=consumer, groupbuy_price=groupbuy,
            options=opt or "", benefits=shared_benefits, ref=ref,
        )
    except Exception:
        log.exception("profiler failed for %s", name)

    category = prof.get("category") or sheet.get("category") or "미분류"

    # ④ 카테고리 규칙 → 추천 커미션율 + 소비자 태그 (허용 8개 안에서만)
    rec_comm = category_rules.recommended_commission(category, name)
    tags = category_rules.filter_tags((prof.get("consumer_tags") or []) + category_rules.consumer_tags(category, name))
    if not tags:  # 매칭 실패 시 카테고리 규칙 기본값
        tags = category_rules.consumer_tags(category, name) or []

    # 핵심 혜택: 프로파일 + 시트 셀링포인트 병합
    benefits = list(dict.fromkeys((prof.get("key_benefits") or []) + (shared_benefits or [])))

    # 메모: 정산/안내/구조타입/배송상세/수량
    dispatch_full = sheet.get("dispatch_days")
    note_bits = [b for b in [
        pr.get("note"),
        (f"판매가능수량 {int(pr['available_qty'])}" if pr.get("available_qty") else None),
        (f"[구조] {prof['structure_type']}" if prof.get("structure_type") else None),
        (f"[배송] {dispatch_full}" if dispatch_full and len(str(dispatch_full)) > 20 else None),
    ] if b]

    return Product(
        company_id=company_id,
        status="draft",
        review_status="structured",
        sourcing_batch_id=batch.id,
        name=name,
        brand=brand,
        category=category,
        consumer_price=consumer,
        supplier_price=supplier,
        groupbuy_price=groupbuy,
        margin_rate=breakdown.margin_rate,
        discount_rate=breakdown.discount_rate or 0,
        recommended_commission_rate=rec_comm,
        set_options=[{"name": opt, "qty": 1, "price": groupbuy, "notes": ""}] if opt else None,
        description=prof.get("description"),
        unique_selling_point=prof.get("unique_selling_point"),
        key_benefits=benefits or None,
        content_angle=prof.get("content_angle"),
        positioning=prof.get("positioning"),
        target_audience=prof.get("target_audience"),
        categories=tags or None,
        product_link=product_url,
        product_image=product_image,
        carrier=_clamp(sheet.get("shipping_carrier"), 50),
        shipping_cost=sheet.get("shipping_fee"),
        dispatch_days=_clamp(sheet.get("dispatch_days"), 20),
        as_info=sheet.get("as_info"),
        internal_notes="\n".join(filter(None, [shared_notes, " · ".join(note_bits) or None])) or None,
    )


def enrich_product(db: Session, product: Product, do_research: bool = True) -> Product:
    """2차 보강: 웹서치 → 규제표현 분리 → 카피 생성. 결과를 Product에 저장.

    - research  → ai_analysis_raw (JSON 문자열)
    - compliance→ Product.compliance (JSON)
    - copy      → Product.generated_copy (JSON)
    각 단계는 독립적으로 실패해도 나머지를 진행한다.
    """
    name = product.name or ""
    brand = product.brand or ""
    category = product.category or ""
    benefits = product.key_benefits or []

    research = {}
    if do_research:
        try:
            research = researcher.research(name, brand, category)
            if research:
                product.ai_analysis_raw = json.dumps(research, ensure_ascii=False)
        except Exception:
            log.exception("research failed for %s", product.id)

    extra = ""
    if research:
        extra = (research.get("official_info") or "") + " / 후기키워드: " + ", ".join(research.get("review_keywords", []))

    # 웹서치 결과를 근거로 프로파일(설명·USP·혜택·앵글·포지셔닝) 재생성 → 검증된 카피
    if research:
        ref = "\n".join(filter(None, [
            "공식정보: " + (research.get("official_info") or ""),
            "장점: " + ", ".join(research.get("pros", [])),
            "주의: " + ", ".join(research.get("cautions", [])),
            "후기키워드: " + ", ".join(research.get("review_keywords", [])),
        ]))
        try:
            prof = profiler.generate(
                name, brand, category,
                consumer_price=product.consumer_price or 0,
                groupbuy_price=product.groupbuy_price or 0,
                benefits=benefits, ref=ref,
            )
            if prof:
                product.description = prof.get("description") or product.description
                product.unique_selling_point = prof.get("unique_selling_point") or product.unique_selling_point
                product.key_benefits = list(dict.fromkeys((prof.get("key_benefits") or []) + benefits)) or product.key_benefits
                product.content_angle = prof.get("content_angle") or product.content_angle
                product.positioning = prof.get("positioning") or product.positioning
                product.target_audience = prof.get("target_audience") or product.target_audience
                benefits = product.key_benefits or benefits  # 이후 compliance/copy에 반영
        except Exception:
            log.exception("grounded profile regen failed for %s", product.id)

    try:
        comp = compliance.analyze(name, brand, category, benefits, extra=extra)
        if comp:
            product.compliance = comp
    except Exception:
        log.exception("compliance failed for %s", product.id)
        comp = product.compliance or {}

    try:
        safe = (comp or {}).get("safe_expressions", [])
        risky = [r.get("phrase") for r in (comp or {}).get("risky_expressions", [])]
        copy = copywriter.generate(
            name, brand, category, benefits,
            usp=product.unique_selling_point or "",
            groupbuy_price=product.groupbuy_price or 0,
            safe=safe, risky=risky,
        )
        if copy:
            product.generated_copy = copy
    except Exception:
        log.exception("copy failed for %s", product.id)

    if product.review_status == "structured":
        product.review_status = "reviewed"
    db.commit()
    db.refresh(product)
    return product


def settlement_table(product: Product) -> dict:
    """검수 화면용 정산표: 1건(공구가) 기준, 셀러 유형 × 수수료율 정산금.

    반환 구조 (템플릿 친화):
      {basis, rates:[...], rows:[{seller_type, note, cells:[settlement_amount,...]}]}
    """
    basis = product.groupbuy_price or 0
    rates = list(pricing.DEFAULT_COMMISSION_SCENARIOS)
    rows = []
    for t in pricing.SELLER_TYPES:
        cells = [pricing.settle(basis, rate, t) for rate in rates]
        rows.append({
            "seller_type": t,
            "note": cells[0].note,
            "cells": [c.settlement_amount for c in cells],
        })
    return {"basis": int(basis), "rates": rates, "rows": rows}
