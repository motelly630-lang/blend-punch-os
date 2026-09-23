from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    openai_api_key: str = ""
    toss_client_key: str = "test_ck_docs_Ovk5rk1EwkEbP0W43n07xlzm"
    toss_secret_key: str = "test_sk_docs_OePRyFnQvLBb0W02GKlEe9GR"
    database_url: str = "sqlite:///./blendpunch.db"
    app_secret: str = "dev-secret"
    secret_key: str = "dev-jwt-secret-change-in-production"
    remove_bg_api_key: str = ""
    # Google Sheets (제품 소싱 에이전트 → 시트 자동입력)
    google_sa_json: str = ""        # 서비스계정 키 JSON 파일 경로
    sourcing_sheet_id: str = ""     # 대상 스프레드시트 ID (URL의 /d/<여기>/edit)
    integrated_sheet_id: str = ""   # 통합 운영 스프레드시트 ID (마스터 임포트용)
    sheet_autosync: bool = False        # 통합시트 자동 동기화 (기본 꺼짐 — 로컬이 운영시트를 건드리지 않게)
    sheet_autosync_minutes: int = 10    # 자동 동기화 주기(분)
    influencer_enrich: bool = False      # 인스타 프로필 자동수집 (기본 꺼짐)
    influencer_enrich_limit: int = 10    # 1회(1일) 수집 인원 — 신규 계정 워밍업용 보수값. 늘리면 차단 위험
    # 네이버 검색 API (제품 URL/이미지 자동 보강)
    naver_client_id: str = ""
    naver_client_secret: str = ""
    # S3 백업 설정
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-northeast-2"
    s3_backup_bucket: str = ""
    s3_assets_bucket: str = ""  # 이미지 서빙용 퍼블릭 버킷 (미설정 시 s3_backup_bucket 사용)
    # Meta 공식 Instagram API (Business Discovery) — DE-006. 페이지 토큰은 서버 .env 에만
    meta_page_token: str = ""
    meta_ig_user_id: str = ""            # 조회에 쓰는 우리 인스타 계정 ID (@blend_punch)
    meta_graph_version: str = "v25.0"
    # Instagram 봇 계정 (구 방식 — Meta 설정이 없을 때만 사용)
    instagram_username: str = ""
    instagram_password: str = ""
    # 내부 알림 웹훅 (슬랙 / 카카오워크 / 디스코드 공용)
    alert_mock: bool = True              # false 설정 시 실제 발송
    alert_webhook_url: str = ""          # 발급받은 웹훅 URL 하나만 넣으면 됨
    campaign_alert: bool = False         # 공구 알림 자동발송 (기본 꺼짐)
    campaign_alert_hour: int = 8         # 발송 시각 (KST, 정시)
    # Slack 앱 (채널별 발송 — app/services/slack_notify.py). 위 웹훅(아침 보고)과 별개로 동작하며,
    # 토큰이 없으면 발송하지 않고 실패로 기록한다. 실발송 여부는 alert_mock 을 따른다.
    slack_bot_token: str = ""            # xoxb-... (Bot User OAuth Token)
    slack_channels: str = ""             # "groupbuy=C0123,seller=C0456" — 채널 ID 또는 이름. 비우면 기본 이름
    slack_dm_user: str = ""              # 시스템 이상 알림을 받을 대표님 Slack 멤버 ID (U...)
    slack_events: str = ""               # 켤 자동 알림 이벤트 (쉼표). 비우면 전부 꺼짐
    # 카카오 알림톡 (알리고 비즈메시지)
    kakao_mock: bool = True              # false 설정 시 실제 발송
    kakao_api_key: str = ""
    kakao_user_id: str = ""
    kakao_sender_key: str = ""
    kakao_ship_template: str = ""        # 배송시작 알림톡 템플릿 코드
    # 이메일 발송 (SMTP)
    email_mock: bool = True              # true이면 실제 발송 없이 로그만
    smtp_host: str = "smtp.gmail.com"   # Gmail/Workspace: smtp.gmail.com | Hostinger: smtp.hostinger.com
    smtp_port: int = 587                # Gmail: 587 (STARTTLS) | Hostinger: 587 or 465
    smtp_user: str = ""                 # admin@blendpunch.com
    smtp_password: str = ""             # 앱 비밀번호 (Gmail) or 계정 비밀번호 (Hostinger)
    smtp_from: str = ""                 # "BLEND PUNCH <admin@blendpunch.com>"
    smtp_use_ssl: bool = False          # True이면 SSL(465), False이면 STARTTLS(587)
    app_base_url: str = "https://os.blendpunch.com"   # 이메일 링크용 베이스 URL
    cookie_domain: str = ""                            # 쿠키 도메인 (로컬: 빈값, 운영: .blendpunch.com)
    # Claw 연동 토큰 (Bearer 인증)
    claw_api_token: str = ""


settings = Settings()
