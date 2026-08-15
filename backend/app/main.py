import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, chat, journal, tasks
from app.channels import telegram
from app.config import DEV_JWT_SECRET, settings
from app.services.errors import Invalid, NotFound


def check_production_config() -> None:
    """Refuse to run in production with the built-in dev secret."""
    if settings.app_env == "prod" and settings.jwt_secret == DEV_JWT_SECRET:
        raise RuntimeError(
            "APP_ENV=prod but JWT_SECRET is still the dev default. "
            "Set a real JWT_SECRET in .env before deploying."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
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


# Map domain errors from the service layer to HTTP so routes stay thin. (The
# assistant's tools catch these same errors directly, without HTTP.)
@app.exception_handler(NotFound)
async def _not_found(request: Request, exc: NotFound) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(Invalid)
async def _invalid(request: Request, exc: Invalid) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
