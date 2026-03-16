"""
One-time data fix script:
1. Recalculate actual_revenue for campaigns where sales > 0 but revenue = 0
   (uses unit_price, or product.groupbuy_price, or product.consumer_price as fallback)
2. Recalculate seller/vendor commission amounts
3. Sync KST-based status to DB (planning/active/completed)
4. Create missing settlements for completed campaigns with influencers

Run: uv run python scripts/fix_campaign_data.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, date
from zoneinfo import ZoneInfo
from app.database import SessionLocal
from app.models import Campaign, Product, Influencer
from app.models.settlement import Settlement

KST = ZoneInfo("Asia/Seoul")


def kst_today() -> date:
    return datetime.now(KST).date()


def auto_status(c, today):
    if c.status == "cancelled":
        return "cancelled"
    if c.start_date and c.end_date:
        if today < c.start_date:
            return "planning"
        elif today <= c.end_date:
            return "active"
        else:
            return "completed"
    if c.start_date and today >= c.start_date:
        return "active"
    return c.status


def fix():
    db = SessionLocal()
    today = kst_today()
    fixed_revenue = 0
    fixed_status = 0
    created_settlements = 0

    try:
        campaigns = db.query(Campaign).all()
        print(f"총 캠페인: {len(campaigns)}개")

        for c in campaigns:
            changed = False

            # 1. Status sync
            new_status = auto_status(c, today)
            if c.status != new_status:
                print(f"  상태 변경: [{c.name}] {c.status} → {new_status}")
                c.status = new_status
                fixed_status += 1
                changed = True

            # 2. Revenue recalculation
            # Only fix if actual_revenue is 0/None but actual_sales > 0
            if (not c.actual_revenue or c.actual_revenue == 0) and (c.actual_sales and c.actual_sales > 0):
                price = c.unit_price or 0
                # Fallback to product prices
                if not price and c.product_id:
                    p = db.query(Product).filter_by(id=c.product_id).first()
                    if p:
                        price = p.groupbuy_price or p.consumer_price or p.price or 0
                if price:
                    c.actual_revenue = c.actual_sales * price
                    print(f"  매출 계산: [{c.name}] {c.actual_sales}개 × ₩{price:,.0f} = ₩{c.actual_revenue:,.0f}")
                    fixed_revenue += 1
                    changed = True

            # 3. Commission amounts
            if c.actual_revenue and c.actual_revenue > 0:
                seller_rate = c.seller_commission_rate or c.commission_rate or 0.0
                vendor_rate = c.vendor_commission_rate or 0.0
                new_seller_amt = round(c.actual_revenue * seller_rate)
                new_vendor_amt = round(c.actual_revenue * vendor_rate)
                if c.seller_commission_amount != new_seller_amt or c.vendor_commission_amount != new_vendor_amt:
                    c.seller_commission_amount = new_seller_amt
                    c.vendor_commission_amount = new_vendor_amt
                    changed = True

        db.commit()
        print(f"\n상태 수정: {fixed_status}건, 매출 계산: {fixed_revenue}건")

        # 4. Create missing settlements for completed campaigns
        completed = db.query(Campaign).filter(
            Campaign.status == "completed",
            Campaign.influencer_id.isnot(None),
        ).all()

        existing_campaign_ids = {
            row[0] for row in db.query(Settlement.campaign_id).filter(Settlement.campaign_id.isnot(None)).all()
        }

        for c in completed:
            if c.id in existing_campaign_ids:
                continue
            inf = db.query(Influencer).filter_by(id=c.influencer_id).first()
            seller_rate = c.seller_commission_rate or c.commission_rate or 0.0
            commission_amt = round((c.actual_revenue or 0) * seller_rate)
            tax_rate = 0.033 if (inf and getattr(inf, 'business_type', None) == "프리랜서") else 0.0
            tax_amt = round(commission_amt * tax_rate)
            s = Settlement(
                influencer_id=c.influencer_id,
                campaign_id=c.id,
                period_label=(c.end_date.strftime("%Y년 %m월") if c.end_date else datetime.now().strftime("%Y년 %m월")),
                seller_type=(getattr(inf, 'business_type', None) or "사업자") if inf else "사업자",
                sales_amount=c.actual_revenue or 0,
                commission_rate=seller_rate,
                commission_amount=commission_amt,
                tax_rate=tax_rate,
                tax_amount=tax_amt,
                final_payment=commission_amt - tax_amt,
                status="pending",
                notes="데이터 수정 스크립트로 자동 생성",
            )
            db.add(s)
            created_settlements += 1
            print(f"  정산 생성: [{c.name}] 커미션 ₩{commission_amt:,.0f}")

        db.commit()
        print(f"\n정산 생성: {created_settlements}건")
        print("\n✅ 완료!")

    except Exception as e:
        db.rollback()
        print(f"❌ 오류: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    fix()
