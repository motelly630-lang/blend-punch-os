"""
AI 에이전트 파이프라인 API + UI

GET  /pipeline/product/{product_id}        — 캐릭터 뷰어 페이지
GET  /pipeline/brand/{brand_id}            — 캐릭터 뷰어 페이지
GET  /pipeline/create                      — 신규 제품 자동 등록
GET  /pipeline/queue                       — 관리자 검토 대기열
POST /api/pipeline/product/{id}/start      — 백그라운드 실행 시작
POST /api/pipeline/brand/{id}/start        — 백그라운드 실행 시작
POST /api/pipeline/create/product/start    — 신규 제품 파이프라인 시작
GET  /api/pipeline/poll/{target_type}/{id} — 진행 상황 폴링
GET  /api/pipeline/queue/list              — 대기열 목록 (JSON)
POST /api/pipeline/queue/{queue_id}/approve — 승인 + 재개
POST /api/pipeline/queue/{queue_id}/reject  — 반려
"""
import json
import os
import threading
import tempfile
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import Request
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.auth.dependencies import get_current_user
from app.models.user import User
from app.models.agent_log import AgentLog, REVIEW_STATUSES, AGENT_ROLES
from app.models.pipeline_job import PipelineJob

router = APIRouter(tags=["pipeline"])
templates = Jinja2Templates(directory="app/templates")


# ── Job 추적 (DB 기반 — 서버 재시작에도 유지) ──────────────────────────────

def _set_job(target_id: str, status: str, result=None, error=None,
             company_id: int = 1, target_type: str = "product"):
    db = SessionLocal()
    try:
        job = db.query(PipelineJob).filter(PipelineJob.id == target_id).first()
        if not job:
            job = PipelineJob(id=target_id, company_id=company_id,
                              target_type=target_type, started_at=datetime.utcnow())
            db.add(job)
        job.status = status
        if result is not None:
            job.result = result
        if error:
            job.error = str(error)
        if status in ("done", "error"):
            job.finished_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _get_job(target_id: str) -> dict:
    db = SessionLocal()
    try:
        job = db.query(PipelineJob).filter(PipelineJob.id == target_id).first()
        if not job:
            return {"status": "idle", "result": None}
        return {"status": job.status, "result": job.result}
    finally:
        db.close()


def _get_company_id(current_user: User, db: Session) -> int:
    from app.services.feature_flags import get_user_company
    company_id, _ = get_user_company(db, current_user.username)
    return company_id


# ── UI 페이지 ──────────────────────────────────────────────────────────────────

@router.get("/pipeline/create", response_class=HTMLResponse)
def pipeline_create_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("pipeline/create.html", {
        "request": request,
        "current_user": current_user,
    })


@router.get("/pipeline/batch", response_class=HTMLResponse)
def pipeline_batch_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    return templates.TemplateResponse("pipeline/batch.html", {
        "request": request,
        "current_user": current_user,
    })


@router.get("/pipeline/queue", response_class=HTMLResponse)
def pipeline_queue_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """관리자 검토 대기열 페이지."""
    from app.models.human_review_queue import HumanReviewQueue
    company_id = _get_company_id(current_user, db)
    items = (
        db.query(HumanReviewQueue)
        .filter(HumanReviewQueue.company_id == company_id,
                HumanReviewQueue.status == "pending")
        .order_by(HumanReviewQueue.created_at.desc())
        .all()
    )
    return templates.TemplateResponse("pipeline/queue.html", {
        "request": request,
        "current_user": current_user,
        "queue_items": items,
        "AGENT_ROLES": AGENT_ROLES,
    })


@router.get("/pipeline/product/{product_id}", response_class=HTMLResponse)
def pipeline_product_viewer(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.product import Product
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="제품을 찾을 수 없습니다.")
    return templates.TemplateResponse("pipeline/viewer.html", {
        "request": request,
        "current_user": current_user,
        "target_type": "product",
        "target_id": product_id,
        "target_name": product.name,
        "target_sub": product.brand,
        "review_status": getattr(product, "review_status", "draft") or "draft",
        "priority_score": getattr(product, "priority_score", None),
    })


