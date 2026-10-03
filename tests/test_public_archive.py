"""공개 공구 아카이브(/public/archive) — 직원이 공개 체크한 영상만, 공개해도 되는 칸만 나간다.

- 기본 비공개 · 공개 체크 후에만 노출 · 링크를 빼면 같이 사라짐
- 다른 회사 공구·보관/취소 공구·다른 회사 제품/인플루언서 연결은 노출 안 됨
- 커미션·매출·메모·실명·연락처·계좌는 목록·상세 어디에도 없음
- 숫자(조회수·좋아요·댓글)는 직원이 직접 입력
"""
from tests import _env  # noqa: F401  (app 보다 먼저)
from tests._env import SessionLocal, client_for, make_user, seed_companies, uid

import io
import unittest
from datetime import timedelta

from app.models import Influencer, Product
from app.models.campaign import ArchiveContent, Campaign
from app.routers import public
from app.routers.campaigns import _kst_today
from app.services import public_archive


def _reel():
    return f"https://www.instagram.com/reel/Arc{uid()}/"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed_companies()
        cls.staff = client_for(make_user("staff", company_id=1))
        cls.other_staff = client_for(make_user("staff", company_id=2))
        cls.anon = client_for()

    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def camp(self, s=-1, e=3, company_id=1, product=None, influencer=None, urls=None, **kw):
        t = _kst_today()
        c = Campaign(name="내부공구명" + uid(), company_id=company_id,
                     start_date=t + timedelta(s) if s is not None else None,
                     end_date=t + timedelta(e) if e is not None else None, status="active",
                     product_id=product.id if product else None, influencer_id=influencer.id if influencer else None,
                     content_urls=urls if urls is not None else [_reel()], **kw)
        self.db.add(c)
        self.db.commit()
        return c

    def product(self, company_id=1, **kw):
        base = dict(name=f"가상 아카이브 제품 {uid()}", brand=f"가상브랜드{uid()}", category="식품/음료", status="active",
                    visibility_status="active", company_id=company_id, groupbuy_price=19900,
                    seller_commission_rate=0.37, supplier_price=4321, product_image="/static/og-image.png")
        base.update(kw)
        p = Product(**base)
        self.db.add(p)
        self.db.commit()
        return p

    def influencer(self, company_id=1, **kw):
        base = dict(name="실명비공개" + uid(), platform="instagram", handle=f"@gasang_{uid()}", company_id=company_id,
                    contact_phone="010-9999-8888", contact_email="secret@example.com", account_number="111-222-333333",
                    profile_image="/static/og-image.png")
        base.update(kw)
        i = Influencer(**base)
        self.db.add(i)
        self.db.commit()
        return i

    def publish(self, c, url=None, client=None, **form):
        data = {"url": url or c.content_urls[0], "is_public": "1"}
        data.update(form)
        return (client or self.staff).post(f"/campaigns/{c.id}/links/archive", data=data)

    def row(self, c):
        self.db.expire_all()
        return self.db.query(ArchiveContent).filter(ArchiveContent.campaign_id == c.id).first()


