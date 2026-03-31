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
    # Instagram 봇 계정
    instagram_username: str = ""
    instagram_password: str = ""
    # 카카오 알림톡 (알리고 비즈메시지)
    kakao_mock: bool = True              # false 설정 시 실제 발송
    kakao_api_key: str = ""
    kakao_user_id: str = ""
    kakao_sender_key: str = ""
    kakao_ship_template: str = ""        # 배송시작 알림톡 템플릿 코드


settings = Settings()
