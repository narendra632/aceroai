# aceroai

Single-user personal AI assistant — chat, tasks, journal, and cross-session memory.
FastAPI + Postgres/pgvector backend, React SPA, Telegram channel. Private project.

| I want to… | Read |
|---|---|
| Understand how it works | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Know what's built and what's next | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| Run or change the backend | [`backend/README.md`](backend/README.md) |
| Run or change the frontend | [`frontend/README.md`](frontend/README.md) |
| Deploy | [`docs/DEPLOY.md`](docs/DEPLOY.md) · plain-English tour: [`docs/DEPLOYMENT-EXPLAINED.md`](docs/DEPLOYMENT-EXPLAINED.md) |
| Know what a message costs | [`docs/REQUEST-ANATOMY.md`](docs/REQUEST-ANATOMY.md) |
| Read the Insights page | [`docs/INSIGHTS.md`](docs/INSIGHTS.md) |
| Follow the conventions | [`AGENTS.md`](AGENTS.md) |

## Quick start

```bash
docker compose up db -d                        # Postgres + pgvector
cd backend && uv run alembic upgrade head      # build the schema
uv run python -m app.scripts.create_user       # seed the single user
uv run uvicorn app.main:app --reload           # API on :8000
cd ../frontend && npm run dev                  # UI on :5173
```

Configuration is `.env` at the repo root — copy [`.env.example`](.env.example) and
fill it in. Secrets live there and nowhere else.