class PublishFlowTests(Base):
    def test_기본_비공개_체크하면_공개_빼면_사라짐(self):
        p = self.product()
        c = self.camp(product=p)
        self.assertNotIn(p.name, self.anon.get("/public/archive").text, "링크만 넣은 상태는 비공개")

        r = self.publish(c, views="12,345", likes="678", comments="9")
        self.assertIn("msg=", r.headers["location"])
        row = self.row(c)
        self.assertEqual((row.is_public, row.views, row.likes, row.comments, row.company_id), (True, 12345, 678, 9, 1))
        page = self.anon.get("/public/archive")
        self.assertEqual(page.status_code, 200)
        self.assertIn(p.name, page.text)
        self.assertIn("1.2만", page.text, "조회수 표시")

        self.publish(c, is_public="")          # 체크 해제 → 비공개
        self.assertNotIn(p.name, self.anon.get("/public/archive").text)

        self.publish(c)
        self.staff.post(f"/campaigns/{c.id}/links/remove", data={"url": c.content_urls[0]})
        self.assertIsNone(self.row(c), "링크를 빼면 아카이브 정보도 지움")
        self.assertNotIn(p.name, self.anon.get("/public/archive").text)

    def test_목록에_없는_링크_잘못된_숫자는_거부(self):
        c = self.camp()
        r = self.publish(c, url=_reel())
        self.assertIn("err=", r.headers["location"])
        r = self.publish(c, views="-5")
        self.assertIn("err=", r.headers["location"])
        r = self.publish(c, likes="열개")
        self.assertIn("err=", r.headers["location"])
        self.assertIsNone(self.row(c))

    def test_다른_회사_직원은_설정_못함(self):
        c = self.camp()
        r = self.publish(c, client=self.other_staff)
        self.assertEqual(r.headers["location"], "/campaigns")
        self.assertIsNone(self.row(c))

    def test_썸네일_업로드(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (40, 50), (120, 80, 40)).save(buf, "PNG")
        c = self.camp()
        r = self.staff.post(f"/campaigns/{c.id}/links/archive",
                            data={"url": c.content_urls[0], "is_public": "1"},
                            files={"thumbnail": ("t.png", buf.getvalue(), "image/png")})
        self.assertIn("msg=", r.headers["location"])
        thumb = self.row(c).thumbnail
        self.assertTrue(thumb and thumb.startswith(("/static/uploads/archive/", "http")), thumb)
        self.assertIn(thumb, self.anon.get("/public/archive").text)
        self.publish(c, remove_thumbnail="1")
        self.assertIsNone(self.row(c).thumbnail)

    def test_공구_상세에_설정칸(self):
        c = self.camp()
        self.publish(c)
        page = self.staff.get(f"/campaigns/{c.id}").text
        self.assertIn("/links/archive", page)
        self.assertIn("공개 중", page)
        self.assertIn(f"/public/archive/{self.row(c).id}", page, "공개 중이면 공개 화면 링크")
        self.assertIn('href="/public/archive"', self.staff.get("/campaigns/gallery").text, "사내 아카이브에 공개 아카이브 링크")


class VisibilityTests(Base):
    def test_내부_정보는_목록_상세_어디에도_없음(self):
        p = self.product()
        inf = self.influencer()
        c = self.camp(product=p, influencer=inf, notes="내부메모-노출금지", commission_rate=0.33,
                      seller_commission_rate=0.37, vendor_commission_rate=0.21, actual_revenue=9876543, unit_price=15500)
        self.publish(c, views="100")
        item_id = self.row(c).id
        for url in ("/public/archive", f"/public/archive/{item_id}", f"/public/archive?q={inf.handle.lstrip('@')}"):
            html = self.anon.get(url).text
            self.assertIn(inf.handle.lstrip("@"), html, url)
            for secret in ("내부메모-노출금지", "9876543", "9,876,543", "37%", "33%", "21%", "4,321",
                           inf.name, "010-9999-8888", "secret@example.com", "111-222-333333", c.name, "커미션"):
                self.assertNotIn(secret, html, f"{url} 에 {secret} 노출")

    def test_공개_데이터_틀에_내부_칸_없음(self):
        fields = set(public_archive.PublicArchiveItem.__dataclass_fields__)
        for bad in ("commission_rate", "seller_commission_rate", "vendor_commission_rate", "actual_revenue",
                    "notes", "unit_price", "name", "influencer_name", "contact_phone", "account_number"):
            self.assertNotIn(bad, fields)
        self.assertEqual(public_archive.PUBLIC_COMPANY_ID, public.PUBLIC_COMPANY_ID)

    def test_다른_회사_보관_취소_공구는_안나감(self):
        mine = self.camp(product_name_manual="우리공구" + uid())
        other = self.camp(company_id=2, product_name_manual="타사공구" + uid())
        archived = self.camp(is_archived=True, product_name_manual="보관공구" + uid())
        cancelled = self.camp(product_name_manual="취소공구" + uid())
        for c in (mine, archived, cancelled):
            self.publish(c)
        # 다른 회사 공구에 공개 행이 (잘못) 생겨도 안 나가야 함
        self.db.add(ArchiveContent(company_id=2, campaign_id=other.id, url=other.content_urls[0], is_public=True))
        cancelled.status = "cancelled"
        self.db.commit()
        html = self.anon.get("/public/archive").text
        self.assertIn(mine.product_name_manual, html)
        for c in (other, archived, cancelled):
            self.assertNotIn(c.product_name_manual, html)

    def test_다른_회사_제품_인플루언서_연결은_숨김(self):
        p2 = self.product(company_id=2, name="타사제품노출금지" + uid())
        i2 = self.influencer(company_id=2, handle="other_co_handle_" + uid())
        c = self.camp(product=p2, influencer=i2, product_name_manual="직접입력이름" + uid())
        self.publish(c)
        html = self.anon.get(f"/public/archive/{self.row(c).id}").text
        self.assertNotIn(p2.name, html)
        self.assertNotIn(i2.handle, html)
        self.assertIn(c.product_name_manual, html)

    def test_숨김_제품도_사진_이름_브랜드는_보이고_카탈로그_링크만_없음(self):
        # 대표님 결정 2026-10-03: 아카이브에서는 숨김 제품도 사진·이름·브랜드를 보여준다
        p = self.product(visibility_status="hidden", product_image="/static/hidden-product.png")
        c = self.camp(product=p)
        self.publish(c)
        html = self.anon.get(f"/public/archive/{self.row(c).id}").text
        self.assertIn(p.name, html)
        self.assertIn(p.brand, html)
        self.assertIn("/static/hidden-product.png", html)
        self.assertNotIn(f"/public/products/product/{p.id}", html, "숨김 제품 카탈로그 링크는 튕기므로 안 붙임")

    def test_비공개_상세주소는_목록으로(self):
        c = self.camp()
        self.publish(c, is_public="")
        r = self.anon.get(f"/public/archive/{self.row(c).id}")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["location"], "/public/archive")

    def test_유튜브_주소는_정리해서_내보냄(self):
        bad = "javascript:alert(1)//youtube.com/shorts/abcDEF12345"
        c = self.camp(urls=[bad])
        self.publish(c, url=bad)
        html = self.anon.get(f"/public/archive/{self.row(c).id}").text
        self.assertNotIn("javascript:", html)
        self.assertIn("https://www.youtube.com/watch?v=abcDEF12345", html)


