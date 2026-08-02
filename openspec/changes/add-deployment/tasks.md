## 1. Production hardening (code)

- [ ] 1.1 `config.py`: add `app_env: str = "dev"`, `cookie_secure: bool = False`, `cookie_samesite: str = "lax"`, `soul_path: str = ""`
- [ ] 1.2 `app/main.py`: at startup, if `app_env == "prod"` and `jwt_secret` is the dev default, raise a clear error (refuse to boot)
- [ ] 1.3 `api/auth.py`: set the login cookie with `secure=settings.cookie_secure`, `samesite=settings.cookie_samesite`
- [ ] 1.4 `core/composer.py`: if `settings.soul_path` is set, read the persona from there (fall back to the computed path, then the stub)
- [ ] 1.5 `.env.example`: add `APP_ENV`, `COOKIE_SECURE`, `COOKIE_SAMESITE`, `SOUL_PATH`, and prod notes for `DATABASE_URL` (host `db`) and `FRONTEND_ORIGIN` (the Vercel URL)

## 2. Deployment assets (code/files)

- [ ] 2.1 `docker-compose.prod.yml`: `db` (pgvector, **no** published port), `api` (prod command, no `--reload`/source mount, loopback only), `caddy` (publish 80/443), a one-shot `migrate` (`alembic upgrade head`); mount `./docs:/docs:ro` and set `SOUL_PATH`
- [ ] 2.2 `Caddyfile`: reverse-proxy `<subdomain> → api:8000` with automatic HTTPS
- [ ] 2.3 Confirm the `db` volume persists data and is not publicly exposed

## 3. Tests

- [ ] 3.1 Startup fail-fast: `app_env=prod` + default secret → raises; `dev` or a real secret → boots
- [ ] 3.2 Cookie honors `cookie_secure`/`cookie_samesite` settings (login response sets the expected attributes)
- [ ] 3.3 `composer` reads `SOUL_PATH` when set; `ruff` + `pytest` green

## 4. Stage 1 — manual bring-up (runbook in `docs/DEPLOY.md`)

- [ ] 4.1 **GCP**: create account/project; **enable billing** (card) and set a **$1 budget alert**
- [ ] 4.2 Create an **`e2-micro`** VM: free US region (e.g. `us-central1`), Ubuntu LTS, allow HTTP/HTTPS; note the external IP
- [ ] 4.3 SSH in; add a **2 GB swap file** (`fallocate`/`swapon`, persist in `/etc/fstab`); verify with `free -h`
- [ ] 4.4 Install **Docker Engine + compose plugin**; add the user to the `docker` group
- [ ] 4.5 **DuckDNS**: create a subdomain, point it at the VM IP (and note the update token)
- [ ] 4.6 Clone the repo; create **`.env` on the server only** (`APP_ENV=prod`, strong `JWT_SECRET`, `LLM_API_KEY`, `TELEGRAM_BOT_TOKEN`, `COOKIE_SECURE=true`, `COOKIE_SAMESITE=none`, `FRONTEND_ORIGIN=<vercel-url>`, `SOUL_PATH=/docs/SOUL.md`); `chmod 600 .env`
- [ ] 4.7 Set the Caddyfile host to the DuckDNS subdomain; `docker compose -f docker-compose.prod.yml up -d`
- [ ] 4.8 Run migrations (`... run --rm migrate` or `... run --rm api alembic upgrade head`); seed the user (`create_user`)
- [ ] 4.9 Verify: `https://<subdomain>/health` is green over TLS; `free -h` has headroom
- [ ] 4.10 **Vercel**: import the repo, set `VITE_API_URL=https://<subdomain>`, deploy; log in from the browser and from your phone
- [ ] 4.11 (Optional) document a daily `pg_dump` backup to disk

## 5. Stage 2 — CI/CD (after Stage 1 works)

- [ ] 5.1 `.github/workflows/deploy.yml`: on push to `main` (needs CI green) → build the backend image → push to **GHCR**
- [ ] 5.2 Deploy step: SSH to the VM (key + host in **GitHub Actions secrets**) → `docker compose -f docker-compose.prod.yml pull && up -d` → run migrations
- [ ] 5.3 `docker-compose.prod.yml`: switch `api` from `build:` to the GHCR `image:` tag
- [ ] 5.4 Trigger a deploy; confirm the change lands automatically and the app stays up

## 6. Docs

- [ ] 6.1 `docs/DEPLOY.md`: the full runbook (stages 1 & 2), with the swap/RAM notes and the $ budget-alert step
- [ ] 6.2 `backend/README.md` + `frontend/README.md`: short "Deploying" pointers to DEPLOY.md and the env vars
- [ ] 6.3 Update `docs/ROADMAP.md` (hosting done) and `AGENTS.md`/`ARCHITECTURE.md` status
