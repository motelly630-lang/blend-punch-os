"""트렌드 제품 매칭 (2026-09-26 운영 사례로 고침).

'환절기 건조·보습' 에 냉감 패드(설명 '빠른 건조')·콜드브루(설명 '동결건조') 가 붙었다.
- 이름에 키워드 → 강한 매칭, 설명에만 → 분류가 맞을 때만 약하게, 분류도 안 맞으면 제외
"""
import unittest
from types import SimpleNamespace as P

from app.services.trend_matcher import category_fits, match_score

DRY = {"keywords": ["보습", "수분크림", "건조", "환절기", "로션", "바디로션", "립밤", "핸드크림", "세라마이드"],
       "product_categories": ["뷰티", "beauty"]}
CAMP = {"keywords": ["캠핑", "단풍", "등산", "트레킹", "아웃도어", "바베큐", "캠핑용품"],
        "product_categories": ["리빙", "식품", "food", "living"]}


def _p(name, category, description=""):
    return P(name=name, category=category, description=description, tags=None, unique_selling_point=None, key_benefits=None)


class MatchTest(unittest.TestCase):
    def test_설명의_한_단어로_엉뚱한_분류가_붙지_않는다(self):
        for p in (_p("수퍼쿨 냉감 패드", "생활용품", "빠른 건조, 시원한 촉감"),
                  _p("프리미엄 콜드브루 커피 24개입", "식품/음료", "동결건조 공법")):
            self.assertEqual(match_score(p, DRY)[0], 0.0, p.name)

    def test_태그는_약한_무게(self):
        p = _p("수퍼쿨 냉감 패드", "생활용품")
        p.tags = ["건조", "수분"]
        self.assertEqual(match_score(p, DRY)[0], 0.0)              # 분류도 안 맞으니 제외

    def test_이름에_있으면_강하게(self):
        cream = match_score(_p("디어커스 수분크림", "스킨케어", "건조한 피부 보습"), DRY)[0]
        self.assertGreaterEqual(cream, 0.5)

    def test_설명에만_있고_분류가_맞으면_약하게(self):
        name_hit = match_score(_p("쿨린 캠핑 타프 팬 선풍기", "가전제품"), CAMP)[0]
        desc_only = match_score(_p("무선 멀티 청소기", "생활용품", "캠핑 갈 때 좋아요"), CAMP)[0]
        self.assertGreater(desc_only, 0)
        self.assertGreater(name_hit, desc_only)

    def test_분류_묶음(self):
        self.assertTrue(category_fits("스킨케어", DRY))
        self.assertTrue(category_fits("주방용품", CAMP))
        self.assertFalse(category_fits("생활용품", DRY))
        self.assertFalse(category_fits("", DRY))


class ReportTest(unittest.TestCase):
    def test_보고에는_이름이_맞는_제품만_없으면_소싱_후보(self):
        from app.services.slack_reports import strong_products
        e = {"matched_products": [{"product_name": "냉감 패드", "name_match": False},
                                  {"product_name": "수분크림", "name_match": True},
                                  {"product_name": "예전 저장분"}]}              # name_match 없음 → 보여줌
        self.assertEqual(strong_products(e), ["수분크림", "예전 저장분"])
        self.assertEqual(strong_products({"matched_products": [{"product_name": "x", "name_match": False}]}), [])


if __name__ == "__main__":
    unittest.main()
