"""
기능 플래그 서비스

[핵심 개념]
- ALL_FEATURES: 시스템에 존재하는 모든 기능 정의 (코드에서 관리)
- PLAN_FEATURES: 각 플랜(beta/basic/pro)이 포함하는 기능 세트
- GATE_PATHS: URL prefix → feature_key 매핑 (미들웨어 차단용)
- CompanyFeature 행이 없으면 = 모든 기능 활성화 (신규 테넌트 기본값)
- 30s TTL 메모리 캐시로 DB 부하 방지

[확장 포인트]
- 새 기능 추가: ALL_FEATURES dict + GATE_PATHS에 추가
- 새 플랜 추가: PLAN_FEATURES에 key-set 추가
- 멀티테넌트: company_id 파라미터 활용 (현재 항상 1)
"""
import time
import logging
from typing import Optional
from sqlalchemy.orm import Session
from app.models.feature_flag import Company, CompanyFeature

logger = logging.getLogger(__name__)

# ── 전체 기능 정의 ────────────────────────────────────────────────────────────
# key: (display_name, group, tier)
ALL_FEATURES: dict[str, dict] = {
    # OS 핵심
    "dashboard":     {"name": "대시보드",       "group": "os",       "tier": "basic"},
    "products":      {"name": "제품 관리",       "group": "os",       "tier": "basic"},
    "brands":        {"name": "브랜드 관리",     "group": "os",       "tier": "basic"},
    "influencers":   {"name": "인플루언서",      "group": "os",       "tier": "basic"},
    "campaigns":     {"name": "캠페인",          "group": "os",       "tier": "basic"},
    "proposals":     {"name": "제안서",          "group": "os",       "tier": "basic"},
    "applications":  {"name": "공구 신청 관리",  "group": "os",       "tier": "basic"},
    "trends":        {"name": "트렌드",          "group": "os",       "tier": "basic"},
    "trend_engine":  {"name": "시즌 엔진",       "group": "os",       "tier": "pro"},
    "settlements":   {"name": "정산",            "group": "os",       "tier": "basic"},
    "automation":    {"name": "자동화 센터",     "group": "os",       "tier": "pro"},
    "outreach":      {"name": "아웃리치",        "group": "os",       "tier": "pro"},
    "crm":           {"name": "CRM 파이프라인",  "group": "os",       "tier": "pro"},
    # 커머스
    "orders":        {"name": "주문 관리",       "group": "commerce", "tier": "basic"},
    "sales_pages":   {"name": "판매 페이지",     "group": "commerce", "tier": "basic"},
    "sellers":       {"name": "셀러 관리",       "group": "commerce", "tier": "pro"},
}

# ── 플랜 프리셋 ────────────────────────────────────────────────────────────────
PLAN_FEATURES: dict[str, set[str]] = {
    "beta": {
        "dashboard", "products", "brands",
    },
    "basic": {
        "dashboard", "products", "brands",
        "influencers", "campaigns", "proposals", "applications",
        "trends", "settlements",
        "orders", "sales_pages",
    },
    "pro": set(ALL_FEATURES.keys()),
}

# ── URL prefix → feature_key 매핑 (순서 중요: 더 긴 prefix 먼저) ──────────────
GATE_PATHS: list[tuple[str, str]] = [
    ("/trends/engine",   "trend_engine"),
    ("/products",        "products"),
    ("/brands",          "brands"),
    ("/influencers",     "influencers"),
    ("/campaigns",       "campaigns"),
    ("/proposals",       "proposals"),
    ("/applications",    "applications"),
    ("/trends",          "trends"),
    ("/settlements",     "settlements"),
    ("/automation",      "automation"),
    ("/outreach",        "outreach"),
    ("/crm",             "crm"),
    ("/orders",          "orders"),
    ("/sales-pages",     "sales_pages"),
    ("/sellers",         "sellers"),
    # AI API 엔드포인트
    ("/api/ai-proposal", "proposals"),
    ("/api/ai-product",  "products"),
    ("/api/ai-playbook",  "campaigns"),
    ("/api/ai-dm",       "automation"),
    ("/api/ai-seller-content", "automation"),
    ("/api/ai-product-image",  "products"),
    ("/api/ai-influencer",     "influencers"),
    ("/api/ai-recommend",      "influencers"),
    ("/api/ai-product-chat",   "products"),
]

