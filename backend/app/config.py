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
    # while a region takes ~0.5-2s. Vectors are identical across regions (verified
    # cosine 1.000000), so this changes latency only — never stored meaning.
    #
    # Pick the region nearest the SERVER, not the user: from the Oregon VM that is
    # us-central1 (~1.8s); developing from India, asia-south1 is ~486ms. Override
    # EMBED_LOCATION per environment. See docs/REQUEST-ANATOMY.md.
    embed_location: str = "us-central1"
    # A CEILING, not a quota. Recall used to return exactly this many facts on every
    # message — including "write a python function", which has nothing to do with the
    # user. The hybrid selection below returns fewer (measured: 0-8 on real queries), so
    # this number now only matters when a message really does touch many stored facts.
    # Raised 12 -> 16 when lexical-only admission was added, so a third admission lane
    # cannot push consensus facts (the best ones) off the end.
    memory_recall_k: int = 16
    # Hard ceiling on recall. Recall is best-effort by design, so if the embedding call
    # stalls we answer without facts rather than making the user wait — this bounds the
    # tail latency instead of letting one slow call dominate the whole turn.
    memory_recall_timeout_s: float = 4.0
    memory_dedup_distance: float = 0.12  # cosine distance below which a fact is a dup

    # --- hybrid recall (migration 010) ---
    # Two rankers search independently and their POSITIONS are fused; a fact both of them
    # found is trusted, a fact only one found is a guess that must clear a quality bar.
    # See openspec design Decision 4 — every number here was measured, not chosen.
    #
    # How many candidates each ranker contributes before fusion. Small on purpose: RRF
    # weights the head of each list heavily, so a deeper pool changes nothing but cost.
    recall_pool: int = 20
    # Reciprocal Rank Fusion damping. The standard constant; it makes the gap between
    # rank 1 and 2 matter more than the gap between rank 11 and 12.
    rrf_k: int = 60
    # Most terms taken from one message. A three-paragraph message carries ~50 content
    # words; OR-ing all of them matches nearly every fact (measured: 219 ms at 20k facts).
    # The 8 kept are the RAREST, not the first 8 — the rare ones identify a fact.
    lexical_terms_max: int = 8
    # Drop a query term appearing in more than this share of the user's facts. Every fact
    # begins with the user's name by design, so this is a real query shape, not a
    # hypothetical. This is the one thing IDF would have told us, applied by hand.
    lexical_max_df: float = 0.30
    # A term at or below this share is *identifying*. Only a fact matched by such a term
    # may be admitted on the lexical ranker alone — the lexical equivalent of the
    # vector-only distance floor.
    lexical_rare_df: float = 0.10
    # Ratios are meaningless on a tiny memory (at 5 facts, a word in 2 of them is 40%).
    # Below these counts the ratio is ignored, so a new user's recall is not crippled.
    lexical_df_min_docs: int = 3
    # A word in one or two facts is identifying no matter how large memory gets.
    lexical_rare_min_docs: int = 2
    # How many distinct words get an exact document-frequency measurement. Beyond this the
    # longest are measured first — length is a stated proxy for rarity, used only to pick
    # what to measure, never to rank. Real messages sit well inside this.
    lexical_df_terms_max: int = 32
    # Ceiling on the candidate set handed to ts_rank. Ranking cost is linear in matches, so
    # this bounds it by a constant. With the DF filter applied it does not bind at
    # realistic sizes; it exists so a pathological corpus degrades in quality, not latency.
    lexical_candidate_max: int = 500
    # Top-ups when the two rankers do not agree. Agreement is the signal; these stop a
    # vague-but-personal question ("what should I do today") from recalling nothing.
    vector_only_max: int = 4
    lexical_only_max: int = 3
    # A vector-only fact must be at least this close. MEASURED: one person's facts occupy
    # a 0.30-0.58 cosine band, and 0.52 is the one place the data separates cleanly —
    # above it lie the queries that are not about the user at all.
    vector_only_max_distance: float = 0.52
    # A LOOSER outer bound, applied to facts both rankers found. The vector ranker does not
    # "find" anything — it returns its 20 nearest rows whether or not any relate to the
    # message — so its agreement only means something while the query is inside the band
    # where one person's facts actually live (0.30-0.58 measured; 0.60 leaves headroom).
    # Past it the vector ranker had no opinion, and calling that agreement would report a
    # consensus to the user that never happened. Such facts fall back to the lexical gate.
    consensus_max_distance: float = 0.60
    model_memory: str = ""  # extractor model; empty = use model_chat
    memory_extraction_enabled: bool = True

    app_timezone: str = "Asia/Kolkata"
    frontend_origin: str = "http://localhost:5173"

    # --- scheduled jobs (migration 011) ---
    # How often the ticker asks "is anything due". NOT how often jobs run — a job's own
    # cron decides that. This only bounds how late a due job starts, and how quickly a run
    # missed during a deploy is recovered. Five minutes is well under the shortest gap
    # between any job's occurrences (one hour).
    job_tick_seconds: int = 300
    # Default staleness policy: a job missed by more than this is recorded and NOT run
    # late, because a morning brief delivered at 6pm is noise. Per-job overridable.
    job_catch_up_hours: int = 24

    # --- notifications and web push (migration 011) ---
    # A P-256 keypair identifying this server to the browsers' push services. Generate ONCE
    # with `uv run python -m app.scripts.generate_vapid`; rotating it invalidates every
    # existing subscription. The public half is genuinely public and is served to the
    # browser; the private half is a secret and lives only in .env.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    # A contact URI the push service can use to reach the operator about a misbehaving
    # sender. Required by the VAPID spec; "mailto:" or "https:".
    vapid_subject: str = "mailto:acero@localhost"
    # How long a push service holds an undelivered message for a device that is offline.
    #
    # ⚠ This is NOT the value used for a notification a scheduled job raised. That one is
    # derived from the job's own `catch_up` window, which already declares how stale its
    # output may be — see `services/notifications.deliver`. This default applies only to
    # notifications no job produced: today, the test push from Settings.
    #
    # Two independent statements of staleness used to exist and they contradicted each other.
    # `day_end_summary` declares `catch_up=3h` — "by midnight, so it still lands on the day it
    # describes" — and was then handed to the push service with a 24-hour TTL, an instruction
    # to deliver the thing the runner had already refused to produce that late. One
    # declaration now serves both decisions, so they cannot drift apart again.
    push_ttl_default_s: int = 3600
    # Quiet hours, as local hours. A notification raised inside the window is still
    # WRITTEN — only the push is suppressed, so it is waiting in the app in the morning.
    quiet_hours_start: int = 22
    quiet_hours_end: int = 7
    # Ceiling on pushes per day. **0 means no ceiling, and is the default.**
    #
    # It used to default to 6, which was binding in ordinary use — `task_nudge` alone can
    # fire thirteen times a day — so it was quietly discarding notifications that were
    # wanted, beginning with the hourly overdue-task ping. Notification fatigue is real, but
    # per-tag suppression is what addresses it: the question is whether something is NEWS,
    # not how many times it has been said.
    #
    # Retained at zero rather than removed, because it is the only bound on volume that a
    # LOOPING job would respect. Set it if that day ever comes.
    daily_push_cap: int = 0
    # The notification history is a third table that only grows, so it is bounded by the
    # same nightly sweep that bounds traces. Soft-deleted rows age out on this same cutoff —
    # there is deliberately no second, shorter clock for them.
    notification_retention_days: int = 90
    # How full the disk may get before `disk_watch` says something, and the width of the
    # bands it reports in. Bands rather than exact percentages so a disk hovering around a
    # single number cannot chatter.
    disk_warn_percent: int = 80
    disk_band_percent: int = 5

    # --- trace retention (migration 008) ---
    # Observability must not consume the storage the application depends on. Spans are
    # ~8 rows per turn and carry the least long-term value: nobody asks about the latency
    # of one turn from eight months ago. Turns are kept far longer because they answer
    # questions people do ask. Beyond both, the `daily_usage` rollup is kept forever.
    span_retention_days: int = 30
    turn_retention_days: int = 400  # over a year, so year-on-year comparisons stay live

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