class ListTests(Base):
    def test_탭_검색_필터_정렬(self):
        tag = uid()
        live = self.camp(-1, 3, product_name_manual=f"진행{tag}", category_manual=f"카테{tag}")
        soon = self.camp(5, 9, product_name_manual=f"예정{tag}")
        done = self.camp(-20, -10, product_name_manual=f"종료{tag}",
                         urls=[f"https://www.instagram.com/p/Post{uid()}/"])
        self.publish(live, views="10")
        self.publish(soon, views="30")
        self.publish(done, views="20")
        g = lambda qs: self.anon.get("/public/archive?" + qs).text
        a = g("tab=live&q=" + tag)
        self.assertIn(f"진행{tag}", a); self.assertNotIn(f"예정{tag}", a); self.assertNotIn(f"종료{tag}", a)
        self.assertIn(f"예정{tag}", g("tab=soon&q=" + tag))
        d = g("tab=done&q=" + tag)
        self.assertIn(f"종료{tag}", d); self.assertIn("종료", d)
        self.assertIn(f"종료{tag}", g(f"type=post&q={tag}"))
        self.assertNotIn(f"진행{tag}", g(f"type=post&q={tag}"))
        self.assertIn(f"진행{tag}", g(f"cat=카테{tag}"))
        v = g("sort=views&q=" + tag)
        self.assertLess(v.index(f"예정{tag}"), v.index(f"종료{tag}"))
        self.assertLess(v.index(f"종료{tag}"), v.index(f"진행{tag}"))
        for qs in ("tab=<script>", "type=zzz", "sort=commission", "cat=없는카테고리", "page=999", "page=-3"):
            self.assertEqual(self.anon.get("/public/archive?" + qs).status_code, 200, qs)

    def test_같은_제품_영상_모아보기(self):
        p = self.product()
        a = self.camp(product=p)
        b = self.camp(product=p)
        self.publish(a)
        self.publish(b)
        html = self.anon.get(f"/public/archive/{self.row(a).id}").text
        self.assertIn("같은 제품 영상 2개", html)
        self.assertIn(f"/public/archive/{self.row(b).id}", html)
        self.assertIn("영상 2개", self.anon.get("/public/archive?q=" + p.name).text)

    def test_로그인_없이_열림(self):
        r = self.anon.get("/public/archive")
        self.assertEqual(r.status_code, 200)
        self.assertIn("공구 아카이브", r.text)


