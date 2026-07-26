import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class LoginIn(BaseModel):
    email: str
    password: str


class MessageIn(BaseModel):
    message: str
    session_id: uuid.UUID | None = None


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
