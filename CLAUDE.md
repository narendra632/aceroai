Read AGENTS.md first — it is the source of truth for stack and conventions.

Workflow: plan-then-act. For any multi-file change use OpenSpec:
/opsx:propose → I review → /opsx:apply → /opsx:archive.

After edits, from backend/: `uv run ruff format .` and `uv run pytest`.
Never touch .env. Ask before adding new dependencies.