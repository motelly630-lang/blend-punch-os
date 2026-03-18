import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from app.database import init_db
from app.backup import run_backup
from app.routers import dashboard, products, influencers, proposals
from app.routers import auth as auth_router
from app.routers import campaigns, trends, settlements
from app.routers import public as public_router
from app.routers import automation as automation_router
from app.routers import catalog as catalog_router
from app.routers import import_products as import_products_router
from app.routers import import_influencers as import_influencers_router
from app.routers import import_campaigns as import_campaigns_router
from app.api import ai_product, ai_proposal, ai_playbook, ai_dm, ai_seller_content, ai_product_image, ai_influencer, ai_recommend, ai_product_chat
from app.routers import trend_engine as trend_engine_router
from app.routers import outreach as outreach_router
from app.routers import crm as crm_router
from app.routers import brands as brands_router
from app.routers import shop as shop_router
from app.routers import orders as orders_router
from app.routers import sales_pages as sales_pages_router
from app.routers import sellers as sellers_router
from app.routers import applications as applications_router
from app.auth.dependencies import RequiresLogin, InsufficientPermissions


async def _backup_loop():
    while True:
        now = datetime.now()
        next_run = (now + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)
        await asyncio.sleep((next_run - now).total_seconds())
        run_backup()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from app.scheduler import start_scheduler
    start_scheduler()
    task = asyncio.create_task(_backup_loop())
    yield
    from app.scheduler import stop_scheduler
    stop_scheduler()
    task.cancel()


app = FastAPI(title="BLEND PUNCH OS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


class NoIndexMiddleware(BaseHTTPMiddleware):
    """퍼블릭 카탈로그 경로에 X-Robots-Tag: noindex, nofollow 헤더 추가."""
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/public"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response


app.add_middleware(NoIndexMiddleware)


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    return FileResponse("static/robots.txt", media_type="text/plain")


# ── Exception handlers ────────────────────────────────────────────────────────
@app.exception_handler(RequiresLogin)
async def requires_login_handler(request: Request, exc: RequiresLogin):
    return RedirectResponse(url="/login", status_code=302)


@app.exception_handler(InsufficientPermissions)
async def insufficient_permissions_handler(request: Request, exc: InsufficientPermissions):
    return RedirectResponse(url="/?err=권한이+없습니다", status_code=302)


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(dashboard.router)
app.include_router(import_products_router.router)
app.include_router(import_influencers_router.router)
app.include_router(import_campaigns_router.router)
app.include_router(products.router)
app.include_router(influencers.router)
app.include_router(proposals.router)
app.include_router(campaigns.router)
app.include_router(trends.router)
app.include_router(settlements.router)
app.include_router(ai_product.router)
app.include_router(ai_proposal.router)
app.include_router(public_router.router)
app.include_router(automation_router.router)
app.include_router(ai_playbook.router)
app.include_router(ai_dm.router)
app.include_router(ai_seller_content.router)
app.include_router(ai_product_image.router)
app.include_router(ai_influencer.router)
app.include_router(ai_recommend.router)
app.include_router(ai_product_chat.router)
app.include_router(trend_engine_router.router)
app.include_router(catalog_router.router)
app.include_router(outreach_router.router)
app.include_router(crm_router.router)
app.include_router(brands_router.router)
app.include_router(shop_router.router)
app.include_router(orders_router.router)
app.include_router(sales_pages_router.router)
app.include_router(sellers_router.router)
app.include_router(applications_router.router)


# ── Jinja2 template filters ───────────────────────────────────────────────────
templates = Jinja2Templates(directory="app/templates")


def _setup_filters():
    from jinja2 import Environment

    def format_won(v):
        if not v:
            return "₩0"
        return f"₩{int(v):,}"

    def format_num(v):
        if not v:
            return "0"
        return f"{int(v):,}"

    def format_pct(v):
        if v is None:
            return "-"
        return f"{float(v) * 100:.1f}%"

    def format_date(v):
        if not v:
            return "-"
        if hasattr(v, "strftime"):
            return v.strftime("%Y.%m.%d")
        return str(v)

    def format_datetime(v):
        if not v:
            return "-"
        return v.strftime("%Y.%m.%d %H:%M")

    def platform_label(v):
        return {
            "instagram": "인스타그램",
            "youtube": "유튜브",
            "tiktok": "틱톡",
            "blog": "블로그",
            "naver": "네이버",
        }.get(v, v)

    def demand_label(v):
        return {"high": "높음", "medium": "보통", "low": "낮음"}.get(v, v)

    def status_label(v):
        return {
            "draft": "초안", "active": "활성", "archived": "보관",
            "planning": "기획중", "negotiating": "협의중", "contracted": "계약완료",
            "completed": "완료", "cancelled": "취소",
            "blacklist": "블랙리스트", "inactive": "비활성",
        }.get(v, v)

    def role_label(v):
        return {"admin": "관리자", "manager": "매니저", "viewer": "뷰어"}.get(v, v)

    import app.routers.dashboard as d
    import app.routers.products as p
    import app.routers.influencers as i
    import app.routers.proposals as pr
    import app.routers.campaigns as ca
    import app.routers.trends as tr
    import app.routers.settlements as se
    import app.routers.auth as a
    import app.routers.public as pub
    import app.routers.automation as auto
    import app.routers.catalog as cat
    import app.routers.import_products as imp
    import app.routers.import_influencers as imp_inf
    import app.routers.import_campaigns as imp_camp
    import app.routers.trend_engine as teng
    import app.routers.outreach as out
    import app.routers.crm as crm
    import app.routers.brands as br
    import app.routers.orders as ord_
    import app.routers.sales_pages as sp
    import app.routers.sellers as sel
    import app.routers.applications as appl

    for mod in [d, p, i, pr, ca, tr, se, a, pub, auto, cat, imp, imp_inf, imp_camp, teng, out, crm, br, ord_, sp, sel, appl]:
        env: Environment = mod.templates.env
        env.filters["won"] = format_won
        env.filters["num"] = format_num
        env.filters["pct"] = format_pct
        env.filters["date"] = format_date
        env.filters["dt"] = format_datetime
        env.filters["platform_label"] = platform_label
        env.filters["demand_label"] = demand_label
        env.filters["status_label"] = status_label
        env.filters["role_label"] = role_label
        env.globals["enumerate"] = enumerate
        env.filters["enumerate"] = enumerate
        env.globals["outreach_active_count"] = _outreach_active_count


_outreach_cache: dict = {"value": 0, "expires": 0.0}


def _outreach_active_count() -> int:
    """Cached count (30s TTL) of in-progress outreach items for sidebar badge."""
    import time
    now = time.monotonic()
    if now < _outreach_cache["expires"]:
        return _outreach_cache["value"]
    from app.database import SessionLocal
    from app.models.outreach import OutreachLog
    db = SessionLocal()
    try:
        count = db.query(OutreachLog).filter(
            OutreachLog.sample_status.in_(["제안발송", "샘플요청", "샘플발송"])
        ).count()
    finally:
        db.close()
    _outreach_cache["value"] = count
    _outreach_cache["expires"] = now + 30.0
    return count


_setup_filters()
