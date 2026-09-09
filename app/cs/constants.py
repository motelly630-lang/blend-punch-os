"""CS(고객서비스) 모듈 고정 상수.

1차 개발 방침: 처리상태(status)와 처리방법(resolution)은 시스템 고정값으로 둔다.
추후 관리자 편집형(테이블)으로 확장할 수 있도록, 화면/로직에서 이 상수만 참조하고
문자열을 여기저기 하드코딩하지 않는다. (CS 유형은 요구사항[7]대로 cs_types 테이블로 관리)

badge_class 는 Tailwind 정적 빌드가 스캔할 수 있도록 '완성된 클래스 문자열'로 둔다.
(동적 조합 `bg-{{c}}-50` 형태는 purge 되므로 금지 — tailwind content 글롭에 app/**/*.py 포함 필요)
"""

# ── 처리상태 (요구사항 8) — code → (라벨, badge_class) ──────────────────────────
CS_STATUSES = [
    ("received",         "CS 인입",       "bg-gray-100 text-gray-700"),
    ("internal_review",  "내부 확인중",   "bg-blue-50 text-blue-600"),
    ("partner_pending",  "협업사 전달대기", "bg-indigo-50 text-indigo-600"),
    ("partner_waiting",  "협업사 답변대기", "bg-purple-50 text-purple-600"),
    ("processing",       "처리중",         "bg-amber-50 text-amber-600"),
    ("customer_waiting", "고객 확인대기",   "bg-cyan-50 text-cyan-600"),
    ("completed",        "처리완료",       "bg-green-50 text-green-600"),
    ("hold",             "보류",           "bg-orange-50 text-orange-600"),
    ("closed",           "취소/종료",       "bg-red-50 text-red-600"),
]
CS_STATUS_LABELS = {code: label for code, label, _ in CS_STATUSES}
CS_STATUS_BADGES = {code: cls for code, _, cls in CS_STATUSES}
CS_STATUS_CODES = [code for code, _, _ in CS_STATUSES]
CS_STATUS_DEFAULT = "received"
# 미처리로 간주하는 상태 (통계·빠른탭용)
CS_STATUS_OPEN = ["received", "internal_review", "partner_pending", "partner_waiting", "processing", "customer_waiting", "hold"]

# ── 처리방법 (요구사항 9) — code → 라벨 ─────────────────────────────────────────
CS_RESOLUTIONS = [
    ("guide_close",     "안내 후 종료"),
    ("partial_refund",  "부분환불"),
    ("full_refund",     "전체환불"),
    ("resend",          "재발송"),
    ("missing_resend",  "누락상품 추가발송"),
    ("exchange",        "교환"),
    ("return",          "반품"),
    ("collect_inspect", "회수 후 검수"),
    ("coupon_point",    "쿠폰/적립금"),
    ("partner_check",   "협업사 확인 필요"),
    ("request_docs",    "고객 추가자료 요청"),
    ("etc",             "기타"),
]
CS_RESOLUTION_LABELS = {code: label for code, label in CS_RESOLUTIONS}
CS_RESOLUTION_CODES = [code for code, _ in CS_RESOLUTIONS]

# 처리방법별 추가 입력 항목 (resolution_detail JSON 에 저장할 키) — 요구사항 9
# 화면에서 처리방법 선택 시 해당 필드만 노출한다.
CS_RESOLUTION_FIELDS = {
    "partial_refund": ["refund_amount", "refund_due_date", "refund_done_date", "refund_by", "refund_memo"],
    "full_refund":    ["refund_amount", "refund_due_date", "refund_done_date", "refund_by", "refund_memo"],
    "resend":         ["resend_product", "resend_option", "resend_qty", "resend_due_date", "resend_done_date", "resend_courier", "resend_tracking", "resend_by"],
    "missing_resend": ["resend_product", "resend_option", "resend_qty", "resend_due_date", "resend_done_date", "resend_courier", "resend_tracking", "resend_by"],
    "exchange":       ["collect_needed", "collect_due_date", "collect_tracking", "collect_done_date", "inspect_result", "extra_shipping_fee", "handler"],
    "return":         ["collect_needed", "collect_due_date", "collect_tracking", "collect_done_date", "inspect_result", "extra_shipping_fee", "handler"],
}

