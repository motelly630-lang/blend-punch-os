import io
import json
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from app.database import get_db
from app.models import Settlement, Campaign, Influencer
from app.models.transaction import Transaction
from app.models.user import User
from app.auth.dependencies import get_current_user
from app.auth.tenant import get_company_id
from app.services import settlement_calc

router = APIRouter(prefix="/settlements")
templates = Jinja2Templates(directory="app/templates")

SELLER_TYPES = list(settlement_calc.SELLER_TYPES)
# 내부 상태값은 그대로(pending/confirmed/paid — 대시보드·시트·포털이 쓴다), 화면 이름만 새 흐름으로
STATUS_LABELS = {"pending": "작성중", "confirmed": "지급 대기", "paid": "지급 완료"}


def calc_settlement(sales_amount: float, commission_rate: float, seller_type: str) -> dict:
    """모델에 넣을 금액 칸 (계산은 app/services/settlement_calc.py 하나만 — 예전 식은 쓰지 않는다)."""
    return settlement_calc.model_fields(sales_amount, commission_rate, seller_type)


def _get(db: Session, cid, settlement_id: str):
    return db.query(Settlement).filter(Settlement.id == settlement_id, Settlement.company_id == cid).first()


def _msg(url: str, text: str, err: bool = False) -> RedirectResponse:
    from urllib.parse import quote
    sep = "&" if "?" in url else "?"
    return RedirectResponse(f"{url}{sep}{'err' if err else 'msg'}={quote(text)}", status_code=302)


def _stamp(s: Settlement, user: User, text: str) -> None:
    """누가 언제 무엇을 했는지 메모 끝에 남긴다 (정산은 돈 — 흔적을 남긴다)."""
    now = datetime.utcnow() + timedelta(hours=9)
    line = f"[{now:%Y-%m-%d %H:%M} {user.username}] {text}"
    s.notes = ((s.notes or "").rstrip() + "\n" + line).strip()


def _apply_calc(s: Settlement) -> None:
    """수동 조정이 아니면 새 계산식으로 금액을 다시 채운다."""
    fields = calc_settlement(s.sales_amount or 0, s.commission_rate or 0, s.seller_type or "사업자")
    manual_final = s.final_payment if s.is_manual else None
    for k, v in fields.items():
        setattr(s, k, v)
    if manual_final is not None:
        s.final_payment = manual_final


