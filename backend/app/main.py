import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, chat, insights, investments, journal, learn, memory, tasks
from app.api import jobs as jobs_api
from app.api import notifications as notifications_api
from app.api import settings as settings_api
from app.config import DEV_JWT_SECRET, settings
from app.jobs import scheduler
from app.services.backups import check_tooling
from app.services.errors import Duplicate, Invalid, NotFound

# Secrets that turn up inside log TEXT rather than being logged deliberately: httpx's
# request log, an HTTPStatusError message, a traceback. Rather than chase each source, they
# are scrubbed from the final formatted string.
#
# This existed originally because a Telegram bot token lives in the URL PATH and was being
# written to production logs on every poll. That channel is gone, and the rule stays: a
# provider URL can still carry `?key=`, and the VAPID endpoint is a third-party URL we POST
# to. The reason changed; the decision did not.
_SECRET_PATTERNS = [
    # ?key=... / &api_key=... / token=... in any URL.
    #
    # ⚠ `key` is listed SEPARATELY from `api[_-]?key`, and that is not redundancy. An
    # earlier version of this pattern read `(?:api[_-]?key|token|access_token)=` while its
    # comment claimed to cover `?key=` — which it did not, because `api` was required. That
    # is the exact form the Gemini Developer API uses
    # (`generativelanguage.googleapis.com/...?key=<SECRET>`), so the one provider URL most
    # likely to carry a raw key in a log was the one shape not being redacted. Found by
    # writing the test that asserts each spelling individually.
    #
    # The lookbehind matters: without it this also ate `first_token=2584ms` out of the
    # per-turn timing line, silently destroying telemetry to protect a secret that was
    # never there. Redaction that removes real data is its own kind of bug. It is also what
    # keeps `key` from matching inside `cache_key=` or `monkey=`.
    re.compile(r"(?<![\w-])((?:api[_-]?key|key|access[_-]?token|token)=)[^&\s'\"]+", re.IGNORECASE),
]


class RedactingFormatter(logging.Formatter):
    """Strips secrets from every log line, including tracebacks.

    Applied to the formatter rather than as a filter on purpose: a filter sees
    `record.msg` and `record.args`, but an exception's text is rendered later, and that is
    exactly where a bot token was still appearing after httpx had been silenced.
    """

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(r"<redacted>", text)
        return text


def configure_logging() -> None:
    """Make our own logs visible without touching uvicorn's. The per-turn timing line
    (logger "aceroai.timing") is how latency is verified against a stopwatch."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("aceroai.timing").setLevel(logging.INFO)

    # Scrub secrets from anything that reaches a handler, whoever wrote it.
    for handler in logging.getLogger().handlers:
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))

    # httpx logs every request URL at INFO. This was raised to WARNING after a Telegram
    # bot token — which lives in the URL path — was confirmed live in this app's own log
    # output, on every poll, roughly every 25 seconds, forever.
    #
    # That channel is retired and the level stays where it is: provider URLs can carry a
    # key in the query string, and push endpoints are third-party URLs. Failures still
    # surface — httpx logs those at WARNING and above, and our handlers log provider
    # errors themselves.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def check_production_config() -> None:
    """Refuse to run in production with the built-in dev secret."""
    if settings.app_env == "prod" and settings.jwt_secret == DEV_JWT_SECRET:
        raise RuntimeError(
            "APP_ENV=prod but JWT_SECRET is still the dev default. "
            "Set a real JWT_SECRET in .env before deploying."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    check_production_config()
    # Says so at deploy if a bucket is configured but this image cannot take a dump —
    # otherwise the first symptom would be a notification at 02:30 some night later.
    check_tooling()
    # The job scheduler holds the background slot the Telegram poller used to occupy. It
    # registers exactly ONE APScheduler job — a tick — and `app/jobs/runner.py` plus the
    # `job_runs` table decide what actually runs. See docs/JOBS.md.
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="aceroai", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(tasks.router)
app.include_router(journal.router)
app.include_router(memory.router)
app.include_router(insights.router)
app.include_router(investments.router)
app.include_router(learn.router)
app.include_router(settings_api.router)
app.include_router(notifications_api.router)
app.include_router(jobs_api.router)


# Map domain errors from the service layer to HTTP so routes stay thin. (The
# assistant's tools catch these same errors directly, without HTTP.)
@app.exception_handler(NotFound)
async def _not_found(request: Request, exc: NotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(Invalid)
async def _invalid(request: Request, exc: Invalid) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


@app.exception_handler(Duplicate)
async def _duplicate(request: Request, exc: Duplicate) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
