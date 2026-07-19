from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ".env" resolves when running from repo root / docker;
    # "../.env" resolves when running natively from backend/
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://agent:agent@localhost:5432/agent"
    jwt_secret: str = "dev-not-secret-override-in-env"

    # provider swap = change base_url + api_key + models in .env. no code changes.
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    model_chat: str = "gemini-2.5-flash"
    model_heavy: str = "gemini-2.5-pro"

    app_timezone: str = "Asia/Kolkata"
    frontend_origin: str = "http://localhost:5173"
    telegram_bot_token: str = ""


settings = Settings()