@router.get("")
def settlement_list(request: Request, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user),
                    tab: str = "pending",
                    period: str = "", q: str = "", month: str = ""):
    """탭: pending=정산할 것 · confirmed=지급 대기 · paid=지급 완료 · calc=손익 (내부 값은 그대로)."""
    if tab not in ("pending", "confirmed", "paid", "calc"):
        tab = "pending"

    cid = get_company_id(current_user)

    # Aggregate counts/amounts via SQL — no full table load
    total_paid = db.query(func.sum(Settlement.final_payment)).filter(
        Settlement.company_id == cid, Settlement.status == "paid"
    ).scalar() or 0
    pending_count = db.query(func.count(Settlement.id)).filter(
        Settlement.company_id == cid, Settlement.status == "pending"
    ).scalar() or 0
    confirmed_count = db.query(func.count(Settlement.id)).filter(
        Settlement.company_id == cid, Settlement.status == "confirmed"
    ).scalar() or 0
    paid_count = db.query(func.count(Settlement.id)).filter(
        Settlement.company_id == cid, Settlement.status == "paid"
    ).scalar() or 0

    confirmed_total = db.query(func.sum(Settlement.final_payment)).filter(
        Settlement.company_id == cid, Settlement.status == "confirmed"
    ).scalar() or 0
    kst_today = (datetime.utcnow() + timedelta(hours=9)).date()
    this_month = kst_today.strftime("%Y-%m")
    m_start, m_end = _kst_month_bounds_utc(kst_today.year, kst_today.month)
    paid_this_month = db.query(func.sum(Settlement.final_payment)).filter(
        Settlement.company_id == cid, Settlement.status == "paid",
        Settlement.paid_at >= m_start, Settlement.paid_at < m_end,
    ).scalar() or 0

    # 현재 탭 목록 — 검색(인플루언서·캠페인 이름), 지급 완료는 월별
    sq = (db.query(Settlement)
          .options(joinedload(Settlement.influencer), joinedload(Settlement.campaign))
          .outerjoin(Influencer, Influencer.id == Settlement.influencer_id)
          .outerjoin(Campaign, Campaign.id == Settlement.campaign_id)
          .filter(Settlement.company_id == cid, Settlement.status == tab))
    if q:
        like = f"%{q.strip()}%"
        sq = sq.filter(Influencer.name.ilike(like) | Campaign.name.ilike(like))
    months = []
    if tab == "paid":
        paid_day = func.coalesce(Settlement.paid_at, Settlement.updated_at)
        months = sorted({(d + timedelta(hours=9)).strftime("%Y-%m") for (d,) in db.query(paid_day).filter(
            Settlement.company_id == cid, Settlement.status == "paid").all() if d}, reverse=True)
        if month:
            try:
                y, m = int(month[:4]), int(month[5:7])
                start, end = _kst_month_bounds_utc(y, m)
                sq = sq.filter(paid_day >= start, paid_day < end)
            except (ValueError, IndexError):
                month = ""
        sq = sq.order_by(paid_day.desc())
    elif tab == "confirmed":
        sq = sq.order_by(Settlement.due_date.is_(None), Settlement.due_date.asc(), Settlement.issued_at.asc())
    else:
        sq = sq.order_by(Settlement.created_at.desc())
    settlements = sq.limit(300).all()
    tab_total = sum((x.final_payment or 0) for x in settlements)

    # Unique periods for export filter (distinct query, no full load)
    periods = sorted(
        {r[0] for r in db.query(Settlement.period_label)
         .filter(Settlement.company_id == cid, Settlement.period_label.isnot(None)).distinct().all()},
        reverse=True,
    )

    # 정산 등록 모달용 드롭다운 데이터
    influencers_for_modal = (
        db.query(Influencer)
        .filter(Influencer.company_id == cid, Influencer.is_archived == False)
        .order_by(Influencer.name)
        .limit(300).all()
    )
    campaigns_for_modal = (
        db.query(Campaign)
        .filter(Campaign.company_id == cid, Campaign.is_archived == False)
        .order_by(Campaign.created_at.desc())
        .limit(200).all()
    )
    influencers_json = json.dumps([{
        "id": i.id, "name": i.name,
        "business_type": i.business_type or "사업자",
        "rate": i.commission_preference or 0,
    } for i in influencers_for_modal], ensure_ascii=False)

    def _camp_info(c):
        rate, src = settlement_calc.resolve_rate(c, getattr(c, "product", None), getattr(c, "influencer", None))
        return {
            "id": c.id, "name": c.name,
            "start_date": str(c.start_date) if c.start_date else "",
            "end_date": str(c.end_date) if c.end_date else "",
            "influencer_id": c.influencer_id or "",
            "actual_revenue": c.actual_revenue or 0,
            "rate": rate or 0, "rate_source": src,
            "seller_type": c.seller_type or (c.influencer.business_type if getattr(c, "influencer", None) else "") or "",
        }
    campaigns_json = json.dumps([_camp_info(c) for c in campaigns_for_modal], ensure_ascii=False)

    # 완료됐지만 정산 미등록 캠페인
    settled_campaign_ids = {
        r[0] for r in db.query(Settlement.campaign_id)
        .filter(Settlement.campaign_id.isnot(None), Settlement.company_id == cid).all()
    }
    unsettled_campaigns = (
        db.query(Campaign)
        .filter(
            Campaign.company_id == cid,
            Campaign.status == "completed",
            Campaign.is_archived == False,
            Campaign.id.notin_(settled_campaign_ids) if settled_campaign_ids else True,
        )
        .order_by(Campaign.end_date.desc())
        .limit(20).all()
    )

    # ── 손익계산기 탭 전용 집계 ─────────────────────────────────────────────────
    calc_data = {}
    if tab == "calc":
        # 사용 가능한 기간 목록 (transaction_date 기준 년-월)
        raw_dates = db.query(Transaction.transaction_date).filter(
            Transaction.company_id == cid,
            Transaction.transaction_date.isnot(None),
        ).distinct().all()
        calc_periods = sorted(
            {d[0].strftime("%Y-%m") for d in raw_dates if d[0]},
            reverse=True,
        )

        # 기간 필터 적용
        start_dt = end_dt = None
        if period:
            try:
                y, m = int(period[:4]), int(period[5:7])
                start_dt = date(y, m, 1)
                end_dt = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
            except (ValueError, IndexError):
                period = ""

        def _txn_q(type_):
            q = db.query(func.sum(Transaction.amount)).filter(
                Transaction.company_id == cid, Transaction.type == type_
            )
            if start_dt:
                q = q.filter(Transaction.transaction_date >= start_dt,
                              Transaction.transaction_date < end_dt)
            return q.scalar() or 0

        total_revenue = _txn_q("revenue")
        total_cost = _txn_q("cost")

        settle_q = db.query(func.sum(Settlement.final_payment)).filter(
            Settlement.company_id == cid, Settlement.status.in_(["paid", "confirmed"])
        )
        if start_dt:
            settle_q = settle_q.filter(
                Settlement.created_at >= start_dt, Settlement.created_at < end_dt
            )
        total_settlement_pnl = settle_q.scalar() or 0

        net_profit = total_revenue - total_cost - total_settlement_pnl

        # 거래 내역 목록
        txn_q = db.query(Transaction).filter(Transaction.company_id == cid)
        if start_dt:
            txn_q = txn_q.filter(
                Transaction.transaction_date >= start_dt,
                Transaction.transaction_date < end_dt,
            )
        transactions = txn_q.order_by(Transaction.transaction_date.desc()).limit(300).all()

        # 캠페인 목록 (거래 등록 모달용)
        campaigns_for_select = db.query(Campaign).filter(
            Campaign.company_id == cid, Campaign.is_archived == False
        ).order_by(Campaign.created_at.desc()).limit(100).all()

        calc_data = {
            "calc_periods": calc_periods,
            "calc_period": period,
            "total_revenue": total_revenue,
            "total_cost": total_cost,
            "total_settlement_pnl": total_settlement_pnl,
            "net_profit": net_profit,
            "transactions": transactions,
            "campaigns_for_select": campaigns_for_select,
        }

    return templates.TemplateResponse("settlements/index.html", {
        "request": request, "active_page": "settlements", "current_user": current_user,
        "settlements": settlements, "total_paid": total_paid,
        "pending_count": pending_count, "confirmed_count": confirmed_count, "paid_count": paid_count,
        "confirmed_total": confirmed_total, "paid_this_month": paid_this_month, "this_month": this_month,
        "tab_total": tab_total, "q": q, "month": month, "months": months, "status_labels": STATUS_LABELS,
        "tab": tab, "periods": periods,
        "seller_types": SELLER_TYPES,
        "influencers_for_modal": influencers_for_modal,
        "campaigns_for_modal": campaigns_for_modal,
        "influencers_json": influencers_json,
        "campaigns_json": campaigns_json,
        "unsettled_campaigns": unsettled_campaigns,
        **calc_data,
    })


