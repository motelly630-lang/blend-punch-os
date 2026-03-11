from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    database_url: str = "sqlite:///./blendpunch.db"
    app_secret: str = "dev-secret"
    secret_key: str = "dev-jwt-secret-change-in-production"


settings = Settings()
