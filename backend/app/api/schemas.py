import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    email: str
    password: str


class MessageIn(BaseModel):
    message: str
    session_id: uuid.UUID | None = None
    deep: bool = False  # explicit "think harder": route this turn to deeper reasoning


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    channel: str
    last_active_at: dt.datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    content: str
    created_at: dt.datetime


# --- tasks ---


class TaskIn(BaseModel):
    title: str
    notes: str | None = None
    priority: int = Field(default=2, ge=1, le=3)  # 1 high · 2 mid · 3 low
    due_at: dt.datetime | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    status: str | None = None
    due_at: dt.datetime | None = None
    snoozed_until: dt.datetime | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    notes: str | None
    status: str
    priority: int
    due_at: dt.datetime | None
    snoozed_until: dt.datetime | None
    completed_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


# --- journal ---


class JournalIn(BaseModel):
    content: str
    mood: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None
    entry_date: dt.date | None = None


class JournalUpdate(BaseModel):
    content: str | None = None
    mood: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] | None = None


class JournalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_date: dt.date
    content: str
    mood: int | None
    tags: list[str]
    channel: str
    created_at: dt.datetime


# --- settings ---


class SettingsUpdate(BaseModel):
    provider: str | None = None
    model_chat: str | None = None
    model_deep: str | None = None


class EmbeddingInfo(BaseModel):
    provider: str
    model: str
    dimensions: int
    pinned: bool
    note: str


class SettingsOut(BaseModel):
    provider: str
    model_chat: str
    model_deep: str
    available_providers: list[str]
    model_catalog: dict[str, list[str]]
    defaults: dict[str, str]
    embedding: EmbeddingInfo