@router.get("/export")
def settlement_export(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    period: str = "",
):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    cid = get_company_id(current_user)
    query = db.query(Settlement).filter(Settlement.company_id == cid)
    if period:
        query = query.filter(Settlement.period_label == period)
    rows = query.order_by(Settlement.created_at.desc()).all()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "정산내역"

    headers = ["기간", "인플루언서", "사업자유형", "캠페인", "매출액", "커미션율", "정산대상(부가세포함)", "공급가액", "부가세",
               "원천세액", "실지급액", "증빙", "상태", "발행일", "지급예정일", "지급일", "은행", "계좌번호", "예금주", "비고"]
    header_fill = PatternFill("solid", fgColor="2563EB")
    header_font = Font(bold=True, color="FFFFFF", size=10)

    for ci, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    d = lambda v: (v + timedelta(hours=9)).strftime("%Y-%m-%d") if isinstance(v, datetime) else (v.isoformat() if v else "")
    for ri, s in enumerate(rows, 2):
        inf = s.influencer
        camp = s.campaign
        vals = [
            s.period_label or "", inf.name if inf else "", s.seller_type or "", camp.name if camp else "",
            s.sales_amount or 0, f"{(s.commission_rate or 0) * 100:.1f}%", s.commission_amount or 0,
            s.supply_amount or "", s.vat_amount or 0, s.tax_amount or 0, s.final_payment or 0,
            settlement_calc.EVIDENCE.get(s.seller_type or "", ""), STATUS_LABELS.get(s.status, s.status),
            d(s.issued_at), d(s.due_date), d(s.paid_at),
            # 계좌는 발행 시점 저장본 우선 (지금 계좌가 바뀌었어도 실제로 보낸 곳)
            s.bank_name_snapshot or (inf.bank_name if inf else ""),
            s.account_number_snapshot or (inf.account_number if inf else ""),
            s.account_holder_snapshot or (inf.account_holder if inf else ""),
            s.notes or "",
        ]
        for ci, v in enumerate(vals, 1):
            ws.cell(row=ri, column=ci, value=v)

    # Auto column width
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 30)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    from urllib.parse import quote
    period_part = f"_{period}" if period else ""
    filename = quote(f"정산내역{period_part}.xlsx")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.get("/{settlement_id}")
