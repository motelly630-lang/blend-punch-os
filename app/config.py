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


settings = Settings()
