"""
테넌트 격리 유틸리티

모든 라우터에서 company_id 필터링에 사용:
    cid = get_company_id(user)
    db.query(Product).filter(Product.company_id == cid, ...)
"""
from app.models.user import User


def get_company_id(user: User) -> int:
    """
    현재 사용자의 effective company_id 반환.
    슈퍼어드민(company_id=None)은 1번 회사(블렌드펀치) 소속으로 처리.
    """
    return user.company_id if user.company_id is not None else 1
