"""협력사 포털 접근 컨텍스트 — 협력사 본인 / 내부 관리자 미리보기 공용.

두 가지 접근을 하나의 컨텍스트로 통일한다:
  1. role=="partner"  — 자기 partner_id 로 고정. 쓰기(답변·CS등록) 가능.
  2. 내부 직원(admin/staff/manager) — 협력사를 골라서 포털을 그대로 미리보기.
     **보기 전용**: 협력사 이름으로 답변·CS가 남지 않도록 모든 쓰기를 차단한다.

선택한 협력사는 쿠키(portal_as)에 담아 포털 내 모든 링크에서 유지된다.
"""
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth.dependencies import get_current_user, InsufficientPermissions
from app.auth.tenant import get_company_id
from app.models.partner import Partner
from app.models.user import User

PORTAL_AS_COOKIE = "portal_as"
STAFF_ROLES = ("admin", "staff", "manager")


@dataclass
class PortalCtx:
    """포털 화면 1건을 그리는 데 필요한 최소 컨텍스트."""

    request: Request
    db: Session
    user: User
    partner: Partner | None
    is_admin_view: bool

    @property
    def partner_id(self) -> str | None:
        return self.partner.id if self.partner else None

    @property
    def readonly(self) -> bool:
        """내부 직원 미리보기는 언제나 보기 전용."""
        return self.is_admin_view

    @property
    def company_id(self) -> int:
        return get_company_id(self.user)

    def tpl(self, **extra) -> dict:
        """portal_base.html 이 요구하는 공통 변수 + 화면별 추가 변수."""
        ctx = {
            "request": self.request,
            "user": self.user,
            "partner": self.partner,
            "admin_view": self.is_admin_view,
            "readonly": self.readonly,
            "switch_partners": switchable_partners(self.db, self.user) if self.is_admin_view else [],
        }
        ctx.update(extra)
        return ctx


def switchable_partners(db: Session, user: User):
    """내부 직원이 미리보기로 전환할 수 있는 협력사 목록 (같은 회사, 활성)."""
    return (
        db.query(Partner)
        .filter(Partner.company_id == get_company_id(user), Partner.is_active == True)
        .order_by(Partner.name)
        .all()
    )


def require_portal_access(user: User = Depends(get_current_user)) -> User:
    """포털 진입 허용 role — 협력사 담당자 + 내부 직원(미리보기)."""
    if user.role != "partner" and user.role not in STAFF_ROLES:
        raise InsufficientPermissions()
    return user


def portal_context(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_portal_access),
) -> PortalCtx:
    """현재 요청의 포털 컨텍스트를 만든다.

    협력사 계정은 자기 협력사로 고정되고, 내부 직원은 ?as= 또는 쿠키로 고른 협력사를 본다.
    (고르지 않았거나 잘못된 id 면 partner=None → 라우터가 선택 화면으로 보낸다)
    """
    if user.role == "partner":
        partner = (
            db.query(Partner).filter(Partner.id == user.partner_id).first()
            if user.partner_id else None
        )
        return PortalCtx(request=request, db=db, user=user, partner=partner, is_admin_view=False)

    pid = request.query_params.get("as") or request.cookies.get(PORTAL_AS_COOKIE)
    partner = None
    if pid:
        # 다른 회사 협력사는 볼 수 없다 (쿠키 위조 방지)
        partner = (
            db.query(Partner)
            .filter(Partner.id == pid, Partner.company_id == get_company_id(user))
            .first()
        )
    return PortalCtx(request=request, db=db, user=user, partner=partner, is_admin_view=True)
