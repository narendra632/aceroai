from pydantic_settings import BaseSettings, SettingsConfigDict

# The built-in dev secret. Production refuses to start while JWT_SECRET is this
# (see app.main), so a real deployment can never ship with the sample key.
DEV_JWT_SECRET = "dev-not-secret-override-in-env"


class Settings(BaseSettings):
    # ".env" resolves when running from repo root / docker;
    # "../.env" resolves when running natively from backend/
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://agent:agent@localhost:5432/agent"
    jwt_secret: str = DEV_JWT_SECRET

    # provider swap = change base_url + api_key + models in .env. no code changes.
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    model_chat: str = "gemini-2.5-flash"
    model_heavy: str = "gemini-2.5-pro"

    # Reasoning ("thinking") budget. Chat defaults to "low" (fast first token);
    # "deep" is used when the user asks to think harder or a heavy task routes to
    # it. Empty = don't send the param (for providers that don't support it).
    reasoning_effort_chat: str = "low"
    reasoning_effort_deep: str = "high"
    # Retry transient provider errors (timeout/connection/rate-limit) this many
    # times, only before the first token (never duplicates streamed output).
    llm_max_retries: int = 2
    # Reject a user message longer than this (chars) before persisting/calling.
    max_input_chars: int = 16000
    # Max tool-use rounds the assistant may take in one turn before it must answer
    # with text (guards against a runaway tool loop).
    tools_max_iters: int = 5

    # --- memory (pgvector) ---
    embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768  # matches the profile_facts.embedding vector column
    memory_recall_k: int = 12  # max relevant facts injected per message
    memory_dedup_distance: float = 0.12  # cosine distance below which a fact is a dup
    model_memory: str = ""  # extractor model; empty = use model_chat
    memory_extraction_enabled: bool = True

    app_timezone: str = "Asia/Kolkata"
    frontend_origin: str = "http://localhost:5173"
    telegram_bot_token: str = ""

    # --- production ---
    app_env: str = "dev"  # "prod" enables the startup secret check
    # The auth cookie. In prod behind HTTPS with a cross-site frontend (Vercel),
    # set cookie_secure=true and cookie_samesite="none" so the browser sends it.
    cookie_secure: bool = False
    cookie_samesite: str = "lax"
    # Absolute path to SOUL.md when docs/ isn't alongside the code (prod image);
    # empty = use the repo-relative path. The prod compose mounts docs and sets it.
    soul_path: str = ""


settings = Settings()