def settlement_detail(settlement_id: str, request: Request,
                      db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    cid = get_company_id(current_user)
    s = db.query(Settlement).filter(Settlement.id == settlement_id, Settlement.company_id == cid).first()
    if not s:
        return RedirectResponse("/settlements", status_code=302)
    c = settlement_calc.calc(s.sales_amount or 0, s.commission_rate or 0, s.seller_type or "사업자")
    return templates.TemplateResponse("settlements/detail.html", {
        "request": request, "active_page": "settlements", "current_user": current_user, "s": s,
        "calc": c, "status_labels": STATUS_LABELS, "seller_types": SELLER_TYPES,
        "evidence": settlement_calc.EVIDENCE.get(s.seller_type or "사업자", ""),
        "legacy": s.calc_version is None,
    })


def _rate_from_form(commission_rate_pct: str, commission_rate: str = "") -> float:
    """수수료율: 화면은 % 로 받는다(15 = 15%, 0.5 = 0.5%). 0~100% 밖이면 ValueError."""
    try:
        v = float(str(commission_rate_pct or 0).replace("%", "").strip() or 0)
    except ValueError:
        raise ValueError("수수료율은 숫자(%)로 넣어 주세요")
    if not 0 <= v <= 100:
        raise ValueError("수수료율은 0~100% 사이여야 해요")
    return v / 100


def _kst_month_bounds_utc(y: int, m: int):
    """한국 시간 기준 한 달의 시작·끝 → UTC (paid_at 등은 UTC 로 저장된다)."""
    start = datetime(y, m, 1) - timedelta(hours=9)
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(hours=9)
    return start, end


def _parse_date(v: str):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


@router.post("/preview")
def settlement_preview(sales_amount: float = Form(0.0), commission_rate_pct: str = Form(""),
                       commission_rate: str = Form(""), seller_type: str = Form("사업자"),
                       current_user: User = Depends(get_current_user)):
    """화면 미리보기 — 서버 계산식 그대로 돌려준다 (자바스크립트로 따로 계산하지 않는다)."""
    from fastapi.responses import JSONResponse
    try:
        rate = _rate_from_form(commission_rate_pct)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse(settlement_calc.calc(sales_amount, rate, seller_type))


@router.post("/new")
def settlement_create(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    influencer_id: str = Form(""),
    campaign_id: str = Form(""),
    period_label: str = Form(""),
    seller_type: str = Form("사업자"),
    sales_amount: float = Form(0.0),
    commission_rate_pct: str = Form(""),
    commission_rate: str = Form(""),
    final_payment_manual: str = Form(""),
    due_date: str = Form(""),
    notes: str = Form(""),
):
    cid = get_company_id(current_user)
    try:
        rate = _rate_from_form(commission_rate_pct)
    except ValueError as e:
        return _msg("/settlements", str(e), err=True)
    inf = None
    if influencer_id:
        inf = db.query(Influencer).filter(Influencer.company_id == cid, Influencer.id == influencer_id).first()
    camp = None
    if campaign_id:
        camp = db.query(Campaign).filter(Campaign.company_id == cid, Campaign.id == campaign_id).first()
    s = Settlement(
        company_id=cid,
        influencer_id=inf.id if inf else None,
        campaign_id=camp.id if camp else None,
        period_label=period_label or None,
        seller_type=seller_type if seller_type in SELLER_TYPES else "사업자",
        sales_amount=sales_amount,
        commission_rate=rate,
        due_date=_parse_date(due_date),
        bank_name_snapshot=inf.bank_name if inf else None,
        account_number_snapshot=inf.account_number if inf else None,
        account_holder_snapshot=inf.account_holder if inf else None,
        notes=notes or None,
        status="pending",
    )
    try:
        manual = float(final_payment_manual) if str(final_payment_manual).strip() else None
    except ValueError:
        manual = None
    s.is_manual = manual is not None
    if manual is not None:
        s.final_payment = round(manual)
    _apply_calc(s)
    _stamp(s, current_user, "작성" + (" (지급액 수동 입력)" if s.is_manual else ""))
    db.add(s)
    db.commit()
    return _msg(f"/settlements/{s.id}", "정산서를 만들었어요 — 확인 후 [발행] 하세요")


@router.post("/{settlement_id}/edit")
def settlement_edit(settlement_id: str, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user),
                    seller_type: str = Form("사업자"), sales_amount: float = Form(0.0),
                    commission_rate_pct: str = Form(""), final_payment_manual: str = Form(""),
                    due_date: str = Form(""), period_label: str = Form("")):
    """작성중일 때만 고친다. 지급액을 비우면 자동 계산으로 돌아간다."""
    s = _get(db, get_company_id(current_user), settlement_id)
    if not s:
        return RedirectResponse("/settlements", status_code=302)
    if s.status != "pending":
        return _msg(f"/settlements/{s.id}", "발행된 정산서는 고칠 수 없어요 — [발행 취소] 후 고치세요", err=True)
    try:
        rate = _rate_from_form(commission_rate_pct)
    except ValueError as e:
        return _msg(f"/settlements/{s.id}", str(e), err=True)
    s.seller_type = seller_type if seller_type in SELLER_TYPES else "사업자"
    s.sales_amount = sales_amount
    s.commission_rate = rate
    s.due_date = _parse_date(due_date)
    if period_label:
        s.period_label = period_label
    try:
        manual = float(final_payment_manual) if str(final_payment_manual).strip() else None
    except ValueError:
        manual = None
    s.is_manual = manual is not None
    if manual is not None:
        s.final_payment = round(manual)
    _apply_calc(s)
    _stamp(s, current_user, "수정" + (" (지급액 수동 입력)" if s.is_manual else ""))
    db.commit()
    return _msg(f"/settlements/{s.id}", "저장했어요")


