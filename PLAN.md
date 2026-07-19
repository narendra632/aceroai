# PLAN.md — Phase 0 Completion Run (executed by the AI coding agent)

> **To the human (Narendra):** put this file at the repo root, open your Claude
> extension, and say: *"Read PLAN.md and execute it task by task. Follow its
> operating rules exactly and stop at every HUMAN CHECKPOINT."* Keep Docker
> Desktop running before you start.

---

## 1. Context for you, the agent

You are completing the Phase 0 scaffold of **aceroai** — a single-user personal
AI assistant (chat + journaling + tasks + scheduled reviews; later: memory,
habits, investments). Web frontend + Telegram bot, one FastAPI backend.

**Read `AGENTS.md` at the repo root first.** It is the source of truth for
stack and conventions. Where this plan and AGENTS.md disagree, this plan wins
for setup only — and Task 0 will bring AGENTS.md up to date.

**Current state:** the human has manually completed:
- Root files: AGENTS.md, CLAUDE.md, README.md, docker-compose.yml, docs/,
  and possibly .gitignore, .env.example, .github/, docs/SOUL.md
- `backend/` initialized with uv (Python 3.12 pinned), dependencies added,
  ruff config appended to pyproject.toml
- A real `.env` exists at the repo root (filled by the human)

**Important change already made:** LiteLLM was **dropped** (its Rust core
fails to build on this Windows machine). We use the **openai SDK** instead,
pointed at Gemini's OpenAI-compatible endpoint via `base_url`. Provider swap
= change `LLM_BASE_URL` + `LLM_API_KEY` + model names in `.env`. Some files
the human created may still reference LiteLLM — Task 0 fixes that.

**Environment:** Windows, Git Bash (MINGW64) terminal, VS Code, Docker
Desktop, Node, uv. POSIX-style commands (`mkdir -p`, `cp`, `ls -la`) work.

---

## 2. Operating rules (non-negotiable)

1. **Never open, print, cat, or modify `.env`.** Never echo secrets or ask
   the human for passwords/keys. You may only touch `.env.example`.
2. **Plan-then-act:** before each task, state in 2–4 lines what you are about
   to do, then do it.
3. **Stop at every `HUMAN CHECKPOINT`** and wait for the human's confirmation.
4. If reality conflicts with this plan (missing file, different content,
   failing command), report exactly what you found, propose a fix, and ask
   before deviating.
5. Run all backend commands from `backend/`, all docker/git commands from the
   repo root, unless stated otherwise.
6. Do not add dependencies beyond those listed here. Do not refactor beyond
   the scope of each task. Do not "improve" file contents given below — use
   them verbatim.
7. Before every commit, run `git status` and confirm `.env` is NOT staged.
8. If a command fails, show the error verbatim and your proposed fix; get
   approval before destructive actions (deleting files, dropping DB volumes).

---

## 3. Task 0 — Audit and repair current state

Do a read-only inventory first, then apply fixes. Report findings as a short
checklist (found / fixed / missing) before moving to Task 1.

