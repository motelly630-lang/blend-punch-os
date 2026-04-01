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
    # S3 백업 설정
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "ap-northeast-2"
    s3_backup_bucket: str = ""
    s3_assets_bucket: str = ""  # 이미지 서빙용 퍼블릭 버킷 (미설정 시 s3_backup_bucket 사용)
    # Instagram 봇 계정
    instagram_username: str = ""
    instagram_password: str = ""
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
    # Claw 연동 토큰 (Bearer 인증)
    claw_api_token: str = ""


settings = Settings()
