## Why

Everything so far runs only on Narendra's laptop. To use Acero for real — from his
phone, always-on, and with billing making memory/deep-mode practical — it has to be
**hosted**. This is also the prerequisite for every proactive feature (a scheduled
job only fires if the server is running), so it's the right next step.

Plan: **frontend on Vercel** (free, HTTPS), **backend on Google Cloud's always-free
`e2-micro` VM** running Docker (backend + Postgres/pgvector + Caddy), reached over a
**free subdomain (DuckDNS) with automatic HTTPS**. We bring it up **manually first**
(so every piece is understood), then add **GitHub Actions CI/CD**.

## What Changes

**Production hardening (code — the part that must change before going live):**
- `config.py` gains `app_env` (`dev`/`prod`), `cookie_secure`, `cookie_samesite`,
  and `soul_path`.
- **Fail-fast**: on startup in `prod`, the app refuses to run if `JWT_SECRET` is
  still the dev default (prevents shipping an insecure signing key).
- **Cross-site auth cookie**: the Vercel frontend and the backend are different
  sites, so the login cookie must be `SameSite=None; Secure` in prod (today it's
  `Lax; Secure=False`, which a browser won't send cross-site). `auth.py` reads the
  new cookie settings.
- **Persona in prod**: the image copies only `backend/app`, so `docs/SOUL.md` isn't
  present and the composer silently falls back to a one-line persona. Fix: a
  `SOUL_PATH` the prod compose mounts, so the real SOUL.md is used (and editable
  without a rebuild).
- CORS already restricts to `settings.frontend_origin`; prod just sets it to the
  Vercel URL.

**Deployment assets (new files):**
- `docker-compose.prod.yml` — `db` (pgvector, not publicly exposed) + `api`
  (prod command, no reload/source-mount) + `caddy` (public 80/443, auto-TLS) +
  a one-shot `migrate` step (`alembic upgrade head`).
- `Caddyfile` — reverse-proxy the subdomain to the api with automatic Let's Encrypt.
- `docs/DEPLOY.md` — the exact runbook (GCP VM, swap, Docker, DuckDNS, env, bring-up,
  Vercel, then CI/CD).

**CI/CD (stage 2, after manual bring-up works):**
- `.github/workflows/deploy.yml` — build the backend image, push to GHCR, then SSH
  to the VM to pull + restart. Triggered on push to `main` after CI is green.

## Capabilities

### New Capabilities
- `deployment`: the app runs in production over HTTPS with production-safe auth
  cookies, a fail-fast secret check, a restricted CORS origin, its real persona,
  and (stage 2) automated build-and-deploy on push.

### Modified Capabilities
<!-- none behavioral for chat/memory; auth cookie hardening is captured under the
new `deployment` capability -->

## Impact

- **Code:** `config.py` (+4 settings + a prod secret check), `app/main.py` (run the
  check at startup), `api/auth.py` (use cookie settings), `core/composer.py` (honor
  `SOUL_PATH`). Small, additive; dev behavior unchanged by default.
- **New files:** `docker-compose.prod.yml`, `Caddyfile`, `docs/DEPLOY.md`,
  `.github/workflows/deploy.yml` (stage 2).
- **Config:** `.env.example` gains `APP_ENV`, `COOKIE_SECURE`, `COOKIE_SAMESITE`,
  `SOUL_PATH`, and prod notes for `DATABASE_URL` / `FRONTEND_ORIGIN`.
- **Infra (runbook, no cost within limits):** one `e2-micro` in a free US region,
  a 2 GB swap file, Docker, a DuckDNS subdomain. Requires a **billing account on
  the GCP project** (card on file; won't charge within always-free limits — we set
  a $1 budget alert). Separate from Gemini API billing.
- **Secrets:** a real `.env` is created **on the server only** (never committed);
  GH Actions secrets hold the deploy SSH key + host (stage 2).
- **Testing:** unit tests for the fail-fast check and the cookie-settings wiring;
  the compose/Caddy/runbook are validated by the live bring-up.

## Non-goals (this change)

- Managed Postgres, multi-region, autoscaling, zero-downtime deploys.
- Multi-user readiness (still single-user).
- The day-end scheduler (separate later change, once always-on exists).
