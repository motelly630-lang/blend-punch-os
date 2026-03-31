"""
기능 플래그 서비스 — 멀티테넌트 SaaS 구조

[권한 검사 우선순위]
  1. ALWAYS_ON    → 무조건 허용 (dashboard 등)
  2. 슈퍼어드민   → company_id=NULL + role=admin → 무조건 허용
  3. 회사 활성화  → Company.is_active=False → 전체 차단
  4. 기능 활성화  → CompanyFeature.enabled=False → 해당 기능 차단
  5. Role 레벨    → user.role < feature.min_role → 차단

[ContextVar]
  미들웨어가 요청마다 set_request_context()로 context를 설정하면
  Jinja2 global is_feature_enabled_for_current_user()가 DB 없이
  ContextVar만으로 기능 활성화 여부를 반환함.

[캐시]
  - company_features: 30s TTL (company_id 단위)
  - user→company_id: 60s TTL (username 단위)
"""
import time
import logging
from contextvars import ContextVar
from enum import Enum
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── ALWAYS_ON — feature 관리 대상에서 제외, 항상 활성화 ──────────────────────
ALWAYS_ON: frozenset[str] = frozenset({"dashboard"})

# ── Role 계층 ──────────────────────────────────────────────────────────────────
ROLE_LEVEL: dict[str, int] = {
    "admin":   30,
    "staff":   20,
    "manager": 20,   # legacy alias
    "partner": 10,
    "viewer":  5,    # legacy alias
}

# ── 전체 기능 정의 ────────────────────────────────────────────────────────────
# min_role: 회사에서 해당 기능이 활성화됐을 때 접근 가능한 최소 role
ALL_FEATURES: dict[str, dict] = {
    # OS 핵심
    "products":     {"name": "제품 관리",       "group": "os",       "tier": "basic", "min_role": "staff"},
    "brands":       {"name": "브랜드 관리",     "group": "os",       "tier": "basic", "min_role": "staff"},
    "influencers":  {"name": "인플루언서",      "group": "os",       "tier": "basic", "min_role": "staff"},
    "campaigns":    {"name": "캠페인",          "group": "os",       "tier": "basic", "min_role": "staff"},
    "proposals":    {"name": "제안서",          "group": "os",       "tier": "basic", "min_role": "partner"},
    "applications": {"name": "공구 신청 관리",  "group": "os",       "tier": "basic", "min_role": "staff"},
    "trends":       {"name": "트렌드",          "group": "os",       "tier": "basic", "min_role": "partner"},
    "trend_engine": {"name": "시즌 엔진",       "group": "os",       "tier": "pro",   "min_role": "staff"},
    "settlements":  {"name": "정산",            "group": "os",       "tier": "basic", "min_role": "staff"},
    "automation":   {"name": "자동화 센터",     "group": "os",       "tier": "pro",   "min_role": "admin"},
    "outreach":     {"name": "아웃리치",        "group": "os",       "tier": "pro",   "min_role": "staff"},
    "crm":          {"name": "CRM 파이프라인",  "group": "os",       "tier": "pro",   "min_role": "staff"},
    # 커머스
    "orders":       {"name": "주문 관리",       "group": "commerce", "tier": "basic", "min_role": "staff"},
    "sales_pages":  {"name": "판매 페이지",     "group": "commerce", "tier": "basic", "min_role": "admin"},
    "sellers":      {"name": "셀러 관리",       "group": "commerce", "tier": "pro",   "min_role": "admin"},
}

# ── 플랜 프리셋 ────────────────────────────────────────────────────────────────
PLAN_FEATURES: dict[str, set[str]] = {
    "beta": {
        "products", "brands",
    },
    "basic": {
        "products", "brands",
        "influencers", "campaigns", "proposals", "applications",
        "trends", "settlements",
        "orders", "sales_pages",
    },
    "pro": set(ALL_FEATURES.keys()),
}

