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


class SessionPatch(BaseModel):
    title: str


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


# --- memory / knowledge graph ---


class FactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    fact: str
    category: str
    # Reads ProfileFact.effective_confidence, not the stored column: a confirmed fact is
    # certain by definition, while the column keeps the model's original estimate so
    # un-confirming can restore it.
    confidence: float = Field(validation_alias="effective_confidence")
    source: str  # "inferred" (the assistant concluded it) | "stated" (the user confirmed it)
    status: str  # "active" | "superseded" | "rejected"
    superseded_by: uuid.UUID | None
    valid_from: dt.datetime
    created_at: dt.datetime
    updated_at: dt.datetime


class FactDetailOut(FactOut):
    """Everything the detail panel needs, resolved server-side.

    `source_session_id` turns `source_ref` (a message id) into something the UI can link to,
    and `previous` makes a superseded fact's history reachable rather than merely stored.
    """

    source_session_id: uuid.UUID | None = None
    previous: FactOut | None = None


class FactPatch(BaseModel):
    # Changing `fact` supersedes the row (and needs a fresh embedding); changing only the
    # metadata updates it in place. See services/memory.update_fact.
    fact: str | None = None
    category: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class GraphNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fact: str
    category: str
    confidence: float
    source: str
    valid_from: dt.datetime


class GraphEdge(BaseModel):
    source: uuid.UUID
    target: uuid.UUID
    distance: float  # cosine distance: 0 = identical meaning, 1 = unrelated


class GraphOut(BaseModel):
    """Deliberately carries no embeddings — the 768-dimensional vectors never leave the
    server. The client receives only what it needs to draw."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    # True when more facts exist than the graph will draw. Silently showing a subset of
    # someone's memory as if it were all of it is the kind of quiet lie that erodes trust
    # in the whole view.
    truncated: bool = False
    total: int = 0
    # The rendering ceiling, sent so the interface can name the actual number rather than
    # hard-coding a copy of it that drifts.
    render_limit: int = 0
    # True once the memory approaches or passes that ceiling. Surfaced in the UI on
    # purpose: the moment to switch the layout to a Barnes-Hut quadtree should announce
    # itself where it will be seen, not sit in a document nobody re-reads.
    needs_faster_layout: bool = False


class MemoryStatsOut(BaseModel):
    total: int
    by_category: dict[str, int]
    by_source: dict[str, int]
    by_status: dict[str, int]
    per_day: list[dict]
