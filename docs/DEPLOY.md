# DEPLOY.md — hosting aceroai

Frontend on **Vercel**, backend on a **Google Cloud always-free `e2-micro`** VM
running Docker (backend + Postgres/pgvector + Caddy), reached over a **free
DuckDNS subdomain with automatic HTTPS**.

```
[ phone / browser ]
       │ HTTPS
       ▼
[ Vercel: frontend ] ──VITE_API_URL──►  https://<you>.duckdns.org
                                              │
                          ┌─── e2-micro VM (Docker) ───┐
                          │  caddy :80/:443 (auto-TLS)  │
                          │    └─► api:8000 (FastAPI)    │
                          │          └─► db (pgvector)   │
                          │  + 2 GB swap                 │
                          └──────────────────────────────┘
```

Two stages: **Stage 1** brings it up by hand (understand each piece); **Stage 2**
adds GitHub Actions so a push to `main` deploys automatically.

> **Cost:** the compute is $0 within always-free limits, but Google requires a
> billing account (card) on the project. If you also enable Gemini pay-as-you-go
> (Tier 1) on the **same** project, that adds a few cents/month — so set a
> **~$5 budget alert** (a $1 alert would fire on normal Gemini usage).

---

## Stage 0 — accounts & billing (once)

1. **Google Cloud**: sign in at <https://console.cloud.google.com>, create a
   project (e.g. `aceroai`).
2. **Enable billing**: Billing → link a billing account (add a card).
3. **Budget alert**: Billing → Budgets & alerts → Create budget → amount **~$5** →
   alert at 50/90/100%. (The VM stays $0; the ~$5 covers small Gemini pay-as-you-go
   usage if you enable Tier 1 on this same project.)
4. **DuckDNS**: sign in at <https://www.duckdns.org> (Google/GitHub login), create a
   subdomain e.g. `acero` → you get `acero.duckdns.org`. Note your **token**.

---

## Stage 1 — manual bring-up

### 1.1 Create the VM

Console → **Compute Engine → VM instances → Create instance**:
- **Region**: `us-central1` (or `us-west1`/`us-east1` — only these are free).
- **Machine type**: `e2-micro` (this is the always-free one).
- **Boot disk**: Ubuntu 24.04 LTS, 30 GB **standard** (not SSD — free tier is standard).
- **Firewall**: check **Allow HTTP** and **Allow HTTPS**.
- Create. Note the **External IP**.

**Reserve a static IP** (so it survives reboots — free while attached): VPC network
→ IP addresses → reserve the instance's external IP as static.

### 1.2 First login + swap + Docker

SSH in (the "SSH" button on the VM row opens a browser terminal). Then:

```bash
# 2 GB swap so the 1 GB RAM never OOMs
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h            # confirm 2.0Gi swap

# Docker Engine + compose plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker      # apply the group now (or log out/in)
docker --version
```

### 1.3 Point DuckDNS at the VM

On <https://www.duckdns.org>, set your subdomain's IP to the VM's static IP (or run
their update command once). Verify from the VM:

```bash
dig +short acero.duckdns.org     # should print your VM IP
```

### 1.4 Get the code onto the VM

The repo is private, so add a **read-only deploy key**:

```bash
ssh-keygen -t ed25519 -C "aceroai-vm" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```
Copy that public key → GitHub repo → **Settings → Deploy keys → Add** (read-only).
Then:

```bash
git clone git@github.com:narendra632/aceroai.git
cd aceroai
```

### 1.5 Create the server `.env` (never committed)