class ReviewFixTests(Base):
    """독립 리뷰(2026-10-03) 지적 사항."""

    def test_페이지_탭_칩_링크가_현재_조건을_유지(self):
        tag = uid()
        cat = f"유지카테{tag}"
        for _ in range(26):                       # 2쪽이 생기게
            c = self.camp(product_name_manual=f"유지{tag}", category_manual=cat)
            self.publish(c)
        html = self.anon.get(f"/public/archive?tab=live&cat={cat}&type=reel&sort=views&q={tag}").text
        import html as _h
        from urllib.parse import parse_qs, urlsplit
        hrefs = [_h.unescape(h) for h in __import__("re").findall(r'href="(/public/archive\?[^"]+)"', html)]
        page2 = [h for h in hrefs if "page=2" in h]
        self.assertTrue(page2, "2쪽 링크가 있어야")
        q = parse_qs(urlsplit(page2[0]).query)
        self.assertEqual((q["tab"], q["cat"], q["type"], q["sort"], q["q"]), (["live"], [cat], ["reel"], ["views"], [tag]))
        soon = [h for h in hrefs if "tab=soon" in h][0]
        self.assertIn(f"q={tag}", soon)
        self.assertNotIn("page=", soon, "탭을 바꾸면 1쪽부터")

    def test_이미지가_아닌_썸네일은_거부(self):
        c = self.camp()
        r = self.staff.post(f"/campaigns/{c.id}/links/archive", data={"url": c.content_urls[0], "is_public": "1"},
                            files={"thumbnail": ("photo.heic", b"not really an image", "image/heic")})
        self.assertIn("err=", r.headers["location"])
        self.assertIsNone(self.row(c), "실패하면 아무것도 저장하지 않음")

    def test_긴_유튜브_주소는_영상번호_주소로_저장(self):
        long_url = "https://www.youtube.com/watch?v=abcDEF12345&" + "utm_x=" + "z" * 600
        c = self.camp(urls=[long_url])
        r = self.publish(c, url=long_url)
        self.assertIn("msg=", r.headers["location"])
        self.assertEqual(self.row(c).url, "https://www.youtube.com/watch?v=abcDEF12345")
        self.assertIn("공개 중", self.staff.get(f"/campaigns/{c.id}").text, "공구 상세에서도 같은 영상으로 인식")
        self.staff.post(f"/campaigns/{c.id}/links/remove", data={"url": long_url})
        self.assertIsNone(self.row(c))

    def test_이상한_페이지_값도_정상_화면(self):
        for qs in ("page=abc", "page=", "page=1.5", "page=99999999999999999999", "page=%C2%B2", "page=" + "9" * 4500,
                   "page=-3", "page=%EF%BC%91"):
            self.assertEqual(self.anon.get("/public/archive?" + qs).status_code, 200, qs)


