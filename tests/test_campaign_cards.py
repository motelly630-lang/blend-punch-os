"""캠페인 목록 — 3열 카드 + 빠른 수정은 화면 가운데 창 (2026-09-30).
수정을 누르면 카드가 '두 칸 차지'로 바뀌어 한 줄 목록에 없던 칸이 생기고 옆 카드가 세로로 찌그러지던 문제 방지."""
from tests import _env  # noqa: F401
from tests._env import SessionLocal, client_for, make_user, seed_companies, uid

import unittest
from datetime import date, timedelta

from app.models.campaign import Campaign


class CampaignCardListTests(unittest.TestCase):
    def test_cards_grid_and_modal_edit(self):
        seed_companies()
        db = SessionLocal()
        c = Campaign(company_id=1, name=f"카드시험 {uid()}", product_name_manual="빠른등록 제품", status="active",
                     start_date=date.today() - timedelta(days=1), end_date=date.today() + timedelta(days=2))
        db.add(c)
        db.commit()
        cid = c.id
        db.close()
        html = client_for(make_user("admin", company_id=1)).get("/campaigns").text
        self.assertIn('id="camp-list"', html)
        self.assertIn("xl:grid-cols-3", html)
        self.assertNotIn("editing ? 'lg:col-span-2'", html, "수정 중 카드가 칸을 넓히면 목록이 찌그러짐")
        row = html[html.index(f'data-camp="{cid}"'):]
        row = row[: row.index('class="camp-row', 10)] if 'class="camp-row' in row[10:] else row
        self.assertIn('class="fixed inset-0', row, "빠른 수정은 떠 있는 창")
        self.assertIn("/inline-update", html)
        self.assertIn("빠른등록 제품", row)
        self.assertIn(f'href="/campaigns/{cid}"', row)
        # 빠른 등록처럼 제품 연결이 없으면 '채울 것' 표시 + 필터·한 줄 보기 버튼
        self.assertIn('data-todo="1"', row)
        self.assertIn("제품 연결", row)
        self.assertIn('id="camp-todo-btn"', html)
        self.assertIn('id="btn-rows-view"', html)

    def test_complete_campaign_has_no_todo(self):
        from app.models import Product
        from app.models.influencer import Influencer
        seed_companies()
        db = SessionLocal()
        p = Product(company_id=1, name=f"사진제품 {uid()}", brand="b", category="기타", status="active",
                    product_image="/uploads/products/x.jpg")
        i = Influencer(company_id=1, name=f"인플 {uid()}", platform="instagram", handle="@x")
        db.add_all([p, i])
        db.flush()
        c = Campaign(company_id=1, name="완전한 캠페인", product_id=p.id, influencer_id=i.id, status="planning",
                     start_date=date.today() + timedelta(days=3), end_date=date.today() + timedelta(days=9))
        db.add(c)
        db.commit()
        cid = c.id
        db.close()
        html = client_for(make_user("admin", company_id=1)).get("/campaigns").text
        row = html[html.index(f'data-camp="{cid}"'):]
        row = row[: row.index('class="camp-row', 10)] if 'class="camp-row' in row[10:] else row
        self.assertIn('data-todo="0"', row)
        self.assertIn('src="/uploads/products/x.jpg"', row)


if __name__ == "__main__":
    unittest.main()
