import asyncio
import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, chat, insights, journal, learn, memory, tasks
from app.api import settings as settings_api
from app.channels import telegram
from app.config import DEV_JWT_SECRET, settings
from app.services.errors import Duplicate, Invalid, NotFound

# Secrets that turn up inside log TEXT rather than being logged deliberately. A Telegram
# bot token lives in the URL path, so any library or exception that mentions the URL leaks
# it: httpx's request log, an HTTPStatusError message, a traceback. Rather than chase each
# source, the token is scrubbed from the final formatted string.
_SECRET_PATTERNS = [
    # api.telegram.org/bot<id>:<secret>/method
    re.compile(r"(bot\d+:)[A-Za-z0-9_-]{20,}"),
    # ?key=... / &api_key=... / token=... in any URL.
    # The lookbehind matters: without it this also ate `first_token=2584ms` out of the
    # per-turn timing line, silently destroying telemetry to protect a secret that was
    # never there. Redaction that removes real data is its own kind of bug.
    re.compile(r"(?<![\w-])((?:api[_-]?key|token|access_token)=)[^&\s'\"]+", re.IGNORECASE),
]


class RedactingFormatter(logging.Formatter):
    """Strips secrets from every log line, including tracebacks.

    Applied to the formatter rather than as a filter on purpose: a filter sees
    `record.msg` and `record.args`, but an exception's text is rendered later, and that is
    exactly where the Telegram token was still appearing after httpx was silenced.
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

    # httpx logs every request URL at INFO. Telegram puts the bot token IN the URL path
    # (api.telegram.org/bot<TOKEN>/getUpdates), so the secret was being written to the
    # console and to production logs on every poll — roughly every 25 seconds, forever.
    # Confirmed live in this app's own log output before it was raised to WARNING.
    #
    # Failures still surface: httpx logs those at WARNING and above, and our own handlers
    # log provider errors themselves.
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
    # Telegram poller runs only when a token is configured (Feature 3: scheduler here too)
    poller = None
    if settings.telegram_bot_token:
        poller = asyncio.create_task(telegram.run_poller())
    try:
        yield
    finally:
        if poller is not None:
            poller.cancel()
            try:
                await poller
            except asyncio.CancelledError:
                pass


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
app.include_router(learn.router)
app.include_router(settings_api.router)


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
