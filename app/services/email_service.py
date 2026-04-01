"""
이메일 발송 서비스 (SMTP + Mock 모드)

- email_mock=True (기본): 실제 발송 없이 DB 로그만 기록 (개발/테스트용)
- email_mock=False: STARTTLS SMTP 실제 발송
"""
import smtplib
import uuid
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.config import settings
from app.models.email_log import EmailLog


def _send_smtp(to_email: str, to_name: str, subject: str, body: str, html_body: str = "") -> None:
    """SMTP 발송 (STARTTLS 587 or SSL 465). 실패 시 예외 raise."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    from_addr = settings.smtp_from or settings.smtp_user

    if settings.smtp_use_ssl:
        # SSL (포트 465) — Hostinger 등
        import ssl as _ssl
        ctx = _ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=15) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(from_addr, [to_email], msg.as_string())
    else:
        # STARTTLS (포트 587) — Gmail / Google Workspace / Hostinger
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(from_addr, [to_email], msg.as_string())


def send_email(
    db: Session,
    *,
    to_email: str,
    to_name: str = "",
    subject: str,
    body: str,
    html_body: str = "",
    template_name: str = "",
    related_type: str = "",
    related_id: str = "",
    created_by: str = "",
    company_id: int = 1,
) -> EmailLog:
    """
    이메일을 발송하고 EmailLog에 기록한다.

    Returns:
        EmailLog — 생성된 로그 레코드 (status: sent or failed)
    """
    log = EmailLog(
        id=str(uuid.uuid4()),
        company_id=company_id,
        to_email=to_email,
        to_name=to_name or "",
        subject=subject,
        body=body,
        template_name=template_name or None,
        status="pending",
        related_type=related_type or None,
        related_id=related_id or None,
        created_by=created_by or None,
    )
    db.add(log)
    db.flush()  # get id without commit

    if settings.email_mock:
        log.status = "sent"
        log.sent_at = datetime.utcnow()
        log.error_msg = "[MOCK] 실제 발송 없음 — email_mock=True"
    else:
        try:
            _send_smtp(to_email, to_name, subject, body, html_body)
            log.status = "sent"
            log.sent_at = datetime.utcnow()
        except Exception as e:
            log.status = "failed"
            log.error_msg = str(e)[:500]

    db.commit()
    return log


def render_template(template_key: str, variables: dict) -> tuple[str, str]:
    """
    내장 템플릿 키로 subject/body를 렌더링한다.

    Returns:
        (subject, body) — {variable} 치환 완료
    """
    from app.models.email_log import EMAIL_TEMPLATES
    tpl = EMAIL_TEMPLATES.get(template_key)
    if not tpl:
        raise ValueError(f"알 수 없는 템플릿: {template_key}")

    subject = tpl["subject"].format_map(_SafeDict(variables))
    body = tpl["body"].format_map(_SafeDict(variables))
    return subject, body


class _SafeDict(dict):
    """존재하지 않는 키는 '{key}' 그대로 남긴다."""
    def __missing__(self, key):
        return "{" + key + "}"