# Selectable models per provider, shown in Settings. Not a whitelist — the API also
# accepts a model outside this list, so a brand-new release is usable before this is
# updated.
#
# VERIFIED against each provider's live model list on 2026-08-18, after an earlier
# hand-written version offered `gpt-5.1-mini`, which does not exist. Every entry below
# was returned by the provider for this account. Ordered newest first, because that is
# the order a person scanning a dropdown expects.
MODEL_CATALOG: dict[str, list[str]] = {
    "google": [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite",
    ],
    "openai": [
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.2",
        "gpt-5.1",
        "gpt-4.1",
    ],
}

# Models that do NOT accept a reasoning/thinking control.
#
# This matters beyond a crash. The app's whole adaptive-reasoning feature — "think harder"
# on web — is a request for MORE deliberation. On a model without
# that capability the toggle changes nothing at all, and a control that silently does
# nothing is worse than one that isn't offered. Settings says so rather than letting the
# user discover it by not noticing a difference.
#
# Every Gemini model here takes a thinking_budget, so this is currently OpenAI-only.
NO_REASONING_CONTROL: frozenset[str] = frozenset(
    {
        "openai/gpt-4.1",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
    }
)


def supports_reasoning(provider: str, model: str) -> bool:
    """Whether picking this model for 'deep' actually buys deeper thinking."""
    return f"{provider}/{model}" not in NO_REASONING_CONTROL


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
