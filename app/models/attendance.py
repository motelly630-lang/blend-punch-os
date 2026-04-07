import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Date, ForeignKey
from app.models.base import Base


class AttendanceLog(Base):
    __tablename__ = "attendance_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)          # 날짜 (KST 기준)
    first_login_at = Column(DateTime, nullable=True)         # 당일 첫 로그인 시각
    last_logout_at = Column(DateTime, nullable=True)         # 마지막 로그아웃 시각 (버튼 클릭만)
