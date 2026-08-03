## Context

The app is a FastAPI backend (sync SQLAlchemy on Postgres 17 + pgvector, openai SDK
→ Gemini) and a React/Vite SPA. Dev runs via `docker-compose.yml` (`db` + `api`
with `--reload` and a source mount, ports bound to loopback). `Dockerfile` copies
only `backend/app`. Auth is a JWT in an httpOnly cookie set `SameSite=Lax;
Secure=False`. CORS is already limited to `settings.frontend_origin`. There is no
production compose, no TLS, and no CD.

## Goals / Non-Goals

**Goals:** a stable, always-on, HTTPS single-user deployment at ~$0; understood
step-by-step (manual first); then reproducible via CI/CD; with the security gaps
that only matter in production closed.

**Non-Goals:** managed DB, HA/zero-downtime, multi-region, multi-user — all later.

## Decisions

**1. Google Cloud always-free `e2-micro` + Docker + a swap file.**
One `e2-micro` (2 shared vCPU, **1 GB RAM**) in a free US region runs the whole
backend: Postgres/pgvector, the API, and Caddy. 1 GB is tight (~600 MB resident), so
we add a **2 GB swap file** and keep Postgres modest (`shared_buffers≈128MB`). Docker
*runs* fine here; only image *builds* are memory-heavy, so in CI/CD the image is
built on GitHub and the VM only pulls (stage 2); for the manual stage, build-on-box
works thanks to swap. *Alternatives:* DigitalOcean ($200 student credit — expired
Aug 2026); managed Postgres (not free). *Cost note:* the compute is $0 within
always-free limits, but GCP requires a **billing account on the project** (card on
file) even for the free tier — we add a **$1 budget alert**.

**2. Free subdomain (DuckDNS) + Caddy for automatic HTTPS.**
HTTPS is **mandatory**, for two reasons: (a) an HTTPS Vercel page cannot call an
HTTP backend (mixed content is blocked); (b) the auth cookie must be `Secure`.
Narendra has no domain, so a **DuckDNS** subdomain (e.g. `acero.duckdns.org`) points
at the VM's IP, and **Caddy** obtains/renews a Let's Encrypt cert automatically and
reverse-proxies `:443 → api:8000`. Caddy is the only public-facing service (80/443);
the API listens on the internal Docker network, Postgres is never published.
*Alternatives:* `sslip.io` (IP-in-hostname, no signup — fallback if DuckDNS is
flaky); Cloudflare Tunnel (needs a domain on Cloudflare). Easy to swap in a real
domain later — just change the Caddyfile host + `FRONTEND_ORIGIN`/`VITE_API_URL`.

**3. Cross-site auth cookie: `SameSite=None; Secure` in production.**
The frontend (`*.vercel.app`) and backend (`*.duckdns.org`) are different registrable
domains, so the login cookie is **cross-site**; a `SameSite=Lax` cookie is not sent
on those requests. Prod therefore needs `SameSite=None; Secure=True` (which requires
HTTPS — decision 2). These become config (`cookie_samesite`, `cookie_secure`), so
dev stays `Lax`/insecure and only prod flips them. CORS stays locked to the exact
Vercel origin with credentials allowed. *CSRF:* acceptable for a single-user app with
a strict CORS allowlist and a bearer-in-cookie read via same-origin XHR; revisit if
we go multi-user. *Alternative considered:* host frontend on a subdomain of the same
registrable domain as the API (would keep `Lax`) — rejected: Narendra wants Vercel,
and that couples the two hosts.

**4. Persona via a mounted `SOUL_PATH`, not baked into the image.**
The image doesn't contain `docs/`, so `composer._read_persona()` falls back to a
stub in prod. Add an optional `soul_path` setting; when set, the composer reads it.
The prod compose mounts `./docs:/docs:ro` and sets `SOUL_PATH=/docs/SOUL.md`. Keeping
it a mount (not a `COPY`) means editing the persona doesn't require an image rebuild.
*Alternative:* change the Docker build context to the repo root and `COPY docs/` —
rejected: broadens the build context and still needs a rebuild to edit.

**5. Fail-fast on a default secret in production.**
On startup, if `app_env == "prod"` and `jwt_secret` is the known dev default, raise
and refuse to boot. Cheap insurance against the classic "shipped with the sample
secret" incident. Dev is unaffected (default `app_env=dev`).

**6. Migrations as an explicit deploy step.**
A one-shot `migrate` service (or a documented `docker compose run --rm api alembic
upgrade head`) runs before/at deploy. Not auto-run inside the web process, so a bad
migration can't wedge app startup silently.

**7. Manual bring-up first, then CI/CD (Narendra's choice).**
Stage 1 is a hand-run runbook (`docs/DEPLOY.md`) so each piece is understood. Stage 2
adds `deploy.yml`: on push to `main` (after CI passes), build the image → push to
**GHCR** → SSH to the VM → `docker compose pull && up -d` → run migrations. Deploy
secrets (SSH key, host) live in GitHub Actions secrets.

## Risks / Trade-offs

- **1 GB RAM OOM** → swap file + modest Postgres; monitor with a `free -h` check in
  the runbook. If it ever stays tight, the paid e2-small (2 GB) is a one-line change.
- **US region latency to India (~200 ms)** → fine for chat (LLM dominates); paid
  Mumbai VM is the escape hatch.
- **DuckDNS/free-DNS reliability** → `sslip.io` fallback; a real domain later.
- **Secrets on the VM** → `.env` lives only on the server (chmod 600), never in git;
  gitleaks already guards commits.
- **Free-tier egress (1 GB/mo)** → far above a personal backend's usage.
- **Data durability** → Postgres data in a Docker volume on the persistent disk; a
  daily `pg_dump` to disk (and later a bucket) is a documented optional step.

## Migration Plan

Additive and dev-safe: new settings default to dev behavior; new files are prod-only.
Rollback for the code = revert; rollback for the deploy = `docker compose down` and
redeploy the previous image tag. No DB schema change.

## Open Questions

- **Budget alert threshold** — defaulting to $1 (effectively "tell me on any charge").
- **Backups now or later** — recommend a documented `pg_dump` cron in stage 1;
  bucket upload can wait.