@router.get("/pipeline/brand/{brand_id}", response_class=HTMLResponse)
def pipeline_brand_viewer(
    brand_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.brand import Brand
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=404, detail="브랜드를 찾을 수 없습니다.")
    return templates.TemplateResponse("pipeline/viewer.html", {
        "request": request,
        "current_user": current_user,
        "target_type": "brand",
        "target_id": brand_id,
        "target_name": brand.name,
        "target_sub": brand.description or "",
        "review_status": getattr(brand, "review_status", "draft") or "draft",
        "priority_score": getattr(brand, "priority_score", None),
    })


# ── 신규 제품 생성 파이프라인 ──────────────────────────────────────────────────

@router.post("/api/pipeline/create/product/start")
def start_create_product(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    text: str = Form(""),
    image_file: Optional[UploadFile] = File(None),
    excel_file: Optional[UploadFile] = File(None),
):
    import uuid as _uuid
    company_id = _get_company_id(current_user, db)
    product_id = str(_uuid.uuid4())

    excel_path = image_path = None
    tmp_files = []
    if excel_file and excel_file.filename:
        suffix = os.path.splitext(excel_file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(excel_file.file.read()); excel_path = f.name; tmp_files.append(f.name)
    if image_file and image_file.filename:
        suffix = os.path.splitext(image_file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(image_file.file.read()); image_path = f.name; tmp_files.append(f.name)

    def _run():
        from app.agents.runner import create_product_pipeline
        _set_job(product_id, "running", company_id=company_id, target_type="product")
        _db = SessionLocal()
        try:
            result = create_product_pipeline(
                db=_db, company_id=company_id,
                text=text or None, image_path=image_path, excel_path=excel_path,
                product_id=product_id,
            )
            _set_job(product_id, "done", result=result)
        except Exception as e:
            _set_job(product_id, "error", error=str(e))
        finally:
            _db.close()
            for p in tmp_files:
                try: os.unlink(p)
                except: pass

    threading.Thread(target=_run, daemon=True).start()
    return JSONResponse({"status": "started", "product_id": product_id})


# ── 기존 제품/브랜드 재검토 ────────────────────────────────────────────────────

def _run_in_background(target_type: str, target_id: str, target_name: str,
                        company_id: int, text: str = None,
                        image_path: str = None, excel_path: str = None,
                        existing_data: dict = None, start_from: str = "staff"):
    _set_job(target_id, "running", company_id=company_id, target_type=target_type)
    db = SessionLocal()
    try:
        if target_type == "product":
            from app.agents.runner import run_product_pipeline
            result = run_product_pipeline(
                db=db, product_id=target_id, product_name=target_name,
                company_id=company_id, text=text, image_path=image_path,
                excel_path=excel_path, existing_data=existing_data,
                start_from=start_from,
            )
        else:
            from app.agents.runner import run_brand_pipeline
            result = run_brand_pipeline(
                db=db, brand_id=target_id, brand_name=target_name,
                company_id=company_id, text=text, image_path=image_path,
                excel_path=excel_path, existing_data=existing_data,
            )
        _set_job(target_id, "done", result=result)
    except Exception as e:
        _set_job(target_id, "error", error=str(e))
    finally:
        db.close()
        for p in [image_path, excel_path]:
            if p:
                try: os.unlink(p)
                except: pass


@router.post("/api/pipeline/product/{product_id}/start")
def start_product_pipeline(
    product_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    text: str = Form(""),
    excel_file: Optional[UploadFile] = File(None),
    image_file: Optional[UploadFile] = File(None),
):
    from app.models.product import Product
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404)

    if _get_job(product_id).get("status") == "running":
        return JSONResponse({"status": "already_running"})

    company_id = _get_company_id(current_user, db)
    existing_data = {
        "name": product.name, "brand": product.brand,
        "category": product.category,
        "consumer_price": product.consumer_price,
        "supplier_price": product.supplier_price,
        "groupbuy_price": product.groupbuy_price,
        "seller_commission_rate": product.seller_commission_rate,
        "description": product.description,
        "usp": product.unique_selling_point,
        "target_audience": product.target_audience,
        "usage_scenes": product.usage_scenes,
    }

    excel_path = image_path = None
    if excel_file and excel_file.filename:
        suffix = os.path.splitext(excel_file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(excel_file.file.read()); excel_path = f.name
    if image_file and image_file.filename:
        suffix = os.path.splitext(image_file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(image_file.file.read()); image_path = f.name

    threading.Thread(
        target=_run_in_background,
        args=("product", product_id, product.name, company_id,
              text or None, image_path, excel_path, existing_data),
        daemon=True,
    ).start()
    return JSONResponse({"status": "started"})


@router.post("/api/pipeline/brand/{brand_id}/start")
def start_brand_pipeline(
    brand_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    text: str = Form(""),
    image_file: Optional[UploadFile] = File(None),
):
    from app.models.brand import Brand
    brand = db.query(Brand).filter(Brand.id == brand_id).first()
    if not brand:
        raise HTTPException(status_code=404)

    if _get_job(brand_id).get("status") == "running":
        return JSONResponse({"status": "already_running"})

    company_id = _get_company_id(current_user, db)
    existing_data = {"name": brand.name, "description": brand.description}

    image_path = None
    if image_file and image_file.filename:
        suffix = os.path.splitext(image_file.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(image_file.file.read()); image_path = f.name

    threading.Thread(
        target=_run_in_background,
        args=("brand", brand_id, brand.name, company_id,
              text or None, image_path, None, existing_data),
        daemon=True,
    ).start()
    return JSONResponse({"status": "started"})


# ── 폴링 엔드포인트 ────────────────────────────────────────────────────────────

@router.get("/api/pipeline/poll/{target_type}/{target_id}")
def poll_pipeline(
    target_type: str,
    target_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = _get_job(target_id)
    job_status = job.get("status", "idle")

    logs = (
        db.query(AgentLog)
        .filter(AgentLog.target_type == target_type, AgentLog.target_id == target_id)
        .order_by(AgentLog.created_at.asc())
        .all()
    )

    steps = [{
        "role": l.role,
        "role_label": AGENT_ROLES.get(l.role, l.role),
        "decision": l.decision,
        "reject_reason": l.reject_reason,
        "priority_score": l.priority_score,
        "score": l.score,
        "confidence": l.confidence,
        "risk_level": l.risk_level,
        "output": json.loads(l.output) if l.output else {},
        "elapsed_ms": l.elapsed_ms,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    } for l in logs]

    if target_type == "product":
        from app.models.product import Product
        obj = db.query(Product).filter(Product.id == target_id).first()
    else:
        from app.models.brand import Brand
        obj = db.query(Brand).filter(Brand.id == target_id).first()

    review_status = (getattr(obj, "review_status", "draft") or "draft") if obj else "draft"
    priority_score = getattr(obj, "priority_score", None) if obj else None

    # 자동 생성된 캠페인/제안서 확인 (review_status 무관하게 조회)
    triggered = {}
    if target_type == "product":
        from app.models.trigger_log import TriggerLog
        tlogs = db.query(TriggerLog).filter(
            TriggerLog.source_id == target_id,
            TriggerLog.status == "success",
        ).all()
        for t in tlogs:
            triggered[t.trigger_type] = t.target_id

    # Human Review Queue 확인
    review_queue_id = None
    if review_status == "pending_review":
        from app.models.human_review_queue import HumanReviewQueue
        qitem = (
            db.query(HumanReviewQueue)
            .filter(HumanReviewQueue.target_id == target_id,
                    HumanReviewQueue.status == "pending")
            .order_by(HumanReviewQueue.created_at.desc())
            .first()
        )
        if qitem:
            review_queue_id = qitem.id

    return {
        "job_status": job_status,
        "review_status": review_status,
        "review_status_label": REVIEW_STATUSES.get(review_status, review_status),
        "priority_score": priority_score,
        "steps": steps,
        "steps_done": len(steps),
        "triggered": triggered,
        "review_queue_id": review_queue_id,
    }


# ── 관리자 검토 대기열 API ─────────────────────────────────────────────────────

@router.get("/api/pipeline/queue/list")
def list_queue(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    from app.models.human_review_queue import HumanReviewQueue
    company_id = _get_company_id(current_user, db)
    items = (
        db.query(HumanReviewQueue)
        .filter(HumanReviewQueue.company_id == company_id)
        .order_by(HumanReviewQueue.created_at.desc())
        .limit(50)
        .all()
    )
    return [{
        "id": i.id, "target_type": i.target_type, "target_id": i.target_id,
        "target_name": i.target_name, "stopped_at_role": i.stopped_at_role,
        "score": i.score, "confidence": i.confidence, "status": i.status,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    } for i in items]


@router.post("/api/pipeline/queue/{queue_id}/approve")
def approve_queue_item(
    queue_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    note: str = Form(""),
):
    """승인 → 다음 단계부터 파이프라인 재개."""
    from app.models.human_review_queue import HumanReviewQueue
    company_id = _get_company_id(current_user, db)
    qitem = db.query(HumanReviewQueue).filter(
        HumanReviewQueue.id == queue_id,
        HumanReviewQueue.company_id == company_id,
    ).first()
    if not qitem:
        raise HTTPException(status_code=404)

    qitem.status = "approved"
    qitem.reviewer_note = note
    qitem.reviewed_at = datetime.utcnow()
    db.commit()

    # 멈춘 역할의 다음 단계부터 재개
    roles = ["staff", "assistant", "manager", "lead", "director"]
    stopped_idx = roles.index(qitem.stopped_at_role) if qitem.stopped_at_role in roles else 0
    next_role = roles[stopped_idx + 1] if stopped_idx + 1 < len(roles) else None

    if next_role and qitem.target_type == "product":
        context = json.loads(qitem.context_snapshot) if qitem.context_snapshot else {}
        threading.Thread(
            target=_run_in_background,
            args=(qitem.target_type, qitem.target_id, qitem.target_name or "",
                  company_id, None, None, None, None, next_role),
            kwargs={},
            daemon=True,
        ).start()
        # context가 필요한 경우 runner에서 재구성 (기존 DB 데이터로)

    return JSONResponse({"status": "approved", "resumed_from": next_role})


@router.post("/api/pipeline/queue/{queue_id}/reject")
def reject_queue_item(
    queue_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    note: str = Form(""),
):
    """반려 → 제품 상태를 rejected로 변경."""
    from app.models.human_review_queue import HumanReviewQueue
    company_id = _get_company_id(current_user, db)
    qitem = db.query(HumanReviewQueue).filter(
        HumanReviewQueue.id == queue_id,
        HumanReviewQueue.company_id == company_id,
    ).first()
    if not qitem:
        raise HTTPException(status_code=404)

    qitem.status = "rejected"
    qitem.reviewer_note = note
    qitem.reviewed_at = datetime.utcnow()
    db.commit()

    # 제품 상태 rejected로
    if qitem.target_type == "product":
        from app.models.product import Product
        product = db.query(Product).filter(Product.id == qitem.target_id).first()
        if product:
            product.review_status = "rejected"
            db.commit()

    return JSONResponse({"status": "rejected"})


# ── 로그/상태 조회 ─────────────────────────────────────────────────────────────

@router.get("/api/pipeline/logs/{target_type}/{target_id}")
def get_pipeline_logs(
    target_type: str, target_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    logs = (
        db.query(AgentLog)
        .filter(AgentLog.target_type == target_type, AgentLog.target_id == target_id)
        .order_by(AgentLog.created_at.desc()).limit(50).all()
    )
    return [{
        "role": l.role, "role_label": AGENT_ROLES.get(l.role, l.role),
        "decision": l.decision, "reject_reason": l.reject_reason,
        "priority_score": l.priority_score, "score": l.score,
        "confidence": l.confidence, "risk_level": l.risk_level,
        "output": json.loads(l.output) if l.output else {},
        "elapsed_ms": l.elapsed_ms, "status": l.status,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    } for l in logs]


@router.get("/api/pipeline/status/{target_type}/{target_id}")
def get_pipeline_status(
    target_type: str, target_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if target_type == "product":
        from app.models.product import Product
        obj = db.query(Product).filter(Product.id == target_id).first()
    else:
        from app.models.brand import Brand
        obj = db.query(Brand).filter(Brand.id == target_id).first()
    if not obj:
        raise HTTPException(status_code=404)
    review_status = getattr(obj, "review_status", "draft") or "draft"
    return {
        "target_id": target_id, "target_type": target_type,
        "review_status": review_status,
        "review_status_label": REVIEW_STATUSES.get(review_status, review_status),
        "priority_score": getattr(obj, "priority_score", None),
    }
