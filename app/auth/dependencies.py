from fastapi import Request, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.auth.service import decode_token


class RequiresLogin(Exception):
    """Raised when a route needs an authenticated user but none is found."""


class InsufficientPermissions(Exception):
    """Raised when a user does not have the required role."""


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


def require_manager(user: User = Depends(get_current_user)) -> User:
    if user.role not in ("admin", "manager"):
        raise InsufficientPermissions()
    return user