@router.post("/{settlement_id}/confirm")
def settlement_confirm(settlement_id: str, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user),
                       accept_new_calc: str = Form("")):
    """발행 — 작성중 → 지급 대기. 발행 시점의 금액·계좌를 그대로 보존한다."""
    s = _get(db, get_company_id(current_user), settlement_id)
    if not s:
        return RedirectResponse("/settlements", status_code=302)
    if s.status != "pending":
        return _msg(f"/settlements/{s.id}", "작성중인 정산서만 발행할 수 있어요", err=True)
    if not s.is_manual:
        before = s.final_payment or 0
        new = settlement_calc.calc(s.sales_amount or 0, s.commission_rate or 0, s.seller_type or "사업자")["final_payment"]
        if s.calc_version is None and round(before) != new and accept_new_calc != "1":
            # 예전 계산식 정산서 — 금액이 바뀌므로 정산서 화면에서 "예전 → 새 금액"을 보고 확인해야 발행
            return _msg(f"/settlements/{s.id}",
                        f"예전 계산식 정산서예요 — 발행하면 실지급액이 {round(before):,}원 → {new:,}원으로 바뀌어요. 확인 후 발행해 주세요",
                        err=True)
        if round(before) != new:
            _stamp(s, current_user, f"발행 때 새 계산식 적용: 실지급 {round(before):,}원 → {new:,}원")
        _apply_calc(s)
    if not (s.final_payment or 0) > 0:
        return _msg(f"/settlements/{s.id}", "지급액이 0원이에요 — 매출·수수료율을 먼저 넣어 주세요", err=True)
    if s.influencer and not s.bank_name_snapshot:
        s.bank_name_snapshot = s.influencer.bank_name
        s.account_number_snapshot = s.influencer.account_number
        s.account_holder_snapshot = s.influencer.account_holder
    s.status = "confirmed"
    s.issued_at = datetime.utcnow()
    _stamp(s, current_user, "발행")
    db.commit()
    return _msg(f"/settlements/{s.id}", "발행했어요 — 지급 대기 목록으로 갔어요")


