from fastapi import Request, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.auth.service import decode_token


class RequiresLogin(Exception):
    """Raised when a route needs an authenticated user but none is found."""


class InsufficientPermissions(Exception):
    """Raised when a user does not have the required role."""


class FeatureDisabled(Exception):
    """회사에서 비활성화된 기능에 접근 시도."""
    def __init__(self, key: str = ""):
        self.key = key


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise RequiresLogin()
    payload = decode_token(token)
    if not payload:
        raise RequiresLogin()
    username = payload.get("sub")
    if not username:
        raise RequiresLogin()
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if not user:
        raise RequiresLogin()
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise InsufficientPermissions()
    return user


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    """수퍼어드민 전용 — company_id=None + role=admin (블렌드펀치 계정만 허용)."""
    if user.company_id is not None or user.role != "admin":
        raise InsufficientPermissions()
    return user


def require_manager(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("admin", "manager"):
        raise InsufficientPermissions()
    return user


def require_staff(user: User = Depends(get_current_user)) -> User:
    """Admin or Staff (or legacy manager)."""
    if user.role not in ("admin", "staff", "manager"):
        raise InsufficientPermissions()
    return user


def require_partner(user: User = Depends(get_current_user)) -> User:
    """Any authenticated user — all roles allowed."""
    return user  # get_current_user already validates login


def require_feature(key: str):
    """
    FastAPI dependency factory — 기능 플래그 + role 동시 검사.

    사용법:
        @router.get("/products")
        def products_list(user: User = Depends(require_feature("products"))):
            ...

    검사 순서 (app/services/feature_flags.py check_access 참조):
        ALWAYS_ON → 슈퍼어드민 → 회사 활성화 → 기능 활성화 → role
    """
    def dep(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        from app.services.feature_flags import check_access, AccessResult
        result = check_access(db, user, key)
        if result in (
            AccessResult.COMPANY_INACTIVE,
            AccessResult.COMPANY_DISABLED,
            AccessResult.NO_COMPANY,
        ):
            raise FeatureDisabled(key)
        if result == AccessResult.ROLE_DENIED:
            raise InsufficientPermissions()
        return user
    return dep