# ── URL prefix → feature_key 매핑 (긴 prefix 먼저) ──────────────────────────
GATE_PATHS: list[tuple[str, str]] = [
    ("/trends/engine",         "trend_engine"),
    ("/products",              "products"),
    ("/brands",                "brands"),
    ("/influencers",           "influencers"),
    ("/campaigns",             "campaigns"),
    ("/proposals",             "proposals"),
    ("/applications",          "applications"),
    ("/trends",                "trends"),
    ("/settlements",           "settlements"),
    ("/automation",            "automation"),
    ("/outreach",              "outreach"),
    ("/crm",                   "crm"),
    ("/orders",                "orders"),
    ("/sales-pages",           "sales_pages"),
    ("/sellers",               "sellers"),
    ("/api/ai-proposal",       "proposals"),
    ("/api/ai-product",        "products"),
    ("/api/ai-playbook",       "campaigns"),
    ("/api/ai-dm",             "automation"),
    ("/api/ai-seller-content", "automation"),
    ("/api/ai-product-image",  "products"),
    ("/api/ai-influencer",     "influencers"),
    ("/api/ai-recommend",      "influencers"),
    ("/api/ai-product-chat",   "products"),
]

# ── 캐시 ──────────────────────────────────────────────────────────────────────
_feature_cache: dict[int, dict] = {}         # {company_id: {features, expires}}
_user_co_cache: dict[str, dict] = {}         # {username: {company_id, is_super, expires}}
FEATURE_CACHE_TTL = 30.0
USER_CACHE_TTL    = 60.0

# ── ContextVar — 현재 요청의 company 컨텍스트 ────────────────────────────────
_ctx_company_id:  ContextVar[int]  = ContextVar("ctx_company_id",  default=1)
_ctx_is_super:    ContextVar[bool] = ContextVar("ctx_is_super",    default=False)
_ctx_enabled:     ContextVar[Optional[frozenset]] = ContextVar("ctx_enabled", default=None)


def set_request_context(company_id: int, is_super: bool, enabled: frozenset) -> None:
    """미들웨어에서 요청마다 호출. Jinja2 global이 이 값을 사용."""
    _ctx_company_id.set(company_id)
    _ctx_is_super.set(is_super)
    _ctx_enabled.set(enabled)


def is_feature_enabled_for_current_user(key: str) -> bool:
    """Jinja2 global 함수 — DB 조회 없이 ContextVar에서 즉시 반환."""
    if key in ALWAYS_ON:
        return True
    if _ctx_is_super.get():
        return True
    enabled = _ctx_enabled.get()
    if enabled is None:
        return True   # 컨텍스트 미설정 = 개발환경 fallback
    return key in enabled


def is_super_admin_for_current_user() -> bool:
    """Jinja2 global 함수 — 수퍼어드민(company_id=None + role=admin) 여부."""
    return _ctx_is_super.get()


# ── DB 기반 함수 ──────────────────────────────────────────────────────────────

def invalidate(company_id: int = 1) -> None:
    _feature_cache.pop(company_id, None)


def invalidate_user(username: str) -> None:
    _user_co_cache.pop(username, None)


def get_enabled_features(db: Session, company_id: int) -> frozenset[str]:
    """DB에서 활성화된 feature_key set 반환 (캐시 우선). ALWAYS_ON 포함."""
    now = time.monotonic()
    cached = _feature_cache.get(company_id)
    if cached and now < cached["expires"]:
        return cached["features"]

    from app.models.feature_flag import CompanyFeature
    rows = db.query(CompanyFeature).filter(
        CompanyFeature.company_id == company_id,
        CompanyFeature.enabled == True,
    ).all()

    if rows:
        features = frozenset({r.feature_key for r in rows} | ALWAYS_ON)
    else:
        # 설정 없음 = 전체 활성 기본값
        features = frozenset(set(ALL_FEATURES.keys()) | ALWAYS_ON)

    _feature_cache[company_id] = {"features": features, "expires": now + FEATURE_CACHE_TTL}
    return features


def is_enabled(db: Session, key: str, company_id: int) -> bool:
    if key in ALWAYS_ON:
        return True
    return key in get_enabled_features(db, company_id)


def get_user_company(db: Session, username: str) -> tuple[int, bool]:
    """(company_id, is_super_admin) 반환 — 캐시 우선."""
    now = time.monotonic()
    cached = _user_co_cache.get(username)
    if cached and now < cached["expires"]:
        return cached["company_id"], cached["is_super"]

    from app.models.user import User
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        return 1, False

    is_super = (user.company_id is None and user.role == "admin")
    company_id = user.company_id if user.company_id is not None else 1

    _user_co_cache[username] = {
        "company_id": company_id,
        "is_super": is_super,
        "expires": now + USER_CACHE_TTL,
    }
    return company_id, is_super


def get_path_feature(path: str) -> Optional[str]:
    for prefix, key in GATE_PATHS:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            return key
    return None


# ── 접근 권한 검사 ─────────────────────────────────────────────────────────────