@router.post("/{settlement_id}/unissue")
def settlement_unissue(settlement_id: str, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    """발행 취소 — 지급 대기 → 작성중 (지급 완료된 건 취소할 수 없다)."""
    s = _get(db, get_company_id(current_user), settlement_id)
    if not s:
        return RedirectResponse("/settlements", status_code=302)
    if s.status != "confirmed":
        return _msg(f"/settlements/{s.id}", "지급 대기 상태만 발행을 취소할 수 있어요", err=True)
    s.status = "pending"
    s.issued_at = None
    _stamp(s, current_user, "발행 취소")
    db.commit()
    return _msg(f"/settlements/{s.id}", "발행을 취소했어요 — 고친 뒤 다시 발행하세요")


@router.post("/{settlement_id}/paid")
def settlement_paid(settlement_id: str, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    s = _get(db, get_company_id(current_user), settlement_id)
    if not s:
        return RedirectResponse("/settlements", status_code=302)
    if s.status != "confirmed":
        return _msg(f"/settlements/{s.id}", "발행된(지급 대기) 정산서만 지급 완료할 수 있어요", err=True)
    s.status = "paid"
    s.paid_at = datetime.utcnow()
    _stamp(s, current_user, "지급 완료")
    db.commit()
    return _msg("/settlements?tab=confirmed", "지급 완료로 옮겼어요")


@router.post("/{settlement_id}/delete")
def settlement_delete(settlement_id: str, db: Session = Depends(get_db),
                      current_user: User = Depends(get_current_user)):
    s = _get(db, get_company_id(current_user), settlement_id)
    if not s:
        return RedirectResponse("/settlements", status_code=302)
    if s.status != "pending":
        return _msg(f"/settlements/{s.id}", "작성중인 정산서만 지울 수 있어요 (발행·지급된 건 기록으로 남깁니다)", err=True)
    db.delete(s)
    db.commit()
    return _msg("/settlements", "삭제했어요")
