"""CS 번호 채번 — 내부(/cs)와 협업사 포털(/portal/cs) 등록에서 공용."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.cs import CSTicket


def gen_cs_number(db: Session, cid: int) -> str:
    """CS-YYYYMMDD-#### (회사별·일자별 순번). 동시성은 1차 범위에서 재조회로 충분."""
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"CS-{today}-"
    last = (
        db.query(CSTicket)
        .filter(CSTicket.company_id == cid, CSTicket.cs_number.like(prefix + "%"))
        .order_by(CSTicket.cs_number.desc())
        .first()
    )
    seq = 1
    if last and last.cs_number.startswith(prefix):
        try:
            seq = int(last.cs_number.split("-")[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}{seq:04d}"