class AccessResult(Enum):
    ALLOWED          = "allowed"
    ALWAYS_ON        = "always_on"
    SUPER_ADMIN      = "super_admin"
    COMPANY_INACTIVE = "company_inactive"   # Company.is_active=False
    COMPANY_DISABLED = "company_disabled"   # CompanyFeature.enabled=False
    NO_COMPANY       = "no_company"         # company_id=NULL + not admin
    ROLE_DENIED      = "role_denied"        # role level 부족


def check_access(db: Session, user, key: str) -> AccessResult:
    """
    통합 접근 권한 검사. 우선순위 순서대로 검사.

    Parameters
    ----------
    user : app.models.user.User
    key  : feature key (e.g. "products")
    """
    # 1. ALWAYS_ON
    if key in ALWAYS_ON:
        return AccessResult.ALWAYS_ON

    # 2. 슈퍼어드민 (company_id=NULL + admin)
    if user.company_id is None and user.role == "admin":
        return AccessResult.SUPER_ADMIN

    # 3. 회사 없는 일반 사용자
    if user.company_id is None:
        return AccessResult.NO_COMPANY

    # 4. 회사 활성화 여부
    from app.models.feature_flag import Company
    company = db.query(Company).filter(Company.id == user.company_id).first()
    if not company or not company.is_active:
        return AccessResult.COMPANY_INACTIVE

    # 5. 기능 활성화 여부 (회사 레벨)
    if not is_enabled(db, key, user.company_id):
        return AccessResult.COMPANY_DISABLED

    # 6. Role 레벨
    feature_def = ALL_FEATURES.get(key, {})
    min_role = feature_def.get("min_role", "partner")
    user_level     = ROLE_LEVEL.get(user.role, 0)
    required_level = ROLE_LEVEL.get(min_role, 10)
    if user_level < required_level:
        return AccessResult.ROLE_DENIED

    return AccessResult.ALLOWED


def is_access_allowed(result: AccessResult) -> bool:
    return result in (AccessResult.ALLOWED, AccessResult.ALWAYS_ON, AccessResult.SUPER_ADMIN)


# ── Company 헬퍼 ──────────────────────────────────────────────────────────────

def get_or_create_default_company(db: Session):
    """id=1 기본 회사 보장 (기존 단일테넌트 호환)."""
    from app.models.feature_flag import Company
    company = db.query(Company).filter(Company.id == 1).first()
    if not company:
        company = Company(id=1, name="BLEND PUNCH", plan="pro", is_active=True)
        db.add(company)
        db.commit()
        db.refresh(company)
    return company


def apply_plan(db: Session, plan: str, company_id: int) -> None:
    """플랜 프리셋 일괄 적용."""
    if plan not in PLAN_FEATURES:
        raise ValueError(f"알 수 없는 플랜: {plan}")

    from app.models.feature_flag import Company, CompanyFeature
    enabled_keys = PLAN_FEATURES[plan]

    for key in ALL_FEATURES:
        row = db.query(CompanyFeature).filter(
            CompanyFeature.company_id == company_id,
            CompanyFeature.feature_key == key,
        ).first()
        if row:
            row.enabled = (key in enabled_keys)
        else:
            db.add(CompanyFeature(
                company_id=company_id,
                feature_key=key,
                enabled=(key in enabled_keys),
            ))

    company = db.query(Company).filter(Company.id == company_id).first()
    if company:
        company.plan = plan
    db.commit()
    invalidate(company_id)


def toggle_feature(db: Session, key: str, enabled: bool, company_id: int) -> None:
    """단일 기능 활성화/비활성화."""
    if key not in ALL_FEATURES:
        raise ValueError(f"알 수 없는 기능: {key}")

    from app.models.feature_flag import CompanyFeature
    row = db.query(CompanyFeature).filter(
        CompanyFeature.company_id == company_id,
        CompanyFeature.feature_key == key,
    ).first()

    if row:
        row.enabled = enabled
    else:
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
    """CompanyFeature 행이 없을 때 전체 기능을 enabled=True로 기록."""
    from app.models.feature_flag import CompanyFeature
    existing = {r.feature_key for r in db.query(CompanyFeature).filter(
        CompanyFeature.company_id == company_id
    ).all()}
    for key in ALL_FEATURES:
        if key not in existing:
            db.add(CompanyFeature(company_id=company_id, feature_key=key, enabled=True))
    db.commit()
