"""
시스템 자동 이메일 서비스

모든 SaaS 시스템 이메일 (인증, 비밀번호 재설정, 알림 등)을 처리한다.
EmailLog에 기록되며 email_mock=True이면 실제 발송 없이 로그만 남긴다.
"""
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session
from app.config import settings
from app.services.email_service import send_email

BASE_URL = settings.app_base_url

# HTML 템플릿 렌더러 (시스템 이메일 전용)
_email_env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=select_autoescape(["html"]),
)


def _render_html(template_name: str, **ctx) -> str:
    """app/templates/emails/system/ 하위 HTML 템플릿 렌더링."""
    try:
        tpl = _email_env.get_template(f"emails/system/{template_name}.html")
        return tpl.render(subject=ctx.get("subject", ""), **ctx)
    except Exception:
        return ""


# ── 회원가입 이메일 인증 ──────────────────────────────────────────────────────

def send_verify_email(db: Session, user) -> None:
    link = f"{BASE_URL}/verify-email?token={user.verify_token}"
    subject = "[BLEND PUNCH] 이메일 인증을 완료해주세요"
    body = (
        f"안녕하세요, {user.username}님!\n\n"
        f"BLEND PUNCH OS에 가입해주셔서 감사합니다.\n\n"
        f"아래 링크를 클릭하면 이메일 인증이 완료됩니다:\n"
        f"{link}\n\n"
        f"링크는 24시간 동안 유효합니다.\n\n"
        f"본인이 가입하지 않으셨다면 이 메일을 무시해주세요.\n\n"
        f"감사합니다.\nBLEND PUNCH 팀"
    )
    html_body = _render_html("verify", subject=subject, username=user.username, link=link)
    send_email(
        db, to_email=user.email, to_name=user.username,
        subject=subject, body=body, html_body=html_body,
        template_name="email_verify", related_type="user", related_id=user.id,
        company_id=user.company_id or 1,
    )


# ── 가입 환영 메일 ────────────────────────────────────────────────────────────

def send_welcome(db: Session, user) -> None:
    subject = "[BLEND PUNCH] 가입을 환영합니다!"
    login_url = f"{BASE_URL}/login"
    body = (
        f"안녕하세요, {user.username}님!\n\n"
        f"BLEND PUNCH OS 가입을 환영합니다.\n\n"
        f"지금 바로 로그인하여 서비스를 이용해보세요:\n"
        f"{login_url}\n\n"
        f"궁금한 점이 있으시면 admin@blendpunch.com 으로 연락주세요.\n\n"
        f"감사합니다.\nBLEND PUNCH 팀"
    )
    html_body = _render_html("welcome", subject=subject, username=user.username, login_url=login_url)
    send_email(
        db, to_email=user.email, to_name=user.username,
        subject=subject, body=body, html_body=html_body,
        template_name="welcome", related_type="user", related_id=user.id,
        company_id=user.company_id or 1,
    )


# ── 비밀번호 재설정 ───────────────────────────────────────────────────────────

def send_password_reset(db: Session, user) -> None:
    link = f"{BASE_URL}/reset-password?token={user.reset_token}"
    subject = "[BLEND PUNCH] 비밀번호 재설정 링크"
    body = (
        f"안녕하세요, {user.username}님!\n\n"
        f"비밀번호 재설정 요청이 접수되었습니다.\n\n"
        f"아래 링크를 클릭하여 새 비밀번호를 설정해주세요:\n"
        f"{link}\n\n"
        f"링크는 1시간 동안 유효합니다.\n\n"
        f"본인이 요청하지 않으셨다면 이 메일을 무시해주세요.\n\n"
        f"감사합니다.\nBLEND PUNCH 팀"
    )
    html_body = _render_html("reset_password", subject=subject, username=user.username, link=link)
    send_email(
        db, to_email=user.email, to_name=user.username,
        subject=subject, body=body, html_body=html_body,
        template_name="password_reset", related_type="user", related_id=user.id,
        company_id=user.company_id or 1,
    )


# ── 결제 완료 알림 ────────────────────────────────────────────────────────────

def send_payment_complete(db: Session, order) -> None:
    if not order.customer_email:
        return
    subject = f"[BLEND PUNCH] 주문이 완료되었습니다 (#{order.order_number})"
    body = (
        f"안녕하세요, {order.customer_name}님!\n\n"
        f"주문이 성공적으로 완료되었습니다.\n\n"
        f"주문번호: {order.order_number}\n"
        f"결제금액: {order.total_price:,}원\n"
        f"결제수단: {order.payment_method or '-'}\n\n"
        f"배송이 시작되면 별도로 안내드리겠습니다.\n\n"
        f"감사합니다.\nBLEND PUNCH 팀"
    )
    send_email(
        db, to_email=order.customer_email, to_name=order.customer_name,
        subject=subject, body=body,
        template_name="payment_complete", related_type="order", related_id=order.id,
        company_id=order.company_id or 1,
    )


# ── 공구 신청 접수 알림 ───────────────────────────────────────────────────────

def send_application_received(db: Session, application, to_email: str, to_name: str) -> None:
    subject = "[BLEND PUNCH] 공구 신청이 접수되었습니다"
    body = (
        f"안녕하세요, {to_name}님!\n\n"
        f"공구 신청이 정상적으로 접수되었습니다.\n\n"
        f"검토 후 빠르게 연락드리겠습니다.\n\n"
        f"감사합니다.\nBLEND PUNCH 팀"
    )
    send_email(
        db, to_email=to_email, to_name=to_name,
        subject=subject, body=body,
        template_name="application_received",
        related_type="application", related_id=str(application.id),
        company_id=application.company_id or 1,
    )


def send_application_approved(db: Session, application, to_email: str, to_name: str) -> None:
    subject = "[BLEND PUNCH] 공구 신청이 승인되었습니다"
    body = (
        f"안녕하세요, {to_name}님!\n\n"
        f"신청하신 공구가 승인되었습니다.\n\n"
        f"담당자가 곧 연락드릴 예정입니다.\n\n"
        f"감사합니다.\nBLEND PUNCH 팀"
    )
    send_email(
        db, to_email=to_email, to_name=to_name,
        subject=subject, body=body,
        template_name="application_approved",
        related_type="application", related_id=str(application.id),
        company_id=application.company_id or 1,
    )
