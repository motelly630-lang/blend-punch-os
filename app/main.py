from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import init_db
from app.routers import dashboard, products, influencers, proposals
from app.routers import auth as auth_router
from app.routers import campaigns, trends, settlements
from app.routers import public as public_router
from app.api import ai_product, ai_proposal
from app.auth.dependencies import RequiresLogin, InsufficientPermissions


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="BLEND PUNCH OS", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


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
app.include_router(products.router)
app.include_router(influencers.router)
app.include_router(proposals.router)
app.include_router(campaigns.router)
app.include_router(trends.router)
app.include_router(settlements.router)
app.include_router(ai_product.router)
app.include_router(ai_proposal.router)
app.include_router(public_router.router)


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

    for mod in [d, p, i, pr, ca, tr, se, a, pub]:
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


_setup_filters()