**0.1 Inventory.** Verify these exist (create any that are missing using the
contents from this plan's Appendix A):
- `.gitignore` (root) — must ignore `.env`, `.venv/`, `__pycache__/`,
  `node_modules/`, `dist/`, caches. Full expected content: Appendix A1.
- `.env.example` (root) — Appendix A2 (this is the post-LiteLLM version).
- `.github/copilot-instructions.md` — Appendix A3.
- `docs/SOUL.md` — Appendix A4.
- `docker-compose.yml` — key points to verify: image `pgvector/pgvector:pg17`,
  ports bound to `127.0.0.1` only, healthcheck present, api service overrides
  `DATABASE_URL` with host `db`. Full expected content: Appendix A5.

**0.2 Secret safety.** Run `git status` and `git log --oneline -5`. Confirm
`.env` is untracked and has never been committed. If it was ever committed,
STOP and tell the human (the secrets in it must be rotated and history
cleaned before pushing anywhere).

**0.3 Dependency check.** Read `backend/pyproject.toml`. Required:
`fastapi, uvicorn[standard], sqlalchemy, alembic, psycopg[binary],
pydantic-settings, openai, pyjwt, bcrypt, httpx, sse-starlette, apscheduler`
plus dev: `ruff, mypy, pytest, pre-commit`, plus the `[tool.ruff]` block
(line-length 100, target py312, select E,F,I,UP,B — add if missing).
- If `litellm` is present: `uv remove litellm`
- If `openai` is missing: `uv add openai`

**0.4 De-LiteLLM the docs.** In `AGENTS.md`:
- In the Stack section, replace any mention of LiteLLM with:
  `openai SDK via base_url swap (Gemini default, OpenAI-ready)`
- In the Layout section, `llm.py` should be described as
  `(OpenAI-SDK wrapper)` not `(LiteLLM wrapper)`.
Also check `CLAUDE.md` and `README.md` for LiteLLM mentions; fix the same way.
If `docs/PHASE0_SETUP.md` exists, do NOT edit it — it is a historical
reference; this plan supersedes its LLM-related sections.

**0.5 Cleanup.** Delete the sample `backend/main.py` (or `hello.py`) that
`uv init` created, if present. The app lives in `backend/app/`.

**Commit:** `phase0: audit fixes (openai swap, missing root files)`

---

## 4. Task 1 — Backend package tree

Create these directories and empty `__init__.py` files:

```
backend/app/__init__.py
backend/app/db/__init__.py
backend/app/core/__init__.py
backend/app/api/__init__.py
backend/app/channels/__init__.py
backend/app/jobs/__init__.py
backend/app/scripts/__init__.py
backend/tests/__init__.py
```

No commit yet — Task 2 fills them.

---

## 5. Task 2 — Core backend files

Create each file below with EXACTLY the content in Appendix B (verbatim, no
improvements):

| File | Appendix |
|---|---|
| `backend/app/config.py` | B1 (post-LiteLLM canonical version) |
| `backend/app/db/session.py` | B2 |
| `backend/app/db/models.py` | B3 |
| `backend/app/core/security.py` | B4 |
| `backend/app/main.py` | B5 |
| `backend/app/scripts/create_user.py` | B6 |
| `backend/app/scripts/verify_llm.py` | B7 |
| `backend/tests/test_health.py` | B8 |
| `backend/Dockerfile` | B9 |

Verify: from `backend/` run
`uv run python -c "from app.main import app; print('imports ok')"` — must
print `imports ok`. Then `uv run ruff check .` and `uv run ruff format .`.

**Commit:** `phase0: backend core (config, models, security, health)`

---

## 6. Task 3 — Database + migration 001 + seed user

> **HUMAN CHECKPOINT:** confirm Docker Desktop is running before this task.

**3.1** From repo root: `docker compose up db -d`, then `docker compose ps`
until `db` is healthy. If port 5432 is busy, report it and propose switching
the compose mapping to `127.0.0.1:5433:5432` (requires the human to also
update `DATABASE_URL` in their `.env` — tell them, don't touch `.env`).

**3.2** From `backend/`: `uv run alembic init alembic`

**3.3** Edit `backend/alembic/env.py`: directly below the line
`config = context.config`, insert:

```python
from app.config import settings
from app.db.session import Base
from app.db import models  # noqa: F401  (imports register the tables)

config.set_main_option("sqlalchemy.url", settings.database_url)
```

and change `target_metadata = None` to `target_metadata = Base.metadata`.

**3.4** From `backend/`:
`uv run alembic revision --autogenerate -m "001 core tables"`
Open the generated file in `backend/alembic/versions/`. Sanity-check it
creates exactly these tables: users, chat_sessions, messages, tasks,
journal_entries, profile_facts, generated_reviews. Then insert as the FIRST
line inside `def upgrade():`:

```python
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
```

**3.5** `uv run alembic upgrade head`

**3.6** Verify from repo root:
`docker compose exec db psql -U agent -d agent -c "\dt"` — expect the 7
tables + alembic_version.

> **HUMAN CHECKPOINT — seed user:** tell the human to run, from `backend/`:
> `uv run python -m app.scripts.create_user`
> They type their email and password themselves (you never see or handle the
> password). Then verify with:
> `docker compose exec db psql -U agent -d agent -c "select email from users;"`

**Commit:** `phase0: migration 001 applied, user seeded`
(Note: `alembic/` and its versions ARE committed; that's the point.)

---

## 7. Task 4 — API up + LLM connectivity proof

**4.1** From `backend/`: `uv run pytest` — 1 test must pass.

**4.2** Tell the human to start the API in a dedicated terminal:
`uv run uvicorn app.main:app --reload` (from `backend/`) and keep it running.
Then verify yourself: `curl -s http://localhost:8000/health` → `{"status":"ok"}`.

**4.3** LLM check (no secrets printed): from `backend/` run
`uv run python -m app.scripts.verify_llm`
- Prints a short model reply → provider wiring works end-to-end.
- Prints the "LLM_API_KEY is empty" message → tell the human to fill
  `LLM_API_KEY` in `.env` with their **rotated** Gemini key, then rerun.
- Errors (404 model not found / 401) → report verbatim; likely fixes: bump
  `MODEL_CHAT` in `.env` to a current Flash model id, or key invalid.

---

## 8. Task 5 — Frontend scaffold

**5.1** From repo root:
```
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install tailwindcss @tailwindcss/vite
```
(If `npm create` prompts, accept defaults / confirm the `frontend` name.)

**5.2** Replace/create with Appendix C contents:
- `frontend/vite.config.ts` — C1
- `frontend/src/index.css` — C2 (single line)
- `frontend/.env.development` — C3
- `frontend/src/App.tsx` — C4
Also: remove any `import './App.css'` line and delete `src/App.css`.

**5.3** `npm run dev`

> **HUMAN CHECKPOINT — the green dot:** human opens http://localhost:5173
> and confirms the page shows "API: ok" with a green dot (API from Task 4
> must still be running). This proves browser → Vite → FastAPI → back.

**Commit:** `phase0: frontend scaffold with health check`

---

## 9. Task 6 — AI workflow layer

**6.1** Create `.pre-commit-config.yaml` at repo root — Appendix D1. Then:
- from `backend/`: `uv run pre-commit autoupdate --config ../.pre-commit-config.yaml`
- from repo root: `backend/.venv/Scripts/pre-commit install`
  (Git Bash on Windows; fall back to `uv run pre-commit install` executed
  from `backend/` with `--config ../.pre-commit-config.yaml` if pathing
  fails — in that case also note the hook path in your report.)

**6.2** Create `.github/workflows/ci.yml` — Appendix D2.

**6.3** Create `.vscode/settings.json` and `.vscode/extensions.json` —
Appendix D3.

**6.4** OpenSpec, from repo root:
```
npm install -g @fission-ai/openspec@latest
openspec init
```

> **HUMAN CHECKPOINT:** `openspec init` is interactive — the human selects
> **Claude Code** and **GitHub Copilot** when prompted. Afterward verify
> `openspec list` runs and the `openspec/` folder exists.

**Commit:** `phase0: workflow layer (pre-commit, ci, openspec, vscode)`

---

## 10. Task 7 — Push to GitHub

> **HUMAN CHECKPOINT:** human creates a **private** repo on github.com
> (no README/gitignore) and gives you the remote URL.

Then from repo root:
```
git branch -M main
git remote add origin <URL>
git push -u origin main
```
Ask the human to confirm the Actions tab shows CI green. Optionally verify
the prod image builds: `docker compose build api`.

---

## 11. Task 8 — Document, update memory, and teach

This task is as important as the code.

**8.1** Write `docs/ARCHITECTURE.md` describing the system AS IT ACTUALLY
EXISTS in this repo (read the files; do not invent). Required sections:
1. **Overview** — what aceroai is, single-user, phase roadmap in 5 lines.
2. **System diagram** — ASCII: browser SPA and (future) Telegram → FastAPI
   routes → core/handler (the one brain) → core/composer → core/llm →
   Gemini via OpenAI-compatible endpoint; SQLAlchemy → Postgres+pgvector;
   jobs/scheduler for time-driven runs. Mark not-yet-built parts as
   `(planned — Feature N)`.
3. **Directory guide** — every file that exists, one line each on its role.
4. **Lifecycle walkthroughs** — (a) what will happen when a chat message
   arrives (Feature 1 path through the layers), (b) what will happen at
   9:45pm for the day-end summary (Feature 3). Clearly labeled as the
   design contract for upcoming features.
5. **Data model rationale** — the 7 tables; why timestamptz everywhere, why
   urgency is computed not stored, why Text+CHECK over enums, how
   profile_facts supersession works, why the vector column waits for the
   embedding-model choice in Phase 2.
6. **Config & secrets** — how `.env` → pydantic-settings works; the provider
   swap recipe (base_url + key + model names); rule: secrets never leave
   `.env`.
7. **Development workflow** — the OpenSpec cycle, the commands table, the
   golden rules recap.
8. **Status & next** — Phase 0 complete; Features 1–3 queued as listed in
   AGENTS.md.

**8.2** Update `AGENTS.md` "Current status" to: Phase 0 complete (date),
next = Feature 1 (LLM wrapper + handler + auth + SSE chat), Feature 2
(Telegram channel), Feature 3 (day-end summary job). Add one line:
`Architecture reference: docs/ARCHITECTURE.md`.

**8.3** Move this `PLAN.md` to `docs/plans/phase0-completion.md` (archive —
it is done).

**Commit:** `docs: architecture reference; phase 0 complete`  → push.

**8.4 Teach.** In chat, give the human a guided tour: walk through
ARCHITECTURE.md top to bottom in your own words, then ask them 3 short
comprehension questions (e.g., "a chat message arrives from Telegram — which
file decides what context the model sees?"). Correct gently. Finally, print
the Feature 1 kickoff prompt for them:

```
/opsx:propose Build Feature 1 per AGENTS.md: core/llm.py (thin AsyncOpenAI
wrapper using settings.llm_base_url/llm_api_key with a stream_chat function
on settings.model_chat), core/handler.py with handle_message(user, text,
channel, session_id) persisting user+assistant messages to
chat_sessions/messages, POST /api/auth/login (JWT httpOnly cookie via
core/security.py), and an auth-protected POST /api/chat streaming the reply
over SSE via sse-starlette. Channels stay thin per golden rule 1.
```

---

## 12. Definition of done

- [ ] Audit findings reported; LiteLLM references gone; openai SDK in deps
- [ ] 7 tables + vector extension in Postgres; user row seeded
- [ ] pytest green; /health ok; verify_llm prints a model reply
- [ ] Frontend green dot confirmed by human
- [ ] pre-commit + gitleaks firing; CI green on GitHub; openspec initialized
- [ ] docs/ARCHITECTURE.md written from the real repo; AGENTS.md updated
- [ ] PLAN.md archived to docs/plans/
- [ ] Human toured, quizzed, and holding the Feature 1 prompt

---
---

# Appendix A — Root files (expected content)

## A1 `.gitignore`
```
# python
__pycache__/
*.pyc
.venv/
.pytest_cache/
.ruff_cache/
.mypy_cache/

# node
node_modules/
dist/

# env & secrets
.env
*.env.local

# misc
.DS_Store
```

## A2 `.env.example`
```
# --- database ---
# avoid % and @ characters in the password (they break URL parsing)
POSTGRES_PASSWORD=change-me-strong
DATABASE_URL=postgresql+psycopg://agent:change-me-strong@localhost:5432/agent

# --- auth ---
JWT_SECRET=generate: python -c "import secrets; print(secrets.token_hex(32))"

# --- llm ---
# provider swap = change base_url + api_key + models. examples:
#   gemini: https://generativelanguage.googleapis.com/v1beta/openai/
#   openai: https://api.openai.com/v1
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=
MODEL_CHAT=gemini-2.5-flash
MODEL_HEAVY=gemini-2.5-pro

# --- app ---
APP_TIMEZONE=Asia/Kolkata
FRONTEND_ORIGIN=http://localhost:5173

# --- telegram (filled in Feature 2) ---
TELEGRAM_BOT_TOKEN=
```

## A3 `.github/copilot-instructions.md`
```markdown
This repo's conventions live in AGENTS.md at the root — read and follow it.
Key rules: uv not pip; sync SQLAlchemy 2.0 typed style; all chat logic goes
through backend/app/core/handler.py; timestamptz everywhere; no secrets in
code.
```

## A4 `docs/SOUL.md`
```markdown
# SOUL.md — persona

Name: (pick one!)
Role: Narendra's personal chief-of-staff — journal keeper, task tracker,
time-aware reviewer.
Voice: concise, direct, warm. Pushes back when I drift from my own stated
goals. No corporate filler.
Prime directives:
- Reduce my attention cost; surface time-sensitive things early.
- Never invent facts about me — ground claims in journal entries, tasks,
  or confirmed profile facts.
- When unsure, ask one sharp question instead of assuming.

(Read by core/composer.py at the start of every context build.)
```

## A5 `docker-compose.yml`
```yaml
services:
  db:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: agent
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: agent
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:5432:5432"   # loopback only — never expose publicly
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agent -d agent"]
      interval: 5s
      retries: 10

  api:
    build: ./backend
    env_file: .env
    environment:
      # inside the container, the DB host is the service name "db"
      DATABASE_URL: postgresql+psycopg://agent:${POSTGRES_PASSWORD}@db:5432/agent
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - ./backend/app:/app/app   # mount source only, not .venv
    command: ["uv", "run", "--no-sync", "uvicorn", "app.main:app",
              "--host", "0.0.0.0", "--port", "8000", "--reload"]

volumes:
  pgdata:
```

---

# Appendix B — Backend files (verbatim)

## B1 `backend/app/config.py`
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ".env" resolves when running from repo root / docker;
    # "../.env" resolves when running natively from backend/
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://agent:agent@localhost:5432/agent"
    jwt_secret: str = "dev-not-secret-override-in-env"

    # provider swap = change base_url + api_key + models in .env. no code changes.
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    model_chat: str = "gemini-2.5-flash"
    model_heavy: str = "gemini-2.5-pro"

    app_timezone: str = "Asia/Kolkata"
    frontend_origin: str = "http://localhost:5173"
    telegram_bot_token: str = ""


settings = Settings()
```

## B2 `backend/app/db/session.py`
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

## B3 `backend/app/db/models.py`
```python
import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

now = sa.func.now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(sa.Text, unique=True)
    password_hash: Mapped[str] = mapped_column(sa.Text)
    telegram_chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, unique=True)
    timezone: Mapped[str] = mapped_column(sa.Text, default="Asia/Kolkata")
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        sa.CheckConstraint("channel in ('web','telegram')", name="chat_sessions_channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(sa.Text)
    title: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )
    last_active_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        sa.CheckConstraint("role in ('user','assistant','system','tool')", name="messages_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("chat_sessions.id"))
    role: Mapped[str] = mapped_column(sa.Text)
    content: Mapped[str] = mapped_column(sa.Text)
    model: Mapped[str | None] = mapped_column(sa.Text)
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        sa.CheckConstraint(
            "status in ('todo','in_progress','done','dropped')", name="tasks_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(sa.Text)
    notes: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text, default="todo")
    priority: Mapped[int] = mapped_column(sa.SmallInteger, default=2)  # 1 hi / 2 mid / 3 lo
    due_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    snoozed_until: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now, onupdate=now
    )
    # NOTE: urgency is derived from due_at + priority at read time. Never store it.


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    entry_date: Mapped[dt.date] = mapped_column(sa.Date)
    content: Mapped[str] = mapped_column(sa.Text)
    mood: Mapped[int | None] = mapped_column(sa.SmallInteger)  # optional 1-5
    tags: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), default=list)
    channel: Mapped[str] = mapped_column(sa.Text, default="web")
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )
    # Phase 2 migration adds: embedding vector(N) + HNSW index