# ── 접수경로 (요구사항 5) ────────────────────────────────────────────────────────
CS_CHANNELS = [
    ("kakao_channel", "카카오톡채널"),
    ("dm",            "DM"),
    ("influencer",    "인플루언서"),
    ("partner",       "협업사"),
]
CS_CHANNEL_LABELS = {code: label for code, label in CS_CHANNELS}

# ── 주문 출처 ────────────────────────────────────────────────────────────────────
ORDER_SOURCES = [
    ("self_mall",     "자사몰"),
    ("external_link", "외부링크"),
]
ORDER_SOURCE_LABELS = {code: label for code, label in ORDER_SOURCES}

# ── 판매채널 ────────────────────────────────────────────────────────────────────
SALES_CHANNELS = [
    ("instagram", "인스타그램"),
    ("youtube",   "유튜브"),
    ("tiktok",    "틱톡"),
]
SALES_CHANNEL_LABELS = {code: label for code, label in SALES_CHANNELS}

# ── 타임라인 활동 유형 (요구사항 11) — cs_activities.activity_type ──────────────
# 댓글류(내부메모/공개댓글/협업사답변/고객안내)와 시스템 이벤트를 하나의 타임라인에 통합
ACT_CREATED          = "created"
ACT_EDITED           = "edited"
ACT_STATUS_CHANGE    = "status_change"
ACT_ASSIGN           = "assign"
ACT_FORWARD_PARTNER  = "forward_partner"
ACT_RESOLUTION       = "resolution_change"
ACT_ATTACHMENT       = "attachment"
ACT_REOPENED         = "reopened"
ACT_COMPLETED        = "completed"
# 댓글류 (body 사용)
ACT_INTERNAL_MEMO    = "internal_memo"     # visibility=internal — 협업사 절대 미노출
ACT_PARTNER_PUBLIC   = "partner_public"    # visibility=partner  — 협업사 공개 댓글
ACT_PARTNER_REPLY    = "partner_reply"     # visibility=partner  — 협업사 답변
ACT_CUSTOMER_NOTICE  = "customer_notice"   # visibility=all      — 고객 안내기록

# visibility 값
VIS_INTERNAL = "internal"   # 내부 전용
VIS_PARTNER  = "partner"    # 내부 + 해당 협업사
VIS_ALL      = "all"        # 내부 + 협업사 공통

# 협업사에게 보여줄 수 있는 활동 visibility
PARTNER_VISIBLE_VISIBILITIES = [VIS_PARTNER, VIS_ALL]

# ── 기본 CS 유형 19종 (요구사항 7) — cs_types 시드용 ─────────────────────────────
DEFAULT_CS_TYPES = [
    "배송지연", "미출고", "파손", "누락", "오배송", "상품불량", "변질",
    "중량미달", "포장불량", "진공풀림", "결로", "취소", "교환", "반품",
    "전체환불", "부분환불", "사용문의", "상품문의", "기타",
]

# ── 첨부파일 제한 (요구사항 10) ─────────────────────────────────────────────────
CS_MAX_IMAGES = 20
CS_MAX_FILES = 5                       # 영상/기타 파일
CS_MAX_FILE_SIZE = 20 * 1024 * 1024    # 개별 20MB
CS_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "heic", "bmp"}
CS_VIDEO_EXTS = {"mp4", "mov", "avi", "webm", "mkv"}
CS_DOC_EXTS = {"pdf", "xlsx", "xls", "docx", "doc", "hwp", "hwpx", "txt", "csv", "zip"}
# 업로드 절대 금지 확장자 (실행파일 등)
CS_BLOCKED_EXTS = {"exe", "bat", "cmd", "com", "sh", "js", "jar", "msi", "app", "scr", "ps1", "vbs", "dll"}