class CodexReviewTests(Base):
    """코덱스 검토(2026-10-03) 지적 사항."""

    def test_아카이브_정보가_있는_공구도_삭제_일괄삭제됨(self):
        admin = client_for(make_user("admin", company_id=1))
        a, b, keep = self.camp(), self.camp(), self.camp(company_id=2)
        self.publish(a)
        self.publish(b, is_public="")            # 비공개 행도 마찬가지
        self.db.add(ArchiveContent(company_id=2, campaign_id=keep.id, url=keep.content_urls[0]))
        self.db.commit()
        admin.post(f"/campaigns/{a.id}/delete")
        admin.post("/campaigns/bulk-delete", data={"ids": f"{b.id},{keep.id}"})
        ids = (a.id, b.id, keep.id)
        db = SessionLocal()                      # 지워진 객체를 들고 있지 않은 새 연결로 확인
        try:
            n = lambda cid: db.query(Campaign).filter(Campaign.id == cid).count()
            self.assertEqual((n(ids[0]), n(ids[1])), (0, 0))
            self.assertEqual(db.query(ArchiveContent).filter(ArchiveContent.campaign_id.in_(ids[:2])).count(), 0,
                             "딸린 아카이브 행도 지워져야 (운영 DB 외래키)")
            self.assertEqual(n(ids[2]), 1, "다른 회사 공구는 그대로")
            self.assertEqual(db.query(ArchiveContent).filter(ArchiveContent.campaign_id == ids[2]).count(), 1)
        finally:
            db.close()

    def test_600건이_넘어도_오래된_영상_검색_상세_순위(self):
        t = _kst_today()
        tag = uid()
        rows = []
        for i in range(605):
            u = f"https://www.instagram.com/reel/Bulk{uid()}{i}/"
            c = Campaign(name="대량", company_id=1, status="active", start_date=t - timedelta(i % 30),
                         end_date=t + timedelta(3), content_urls=[u], product_name_manual=f"대량{uid()}")
            self.db.add(c)
            rows.append((c, u))
        old_c = Campaign(name="오래된", company_id=1, status="completed", start_date=t - timedelta(900),
                         end_date=t - timedelta(890), content_urls=["https://www.instagram.com/reel/OldOne123/"],
                         product_name_manual=f"오래된영상{tag}")
        self.db.add(old_c)
        self.db.flush()
        for c, u in rows:
            self.db.add(ArchiveContent(company_id=1, campaign_id=c.id, url=u, is_public=True, views=10))
        old = ArchiveContent(company_id=1, campaign_id=old_c.id, url="https://www.instagram.com/reel/OldOne123/",
                             is_public=True, views=2_000_000_000)
        self.db.add(old)
        self.db.commit()
        self.assertIn(f"오래된영상{tag}", self.anon.get(f"/public/archive?q=오래된영상{tag}").text)
        self.assertEqual(self.anon.get(f"/public/archive/{old.id}").status_code, 200)
        top = self.anon.get("/public/archive?sort=views").text
        self.assertIn(f"/public/archive/{old.id}", top, "조회수 1위는 첫 쪽에")
        for c, _ in rows:
            c.is_archived = True                 # 다른 시험에 영향 없게 정리
        old_c.is_archived = True
        self.db.commit()

    def test_너무_큰_썸네일은_거부(self):
        from app.services import image_service
        c = self.camp()
        big = b"\x89PNG" + b"0" * (image_service.ARCHIVE_THUMB_MAX_BYTES + 10)
        r = self.staff.post(f"/campaigns/{c.id}/links/archive", data={"url": c.content_urls[0], "is_public": "1"},
                            files={"thumbnail": ("big.png", big, "image/png")})
        self.assertIn("err=", r.headers["location"])
        self.assertIsNone(self.row(c))

    def test_html_위장_파일_거부(self):
        c = self.camp()
        r = self.staff.post(f"/campaigns/{c.id}/links/archive", data={"url": c.content_urls[0], "is_public": "1"},
                            files={"thumbnail": ("x.png", b"<html><script>alert(1)</script></html>", "image/png")})
        self.assertIn("err=", r.headers["location"])
        self.assertIsNone(self.row(c))


class CodexRecheckTests(Base):
    def test_예전_형식_유튜브_행도_비공개_전환과_삭제에_포함(self):
        legacy = "https://youtu.be/Legacy12345"
        c = self.camp(urls=[legacy])
        old = ArchiveContent(company_id=1, campaign_id=c.id, url=legacy, is_public=True, views=7,
                             thumbnail="/static/legacy-thumb.png")
        self.db.add(old)
        self.db.commit()
        old_id = old.id
        self.assertEqual(self.anon.get(f"/public/archive/{old_id}").status_code, 200)
        self.assertIn("공개 중", self.staff.get(f"/campaigns/{c.id}").text, "상세에서도 예전 행의 공개 상태가 보임")
        self.publish(c, url=legacy, is_public="")
        self.db.expire_all()
        rows = self.db.query(ArchiveContent).filter(ArchiveContent.campaign_id == c.id).all()
        self.assertEqual(len(rows), 1, "같은 영상은 한 행으로")
        self.assertEqual((rows[0].url, rows[0].is_public), ("https://www.youtube.com/watch?v=Legacy12345", False))
        self.assertEqual(rows[0].thumbnail, "/static/legacy-thumb.png", "옛 썸네일은 이어받음")
        self.assertEqual(self.anon.get(f"/public/archive/{old_id}").status_code, 302)
        self.assertNotIn("Legacy12345", self.anon.get("/public/archive").text)
        self.publish(c, url=legacy)
        self.staff.post(f"/campaigns/{c.id}/links/remove", data={"url": legacy})
        self.assertIsNone(self.row(c))


class StatusTests(unittest.TestCase):
    def test_상태_계산(self):
        t = _kst_today()
        s = public_archive.status_of
        self.assertEqual(s(t - timedelta(1), t + timedelta(1), t), "live")
        self.assertEqual(s(t, None, t), "live")
        self.assertEqual(s(t + timedelta(1), t + timedelta(5), t), "soon")
        self.assertEqual(s(t - timedelta(9), t - timedelta(1), t), "done")
        self.assertEqual(s(None, t - timedelta(1), t), "done")
        self.assertIsNone(s(None, None, t))


if __name__ == "__main__":
    unittest.main()
