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

    # --- model providers ---
    # Each provider is reached through its OWN native SDK (app/core/providers/), so no
    # provider's capabilities are degraded. Users pick provider + models in Settings;
    # these are the defaults used when a user hasn't chosen.
    llm_provider: str = "google"  # "google" | "openai"
    model_chat: str = "gemini-3.5-flash"
    model_heavy: str = "gemini-3.1-pro-preview"

    # Google (Agent Platform / Vertex): billed via Cloud Billing, authenticated with
    # Application Default Credentials — no API key. In prod the GCE VM's own service
    # account supplies ADC; locally use `gcloud auth application-default login`.
    google_cloud_project: str = ""
    google_cloud_location: str = "global"

    # OpenAI: the one provider that still needs a key (from .env, never the UI).
    openai_api_key: str = ""
    openai_base_url: str = ""  # optional override (proxy/compatible host)

    # Legacy Gemini Developer API (prepaid key). Kept only as a fallback path.
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""

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
    # How many open tasks are shown to the model each turn, so it can avoid duplicates,
    # act by id in one step, and surface what's due. Keeps context small on long lists.
    context_tasks_limit: int = 30

    # --- memory (pgvector) ---
    # PINNED ON PURPOSE. Every stored profile_facts vector was produced by this model;
    # vectors from a different model are not comparable (same length, different meaning),
    # so recall would silently return nonsense. Changing these is a deliberate re-embed
    # migration, never a side effect of the user's chat-provider choice.
    embed_provider: str = "google"
    embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768  # matches the profile_facts.embedding vector column
    # Embeddings are served from a REGION, not the "global" endpoint: measured, global
    # takes ~12s per embedding once the connection goes cold (i.e. every real message)
    # while us-central1 takes ~0.5-2s. Verified the vectors are identical across
    # regions (cosine 1.000000), so this changes latency only — never stored meaning.
    embed_location: str = "us-central1"
    memory_recall_k: int = 12  # max relevant facts injected per message
    # Hard ceiling on recall. Recall is best-effort by design, so if the embedding call
    # stalls we answer without facts rather than making the user wait — this bounds the
    # tail latency instead of letting one slow call dominate the whole turn.
    memory_recall_timeout_s: float = 4.0
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

# Selectable models per provider, shown in Settings. Model names churn, so this is a
# starting list, not a whitelist — the API also accepts a model outside it so a
# brand-new release is usable before this list is updated.
MODEL_CATALOG: dict[str, list[str]] = {
    "google": [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ],
    "openai": [
        "gpt-5.1",
        "gpt-5.1-mini",
        "gpt-5",
        "gpt-4.1",
        "gpt-4o",
    ],
}

PROVIDERS = tuple(MODEL_CATALOG)


def provider_available(provider: str) -> bool:
    """True when this provider's credentials are configured server-side. Google uses
    Application Default Credentials, so it only needs a project id; OpenAI needs a key.
    Credentials always come from the environment — never from the UI."""
    if provider == "google":
        return bool(settings.google_cloud_project)
    if provider == "openai":
        return bool(settings.openai_api_key)
    return False


def available_providers() -> list[str]:
    return [p for p in PROVIDERS if provider_available(p)]