class ProfileFact(Base):
    __tablename__ = "profile_facts"
    __table_args__ = (
        sa.CheckConstraint(
            "category in ('preference','health','work','finance','relationship','other')",
            name="profile_facts_category",
        ),
        sa.CheckConstraint("source in ('stated','inferred')", name="profile_facts_source"),
        sa.CheckConstraint(
            "status in ('active','superseded','rejected')", name="profile_facts_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    fact: Mapped[str] = mapped_column(sa.Text)
    category: Mapped[str] = mapped_column(sa.Text)
    confidence: Mapped[float] = mapped_column(sa.Float, default=0.8)
    source: Mapped[str] = mapped_column(sa.Text)
    source_ref: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    status: Mapped[str] = mapped_column(sa.Text, default="active")
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(sa.ForeignKey("profile_facts.id"))
    valid_from: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )


class GeneratedReview(Base):
    __tablename__ = "generated_reviews"
    __table_args__ = (
        sa.CheckConstraint("kind in ('morning','daily','weekly')", name="generated_reviews_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(sa.Text)
    period_start: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    period_end: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True))
    content: Mapped[str] = mapped_column(sa.Text)
    delivered_to: Mapped[list[str]] = mapped_column(ARRAY(sa.Text), default=list)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=now
    )
```

## B4 `backend/app/core/security.py`
```python
import datetime as dt