```bash
cp .env.example .env
nano .env
```
Set at least:
```
POSTGRES_PASSWORD=<a strong password, no @ or %>
DATABASE_URL=postgresql+psycopg://agent:<same password>@db:5432/agent
JWT_SECRET=<paste: openssl rand -hex 32>
LLM_API_KEY=<your Gemini key>
MODEL_CHAT=gemini-3.5-flash
MODEL_HEAVY=gemini-3.1-pro-preview
TELEGRAM_BOT_TOKEN=<your bot token, optional>

APP_ENV=prod
COOKIE_SECURE=true
COOKIE_SAMESITE=none
SOUL_PATH=/docs/SOUL.md
SITE_ADDRESS=acero.duckdns.org
FRONTEND_ORIGIN=https://<your-vercel-url>   # fill after Vercel (step 1.8), then restart
```
Lock it down: `chmod 600 .env`.
(`openssl rand -hex 32` prints a secret; APP_ENV=prod means the app refuses to boot
if you leave JWT_SECRET as the sample.)

### 1.6 Bring up the stack

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps          # db, api up; migrate exited 0
docker compose -f docker-compose.prod.yml logs -f caddy   # watch it get a certificate
```
Migrations run automatically (the `migrate` service) before `api` starts.

### 1.7 Seed your user + verify HTTPS

```bash
docker compose -f docker-compose.prod.yml run --rm api uv run python -m app.scripts.create_user
curl https://acero.duckdns.org/health        # {"status":"ok"} over TLS
free -h                                       # confirm memory headroom
```

### 1.8 Deploy the frontend on Vercel

1. <https://vercel.com> → **Add New → Project** → import the repo.
2. **Root Directory**: `frontend`. **Framework**: Vite (auto-detected).
3. **Environment variable**: `VITE_API_URL = https://acero.duckdns.org`.
4. Deploy → note the `https://<project>.vercel.app` URL.
5. **Back on the VM**: set `FRONTEND_ORIGIN=https://<project>.vercel.app` in `.env`,
   then `docker compose -f docker-compose.prod.yml up -d` to restart the api.
6. Open the Vercel URL, log in, and try it from your phone. If Telegram is
   configured, the bot works too (its poller runs in the api container).

**Done** — you're live. 🎉

---

## Stage 2 — CI/CD (after Stage 1 works)

Goal: push to `main` → GitHub builds the image → the VM pulls & restarts.

1. **Switch to prebuilt images**: in `docker-compose.prod.yml`, change `api` and
   `migrate` from `build: ./backend` to
   `image: ghcr.io/narendra632/aceroai-backend:latest`.
2. **GitHub secrets** (repo → Settings → Secrets → Actions): `DEPLOY_HOST` (VM IP),
   `DEPLOY_USER`, `DEPLOY_SSH_KEY` (a private key whose public half is in the VM's
   `~/.ssh/authorized_keys`).
3. Add `.github/workflows/deploy.yml` **in Stage 2** (once the VM + secrets exist,
   so it doesn't fail on every push before then): it builds + pushes the image to
   GHCR, then SSHes to the VM and runs
   `docker compose -f docker-compose.prod.yml pull && up -d`.
4. On the VM once: `docker login ghcr.io` (a GitHub PAT with `read:packages`) so it
   can pull the private image.

---

## Operations

- **Logs**: `docker compose -f docker-compose.prod.yml logs -f api`
- **Restart**: `... up -d` (after editing `.env`) · **Stop**: `... down`
- **Update (manual)**: `git pull && docker compose -f docker-compose.prod.yml up -d --build`
- **DB backup** (optional cron): `docker compose -f docker-compose.prod.yml exec -T db pg_dump -U agent agent > ~/backup-$(date +%F).sql`
- **Budget**: you should stay at $0; the $1 alert warns you otherwise.

## Troubleshooting

- **No certificate / HTTPS fails** → DuckDNS must resolve to the VM IP and ports
  80/443 must be open (the "Allow HTTP/HTTPS" firewall tags). Check `caddy` logs.
- **Login works but the app can't stay logged in** → `FRONTEND_ORIGIN` must exactly
  match the Vercel URL, and `COOKIE_SECURE=true` + `COOKIE_SAMESITE=none` must be set
  (cross-site cookie). Restart the api after changing `.env`.
- **Out of memory / killed** → confirm swap (`free -h`); the `e2-micro` needs it.
- **App won't start in prod** → you left `JWT_SECRET` as the sample; set a real one.
