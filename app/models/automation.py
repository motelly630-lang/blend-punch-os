import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from app.models.base import Base


class AutomationNote(Base):
    """Saved output from automation center (not linked to a campaign)."""
    __tablename__ = "automation_notes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    module = Column(String(50), nullable=False)          # playbook|dm|seller_recommend|etc
    title = Column(String(300), nullable=True)
    content = Column(Text, nullable=False)
    product_id = Column(String(36), ForeignKey("products.id"), nullable=True)
    product_name = Column(String(300), nullable=True)    # snapshot
    created_at = Column(DateTime, default=datetime.utcnow)


class CampaignRecommendation(Base):
    """Seller recommendation linked to a specific campaign."""
    __tablename__ = "campaign_recommendations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    campaign_id = Column(String(36), ForeignKey("campaigns.id"), nullable=False)
    influencer_id = Column(String(36), ForeignKey("influencers.id"), nullable=False)
    score = Column(String(10), nullable=True)            # e.g. "87.4"
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