import bcrypt
import jwt

from app.config import settings

JWT_ALGO = "HS256"
TOKEN_TTL_DAYS = 30


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": dt.datetime.now(dt.UTC) + dt.timedelta(days=TOKEN_TTL_DAYS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGO)


def decode_access_token(token: str) -> str:
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGO])["sub"]
```

## B5 `backend/app/main.py`
```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

## B6 `backend/app/scripts/create_user.py`
```python
"""Run from backend/:  uv run python -m app.scripts.create_user"""

from getpass import getpass

from app.core.security import hash_password
from app.db.models import User
from app.db.session import SessionLocal


def main() -> None:
    email = input("email: ").strip()
    password = getpass("password: ")
    with SessionLocal() as db:
        db.add(User(email=email, password_hash=hash_password(password)))
        db.commit()
    print(f"created user {email}")


if __name__ == "__main__":
    main()
```

## B7 `backend/app/scripts/verify_llm.py`
```python
"""Run from backend/:  uv run python -m app.scripts.verify_llm

Proves the provider wiring (base_url + key + model) works end to end.
Prints only the model's reply — never the key.
"""

from openai import OpenAI

from app.config import settings


def main() -> None:
    if not settings.llm_api_key:
        print("LLM_API_KEY is empty in .env — fill it first.")
        return
    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    resp = client.chat.completions.create(
        model=settings.model_chat,
        messages=[{"role": "user", "content": "Reply with exactly: scaffold llm ok"}],
        max_tokens=10,
    )
    print(resp.choices[0].message.content)


if __name__ == "__main__":
    main()
```

