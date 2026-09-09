from app.models.user import User
from app.models.product import Product
from app.models.influencer import Influencer
from app.models.campaign import Campaign
from app.models.proposal import Proposal
from app.models.settlement import Settlement
from app.models.trend import TrendItem
from app.models.playbook import Playbook
from app.models.trend_engine import TrendBriefing
from app.models.outreach import OutreachLog
from app.models.crm import CrmPipeline, SampleLog
from app.models.automation import AutomationNote, CampaignRecommendation
from app.models.brand import Brand
from app.models.group_buy_application import GroupBuyApplication
from app.models.transaction import Transaction
from app.models.sourcing_batch import SourcingBatch
from app.models.partner import Partner, PartnerContact
# companies 는 거의 모든 테이블이 company_id 로 참조한다 — 여기서 안 불러오면
# 스크립트에서 모델만 임포트했을 때 flush 시 NoReferencedTableError 가 난다
from app.models.feature_flag import Company, CompanyFeature
from app.models.sheet_sync_log import SheetSyncLog
from app.models.cs import (
    CSTicket, CSActivity, CSAttachment, CSType, CSGuide, CSTemplate, CSNotification, CSDownloadLog,
)

__all__ = ["User", "Product", "Influencer", "Campaign", "Proposal", "Settlement", "TrendItem", "Playbook", "TrendBriefing", "OutreachLog", "CrmPipeline", "SampleLog", "AutomationNote", "CampaignRecommendation", "Brand", "GroupBuyApplication", "Transaction", "SourcingBatch", "Partner", "PartnerContact", "Company", "CompanyFeature", "SheetSyncLog", "CSTicket", "CSActivity", "CSAttachment", "CSType", "CSGuide", "CSTemplate", "CSNotification", "CSDownloadLog"]
