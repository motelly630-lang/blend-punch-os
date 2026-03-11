from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Product, Proposal
from app.models.playbook import Playbook
from app.models.user import User
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/automation")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def automation_index(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    products = (
        db.query(Product)
        .filter(Product.status != "archived")
        .order_by(Product.name)
        .all()
    )

    recent_playbooks = (
        db.query(Playbook)
        .order_by(Playbook.created_at.desc())
        .limit(5)
        .all()
    )

    dm_types = ("dm_first", "dm_followup", "dm_confirm", "seller_outreach", "inf_summary", "memo")
    recent_proposals = (
        db.query(Proposal)
        .filter(Proposal.proposal_type.in_(dm_types))
        .order_by(Proposal.created_at.desc())
        .limit(5)
        .all()
    )

    return templates.TemplateResponse(
        "automation/index.html",
        {
            "request": request,
            "active_page": "automation",
            "current_user": current_user,
            "products": products,
            "recent_playbooks": recent_playbooks,
            "recent_proposals": recent_proposals,
        },
    )
