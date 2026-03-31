"""
카카오 알림톡 발송 서비스

[Mock 모드]
기본값으로 실제 발송 없이 로그만 출력합니다.
.env에 KAKAO_MOCK=false + 나머지 키 설정 시 실제 발송됩니다.

[실제 연동 전 설정 필요]
.env에 아래 항목 추가:
  KAKAO_MOCK=false
  KAKAO_API_KEY=...          # 알리고 API KEY
  KAKAO_USER_ID=...          # 알리고 USER ID
  KAKAO_SENDER_KEY=...       # 카카오 채널 발신프로필 키
  KAKAO_SHIP_TEMPLATE=...    # 배송시작 알림톡 템플릿 코드

[지원 알림 유형]
- send_kakao_shipping(order): 배송 시작 알림
"""
import logging

logger = logging.getLogger(__name__)


def _is_mock() -> bool:
    try:
        from app.config import settings
        return getattr(settings, "kakao_mock", True)
    except Exception:
        return True


async def send_kakao_shipping(order) -> bool:
    """
    배송 시작 알림톡 발송.
    order: app.models.order.Order 인스턴스
    반환: 발송 성공 여부 (실패해도 주문 처리는 계속됨)
    """
    if _is_mock():
        logger.info(
            "[KAKAO MOCK] 배송알림 → %s (%s) | 택배사: %s | 송장: %s | 주문번호: %s",
            order.customer_name,
            order.customer_phone,
            order.carrier_name or "-",
            order.tracking_number or "-",
            order.order_number,
        )
        return True

    return await _send_real(order)


async def _send_real(order) -> bool:
    """
    실제 카카오 알림톡 API 연동 (알리고 비즈메시지 기준).

    다른 API 제공사 사용 시 이 함수만 교체하면 됩니다:
    - 솔라피(Solapi), NHN Cloud, 카카오 공식 등

    ※ 템플릿 변수는 사전에 카카오 채널 관리자센터에서 등록 필요
    """
    try:
        import httpx
        from app.config import settings

        message = (
            f"안녕하세요 {order.customer_name}님,\n"
            f"주문하신 상품이 발송되었습니다.\n\n"
            f"[주문번호] {order.order_number}\n"
            f"[택배사] {order.carrier_name or '-'}\n"
            f"[송장번호] {order.tracking_number or '-'}\n\n"
            f"감사합니다."
        )

        payload = {
            "apikey": settings.kakao_api_key,
            "userid": settings.kakao_user_id,
            "senderkey": settings.kakao_sender_key,
            "tpl_code": settings.kakao_ship_template,
            "receiver_1": order.customer_phone,
            "subject_1": "배송 시작 안내",
            "message_1": message,
        }

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                "https://kakaoapi.aligo.in/akv10/alimtalk/send/",
                data=payload,
            )
            result = resp.json()
            if result.get("code") == 0:
                logger.info("[KAKAO] 발송 성공 → %s", order.customer_phone)
                return True
            logger.warning("[KAKAO] 발송 실패 (code=%s): %s", result.get("code"), result.get("message"))
            return False

    except Exception as e:
        logger.error("[KAKAO] 발송 오류 (주문 처리는 계속): %s", e)
        return False
