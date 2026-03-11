from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.trend import TrendItem
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/trends")
templates = Jinja2Templates(directory="app/templates")

CATEGORIES = ["식품", "주방", "리빙", "뷰티", "건강", "다이어트", "육아", "반려동물"]

# Sample seed data shown when DB is empty
SAMPLE_TRENDS = [
    {"category": "건강", "title": "저속노화 식단 / 항산화 식품 관심 급증", "summary": "건강 장수 관심이 높아지며 항산화 식품, 아연·마그네슘 등 미네랄 보충제 수요 증가.", "trend_score": 9.2, "tags": ["저속노화", "항산화", "미네랄", "건강기능식품"], "recommended_inf_categories": ["건강관리", "요리", "일상"]},
    {"category": "다이어트", "title": "저탄고지 / 케토제닉 식품 재유행", "summary": "단백질·지방 위주 식단 콘텐츠가 인스타·유튜브에서 다시 상승세. 키토 과자·제로 제품 협업 문의 증가.", "trend_score": 8.5, "tags": ["케토", "저탄고지", "프로틴", "다이어트식품"], "recommended_inf_categories": ["다이어트", "건강관리", "요리"]},
    {"category": "뷰티", "title": "더마 코스메틱 / 성분 중심 스킨케어", "summary": "나이아신아마이드, 세라마이드, 레티놀 등 성분 중심 제품 관심 지속. 민감성 피부 특화 제품 협업 활발.", "trend_score": 8.8, "tags": ["더마코스메틱", "성분케어", "세라마이드", "민감성"], "recommended_inf_categories": ["뷰티", "일상"]},
    {"category": "식품", "title": "간편식 프리미엄화 - 밀키트 고급화", "summary": "1~2인 가구 증가로 고급 밀키트, 반조리 식품 수요 상승. 요리 유튜버/인스타 협업 최적 카테고리.", "trend_score": 8.0, "tags": ["밀키트", "간편식", "1인가구", "프리미엄"], "recommended_inf_categories": ["요리", "레시피", "홈카페", "일상"]},
    {"category": "리빙", "title": "홈카페 인테리어 & 커피용품", "summary": "집에서 카페처럼 즐기는 홈카페 트렌드 지속. 커피머신, 텀블러, 카페 소품 협업 문의 꾸준히 증가.", "trend_score": 7.8, "tags": ["홈카페", "인테리어", "커피", "텀블러"], "recommended_inf_categories": ["홈카페", "리빙", "일상", "요리"]},
    {"category": "육아", "title": "유아 친환경·무독성 생활용품", "summary": "영유아 부모의 친환경 인식 높아짐. 유기농 소재, BPA-free, 무형광 제품이 육아 인플루언서 채널에서 강세.", "trend_score": 8.3, "tags": ["친환경육아", "무독성", "유아용품", "유기농"], "recommended_inf_categories": ["육아", "일상", "리빙"]},
    {"category": "반려동물", "title": "반려동물 건강기능식 & 프리미엄 사료", "summary": "펫 시장 고급화 뚜렷. 관절, 피부, 장 건강 기능성 간식·영양제가 펫 인플루언서 채널에서 인기.", "trend_score": 8.6, "tags": ["펫푸드", "반려동물건강", "기능성간식", "프리미엄펫"], "recommended_inf_categories": ["반려동물", "일상"]},
    {"category": "주방", "title": "에어프라이어·멀티쿠커 주방 소형가전", "summary": "1인 가구·바쁜 직장인 대상 소형 주방가전 수요 꾸준. 레시피 콘텐츠 연동 협업 전환율 높음.", "trend_score": 7.5, "tags": ["소형가전", "에어프라이어", "주방", "편의성"], "recommended_inf_categories": ["요리", "레시피", "살림", "일상"]},
]


@router.get("")
def trend_list(request: Request, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user),
               category: str = ""):
    query = db.query(TrendItem).order_by(TrendItem.is_pinned.desc(), TrendItem.trend_score.desc())
    if category:
        query = query.filter(TrendItem.category == category)
    items = query.all()

    # Show sample data as "inspiration" if DB is empty
    show_samples = len(items) == 0 and not category
    return templates.TemplateResponse("trends/index.html", {
        "request": request, "active_page": "trends", "current_user": current_user,
        "items": items, "categories": CATEGORIES, "selected_category": category,
        "show_samples": show_samples, "sample_trends": SAMPLE_TRENDS,
    })


@router.post("/save")
def trend_save(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    category: str = Form(...),
    title: str = Form(...),
    summary: str = Form(""),
    source_url: str = Form(""),
    trend_score: float = Form(5.0),
    tags_raw: str = Form(""),
):
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    item = TrendItem(
        category=category, title=title, summary=summary or None,
        source_url=source_url or None, trend_score=trend_score,
        tags=tags or None,
    )
    db.add(item)
    db.commit()
    return RedirectResponse("/trends?msg=저장되었습니다", status_code=302)


@router.post("/{item_id}/delete")
def trend_delete(item_id: str, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    item = db.query(TrendItem).filter(TrendItem.id == item_id).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse("/trends?msg=삭제되었습니다", status_code=302)