# ── 캐시 ──────────────────────────────────────────────────────────────────────
_cache: dict[int, dict] = {}   # {company_id: {features: set, expires: float}}
CACHE_TTL = 30.0


def invalidate(company_id: int = 1) -> None:
    _cache.pop(company_id, None)


def get_enabled_features(db: Session, company_id: int = 1) -> set[str]:
    """활성화된 feature_key 집합 반환 (캐시 우선)."""
    now = time.monotonic()
    cached = _cache.get(company_id)
    if cached and now < cached["expires"]:
        return cached["features"]

    rows = db.query(CompanyFeature).filter(
        CompanyFeature.company_id == company_id,
        CompanyFeature.enabled == True,
    ).all()

    if not rows:
        # CompanyFeature 행이 없으면 모든 기능 활성화 (기본값)
        features = set(ALL_FEATURES.keys())
    else:
        features = {r.feature_key for r in rows}

    _cache[company_id] = {"features": features, "expires": now + CACHE_TTL}
    return features


def is_enabled(db: Session, key: str, company_id: int = 1) -> bool:
    return key in get_enabled_features(db, company_id)


def get_path_feature(path: str) -> Optional[str]:
    """URL 경로에 해당하는 feature_key 반환. 해당 없으면 None."""
    for prefix, key in GATE_PATHS:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return key
    return None


# ── Company 싱글턴 헬퍼 ────────────────────────────────────────────────────────
def get_or_create_company(db: Session) -> Company:
    company = db.query(Company).filter(Company.id == 1).first()
    if not company:
        company = Company(id=1, name="BLEND PUNCH", plan="pro")
        db.add(company)
        db.commit()
        db.refresh(company)
    return company


def apply_plan(db: Session, plan: str, company_id: int = 1) -> None:
    """
    플랜 프리셋 적용 — 해당 플랜의 기능 세트로 CompanyFeature 일괄 갱신.
    기존 행은 enabled 값만 업데이트 (upsert 방식).
    """
    if plan not in PLAN_FEATURES:
        raise ValueError(f"알 수 없는 플랜: {plan}")

    enabled_keys = PLAN_FEATURES[plan]

    for key in ALL_FEATURES:
        row = db.query(CompanyFeature).filter(
            CompanyFeature.company_id == company_id,
            CompanyFeature.feature_key == key,
        ).first()
        if row:
            row.enabled = key in enabled_keys
        else:
            db.add(CompanyFeature(
                company_id=company_id,
                feature_key=key,
                enabled=key in enabled_keys,
            ))

    company = db.query(Company).filter(Company.id == company_id).first()
    if company:
        company.plan = plan

    db.commit()
    invalidate(company_id)


def toggle_feature(db: Session, key: str, enabled: bool, company_id: int = 1) -> None:
    """단일 기능 활성화/비활성화."""
    if key not in ALL_FEATURES:
        raise ValueError(f"알 수 없는 기능: {key}")

    row = db.query(CompanyFeature).filter(
        CompanyFeature.company_id == company_id,
        CompanyFeature.feature_key == key,
    ).first()

    if row:
        row.enabled = enabled
    else:
        # 행이 없다는 건 "기본값 = 전체 활성" 상태였던 것
        # 비활성화하려면 모든 행을 먼저 materialise해야 함
        _materialise_all(db, company_id)
        row = db.query(CompanyFeature).filter(
            CompanyFeature.company_id == company_id,
            CompanyFeature.feature_key == key,
        ).first()
        if row:
            row.enabled = enabled

    db.commit()
    invalidate(company_id)


def _materialise_all(db: Session, company_id: int) -> None:
    """
    CompanyFeature 행이 없을 때 (= 전체 활성 기본값 상태) 모든 기능을
    enabled=True 행으로 DB에 기록. 이후 개별 toggle이 가능해짐.
    """
    existing = {r.feature_key for r in db.query(CompanyFeature).filter(
        CompanyFeature.company_id == company_id
    ).all()}
    for key in ALL_FEATURES:
        if key not in existing:
            db.add(CompanyFeature(company_id=company_id, feature_key=key, enabled=True))
    db.commit()
