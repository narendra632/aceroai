from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, chat
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Feature 2/3: telegram poller + APScheduler start here
    yield


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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