## B8 `backend/tests/test_health.py`
```python
from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

## B9 `backend/Dockerfile`
```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

# Appendix C — Frontend files (verbatim)

## C1 `frontend/vite.config.ts`
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
});
```

## C2 `frontend/src/index.css` (entire file)
```css
@import "tailwindcss";
```

## C3 `frontend/.env.development`
```
VITE_API_URL=http://localhost:8000
```

## C4 `frontend/src/App.tsx`
```tsx
import { useEffect, useState } from "react";

const API = import.meta.env.VITE_API_URL;

export default function App() {
  const [status, setStatus] = useState<"checking" | "ok" | "down">("checking");

  useEffect(() => {
    fetch(`${API}/health`)
      .then((r) => r.json())
      .then((d) => setStatus(d.status === "ok" ? "ok" : "down"))
      .catch(() => setStatus("down"));
  }, []);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col items-center justify-center gap-4">
      <h1 className="text-3xl font-semibold tracking-tight">aceroai</h1>
      <p className="flex items-center gap-2 text-sm text-zinc-400">
        <span
          className={`h-2.5 w-2.5 rounded-full ${
            status === "ok"
              ? "bg-emerald-400"
              : status === "down"
                ? "bg-red-500"
                : "bg-amber-400"
          }`}
        />
        API: {status}
      </p>
      <p className="text-xs text-zinc-500">Scaffold only — real UI lands with the chat feature.</p>
    </main>
  );
}
```

---

# Appendix D — Workflow files (verbatim)

## D1 `.pre-commit-config.yaml`
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.9.6
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.24.0
    hooks:
      - id: gitleaks
```
(`autoupdate` in Task 6 pins these to current versions.)

## D2 `.github/workflows/ci.yml`
```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run pytest
```

## D3 VS Code files

`.vscode/settings.json`
```json
{
  "python.defaultInterpreterPath": "backend/.venv",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  }
}
```

`.vscode/extensions.json`
```json
{
  "recommendations": ["charliermarsh.ruff", "ms-python.python"]
}
```