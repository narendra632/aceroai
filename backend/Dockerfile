# ⚠ The Debian release is pinned deliberately, not inherited.
#
# `pg_dump` refuses to dump a server NEWER than itself, and which version `postgresql-client`
# resolves to is decided entirely by the base image's Debian release. The database is
# Postgres 17 (pgvector/pgvector:pg17); Debian 13 "trixie" ships client 17.11, and Debian 12
# would have shipped 15 — which cannot dump this server at all.
#
# Left as a floating `python:3.12-slim`, a future rebuild could land on a Debian whose
# `postgresql-client-17` package no longer exists, and the first symptom would be backups
# failing months of nights later. Pinning the release makes that a build failure instead.
FROM python:3.12-slim-trixie

# postgresql-client-17 is here for `db_backup` and `restore_check` (see docs/JOBS.md), not
# for the application, which talks to Postgres through psycopg. ~20 MB.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
