from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Proposal, Product, Influencer
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id

router = APIRouter(prefix="/proposals")
templates = Jinja2Templates(directory="app/templates")


@router.get("")
def proposal_list(request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    proposals = (
        db.query(Proposal)
        .filter(Proposal.company_id == cid)
        .order_by(Proposal.created_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse(
        "proposals/list.html",
        {"request": request, "active_page": "proposals", "current_user": current_user, "proposals": proposals},
    )


@router.get("/product/new")
def proposal_product_new(request: Request, db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user),
                         product_id: str = ""):
    cid = get_company_id(current_user)
    products = db.query(Product).filter(Product.company_id == cid, Product.status == "active").order_by(Product.name).limit(300).all()
    selected = db.query(Product).filter(Product.company_id == cid, Product.id == product_id).first() if product_id else None
    return templates.TemplateResponse("proposals/product_form.html", {
        "request": request, "active_page": "proposals",
        "current_user": current_user,
        "products": products, "selected_product": selected,
    })


@router.post("/product/new")
def proposal_product_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    product_id: str = Form(""),
    title: str = Form(""),
    body: str = Form(...),
):
    cid = get_company_id(current_user)
    proposal = Proposal(
        company_id=cid,
        product_id=product_id or None,
        proposal_type="product_sheet",
        title=title or None,
        body=body,
        ai_generated=False,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return RedirectResponse(f"/proposals/{proposal.id}?msg=제안서가+저장되었습니다", status_code=302)


@router.get("/new")
def proposal_new(request: Request, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user),
                 product_id: str = "", influencer_id: str = ""):
    cid = get_company_id(current_user)
    products = db.query(Product).filter(Product.company_id == cid, Product.status != "archived").order_by(Product.name).limit(300).all()
    influencers = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.status == "active").order_by(Influencer.name).limit(300).all()
    return templates.TemplateResponse(
        "proposals/form.html",
        {
            "request": request, "active_page": "proposals",
            "current_user": current_user,
            "products": products, "influencers": influencers,
            "proposal": None,
            "prefill_product_id": product_id,
            "prefill_influencer_id": influencer_id,
        },
    )


@router.post("/new")
def proposal_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    product_id: str = Form(""),
    influencer_id: str = Form(""),
    proposal_type: str = Form("email"),
    title: str = Form(""),
    body: str = Form(...),
    ai_generated: str = Form("false"),
    is_template: str = Form("false"),
    template_name: str = Form(""),
):
    cid = get_company_id(current_user)
    proposal = Proposal(
        company_id=cid,
        product_id=product_id or None,
        influencer_id=influencer_id or None,
        proposal_type=proposal_type,
        title=title or None,
        body=body,
        ai_generated=(ai_generated == "true"),
        is_template=(is_template == "true"),
        template_name=template_name or None,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return RedirectResponse(f"/proposals/{proposal.id}?msg=제안서가+저장되었습니다", status_code=302)


@router.get("/{proposal_id}/card")
def proposal_card(proposal_id: str, request: Request, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    proposal = db.query(Proposal).filter(Proposal.company_id == cid, Proposal.id == proposal_id).first()
    if not proposal or not proposal.product:
        return RedirectResponse(f"/proposals/{proposal_id}", status_code=302)
    return templates.TemplateResponse("proposals/card.html", {
        "request": request, "proposal": proposal, "product": proposal.product,
    })


@router.get("/{proposal_id}")
def proposal_detail(proposal_id: str, request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    proposal = db.query(Proposal).filter(Proposal.company_id == cid, Proposal.id == proposal_id).first()
    if not proposal:
        return RedirectResponse("/proposals?err=제안서를+찾을+수+없습니다", status_code=302)
    return templates.TemplateResponse(
        "proposals/detail.html",
        {"request": request, "active_page": "proposals", "current_user": current_user, "proposal": proposal},
    )


@router.post("/{proposal_id}/delete")
def proposal_delete(proposal_id: str, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    proposal = db.query(Proposal).filter(Proposal.company_id == cid, Proposal.id == proposal_id).first()
    if proposal:
        db.delete(proposal)
        db.commit()
    return RedirectResponse("/proposals?msg=삭제되었습니다", status_code=302)
