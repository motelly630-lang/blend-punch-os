import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, ForeignKey

from app.models.base import Base


class SourcingBatch(Base):
    """One product-sourcing upload (Excel/PDF) and its pipeline run.

    Status flow:
      uploaded → extracting → extracted → priced → researched
                → review → synced → done | failed
    """

    __tablename__ = "sourcing_batches"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=True, default=1, index=True)

    source_filename = Column(String(300), nullable=True)
    source_path = Column(String(500), nullable=True)
    file_type = Column(String(10), nullable=True)            # xlsx|pdf|csv

    status = Column(String(20), default="uploaded", index=True)
    total_rows = Column(Integer, default=0)
    extracted_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    error_log = Column(JSON, nullable=True)                  # list[{row, message}]

    sheet_url = Column(Text, nullable=True)
    synced_at = Column(DateTime, nullable=True)

    created_by = Column(String(36), nullable=True)          # users.id (VARCHAR uuid) — soft ref
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
