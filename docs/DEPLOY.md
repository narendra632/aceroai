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

# Google needs NO key — the VM's service account supplies credentials (step 5).
GOOGLE_CLOUD_PROJECT=<your project id>
OPENAI_API_KEY=<optional; leave blank and OpenAI isn't offered in Settings>
MODEL_CHAT=gemini-3.5-flash
MODEL_HEAVY=gemini-3.1-pro-preview
VAPID_PUBLIC_KEY=<from `uv run python -m app.scripts.generate_vapid`>
VAPID_PRIVATE_KEY=<the private half — never leaves the server>
VAPID_SUBJECT=mailto:you@example.com

# Embeddings: pick the region nearest THIS SERVER, not nearest you.
# The Oregon VM → us-central1. (The `global` endpoint measured ~12 s per call.)
EMBED_LOCATION=us-central1

APP_ENV=prod
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
6. Open the Vercel URL, log in, and try it from your phone. If notifications are
   configured, the bot works too (its poller runs in the api container).

**Done** — you're live. 🎉

---

## Stage 2 — CI/CD (after Stage 1 works)

Goal: **push to `main` → tests run → GitHub builds the image → the VM pulls &
restarts**, with no SSH-by-hand. The frontend already auto-deploys (Vercel); this
gives the backend the same.

**How it works (already coded):**
- `docker-compose.prod.yml` — `api` and `migrate` now carry both an
  `image: ghcr.io/narendra632/aceroai-backend:latest` **and** `build: ./backend`,
  so CI builds+pushes that image and the VM only *pulls* it (a 1 GB VM builds
  poorly; GitHub's runners don't). A local `up --build` still works.
- `.github/workflows/ci.yml` — after the `backend` (test) job is green, a `deploy`
  job runs **only on a push to `main`** (never on PRs). It builds the image, pushes
  it to **GHCR** (GitHub's private container registry), then SSHes to the VM and runs
  `git pull` → `docker compose pull` → `up -d`. Migrations run automatically inside
  `up -d` (the `migrate` service). The VM authenticates to GHCR with a **short-lived
  token** piped over SSH — no permanent registry password is stored on the box.

**What you set up once (manual):**

**1. Make a deploy SSH key** (CI → VM). On your laptop (Git Bash) or GCP Cloud
Shell — the comment **must** be your VM username (run `whoami` in the VM's SSH to
check; usually your Google account name):

```bash
ssh-keygen -t ed25519 -C "YOUR_VM_USERNAME" -f deploy_key -N ""
cat deploy_key.pub      # the PUBLIC half
cat deploy_key          # the PRIVATE half (keep secret)
```

**2. Give the VM the public half** — the GCP-correct way (survives reboots; a
key pasted straight into `authorized_keys` can be wiped by Google's guest agent):
Console → **Compute Engine → VM instances → click the VM → Edit → SSH Keys → Add
item** → paste the whole `deploy_key.pub` line → **Save**. (GCP reads the username
from the key's comment, which is why step 1's `-C` must match.)

**3. Add three GitHub repo secrets** — repo → **Settings → Secrets and variables →
Actions → New repository secret**:

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | the VM's static external IP (`136.117.137.254`) |
| `DEPLOY_USER` | your VM username (the `whoami` / key comment from step 1) |
| `DEPLOY_SSH_KEY` | the **entire** `deploy_key` file — the private half, incl. the `-----BEGIN/END-----` lines |

*(You do **not** need a GHCR secret — the workflow's built-in `GITHUB_TOKEN` both
pushes the image and, piped over SSH, lets the VM pull it.)*

**4. Allow the token to publish packages** — repo → **Settings → Actions →
General → Workflow permissions** → ensure **Read and write permissions** is
selected (lets `GITHUB_TOKEN` push to GHCR).

**5. First run.** Push any commit to `main` (or re-run the latest workflow).
Watch repo → **Actions**: `backend` runs the tests, then `deploy` builds, pushes,
and updates the VM. Verify: `curl https://acero.duckdns.org/health` still returns
`{"status":"ok"}`, and on the VM `docker compose -f docker-compose.prod.yml ps`
shows the api container recently recreated. The image appears under repo →
**Packages** (private by default).

> **Rollback:** every build is also tagged `…:<git-sha>`. To roll back, SSH in and
> `docker compose -f docker-compose.prod.yml` won't help directly (it tracks
> `:latest`), so pull the good SHA and retag, or just revert the commit on `main`
> and let CI redeploy — the simplest path.

---

## Switching the LLM to Agent Platform (Vertex)

The backend reaches Gemini through **Agent Platform**, billed via **Google Cloud
Billing** — so Google Cloud credits pay for it (the prepaid AI Studio balance is a
different, unrelated pot). Auth is **Application Default Credentials**, so there is
**no API key on the server**.

**One-time, in the Cloud console:**
1. Enable the **Agent Platform / Vertex AI API** on the project.
2. Give the **VM's service account** the **`roles/aiplatform.user`** role
   (IAM → find the VM's service account → Edit → Add role). This is what lets the
   backend authenticate with no key file: ADC resolves through the VM's metadata
   server automatically.
3. **Widen the VM's access scopes to `cloud-platform`** — ⚠ *this is a second,
   separate gate and the role alone is not enough.* A GCE VM's **access scopes** limit
   which APIs it may even request a token for, independently of IAM. The default
   scopes exclude Vertex AI, so calls fail with:
   `403 PERMISSION_DENIED … ACCESS_TOKEN_SCOPE_INSUFFICIENT`.
   Scopes **cannot be changed while the VM is running**:
   ```bash
   gcloud compute instances stop  <vm> --zone <zone>
   gcloud compute instances set-service-account <vm> --zone <zone> \
     --scopes=https://www.googleapis.com/auth/cloud-platform
   gcloud compute instances start <vm> --zone <zone>
   ```
   (Console equivalent: stop the VM → Edit → **Access scopes → Allow full access to
   all Cloud APIs** → Save → Start.) A reserved static IP survives stop/start, so DNS
   and TLS are unaffected; containers restart on their own.
4. Set a **budget alert** on the billing account, so an exhausted credit shows up as a
   warning rather than as failed chats.

**In the server `.env`** (you edit it; never committed):
```
LLM_PROVIDER=google
GOOGLE_CLOUD_PROJECT=<your project id>
GOOGLE_CLOUD_LOCATION=global
MODEL_CHAT=gemini-3.5-flash
MODEL_HEAVY=gemini-3.1-pro-preview
EMBED_LOCATION=us-central1     # nearest region to the VM — NOT "global" (see below)
# OPENAI_API_KEY=              # optional — set it to offer OpenAI in Settings too
```
`LLM_API_KEY` is no longer needed for Google.

> ⚠ **`EMBED_LOCATION` matters a lot.** On the `global` endpoint an embedding measured
> **~12 s** once the connection went cold — which is every real message — versus
> ~1.8 s from `us-central1`. Vectors are identical across regions (verified cosine
> 1.000000), so this is pure latency. Pick the region nearest **the VM**: the Oregon
> VM wants `us-central1`; a laptop in India wants `asia-south1`. Full measurements in
> [`REQUEST-ANATOMY.md`](REQUEST-ANATOMY.md).

**Verify from the VM** after `docker compose ... up -d`:
```bash
docker compose -f docker-compose.prod.yml exec api \
  uv run python -c "import google.auth; c,p=google.auth.default(); print('ADC ok, project:', p)"
curl https://acero.duckdns.org/health
```
Then send a real message and ask the assistant to add a task.

**Rollback:** set `LLM_PROVIDER` back (with the previous key config) and restart.

**Local development** uses the same code path with your own identity:
`gcloud auth application-default login`.

## Operations

- **Logs**: `docker compose -f docker-compose.prod.yml logs -f api`
- **Restart**: `... up -d` (after editing `.env`) · **Stop**: `... down`
- **Update (manual)**: `git pull && docker compose -f docker-compose.prod.yml up -d --build`
- **DB backup** — automated nightly; see *Backups* below. To take an extra one by hand
  (before a risky migration, say):
  ```bash
  docker compose -f docker-compose.prod.yml exec -T db pg_dump -U agent agent > ~/backup-$(date +%F).sql
  ```
  ⚠ A dump left *on the same VM* protects against a bad migration but not against losing the
  disk. The scheduled job exists because that second case is the one that ends the project.
- **Budget**: you should stay at $0; the $1 alert warns you otherwise.

### Backups

Nightly copies of the database go to Google Cloud Storage. Three jobs, because three things
fail independently — `db_backup` (02:30), `restore_check` (04:00 on the 1st) and
`backup_watch` (10:00 daily). See docs/JOBS.md §8 for why the third is separate.

**One-time setup, in the Cloud console:**

1. **Create a bucket** — Cloud Storage → Buckets → Create. Uniform access, public access
   prevention on. Location is a free choice: `us` multi-region gives geo-redundancy across
   several US regions, which for a *backup* is a feature rather than a cost.
2. **Grant the VM's service account `Storage Object Admin` on that bucket** — bucket →
   Permissions → Grant access. **On the bucket, not the project.** It is the same service
   account that already authenticates Vertex.
3. **Set `BACKUP_BUCKET` in the server `.env`.**

No key file, no new secret. Authentication is Application Default Credentials through the
GCE metadata server — the same path Vertex already uses, which is why access scopes are
already `cloud-platform` and no VM restart is needed.

**Retention is configured on the bucket, not in code**, so it keeps working when the
application does not, and so nothing this project runs is ever capable of deleting a backup.
Add three lifecycle rules — Bucket → Lifecycle → Add a rule, *Delete object*, with **Age**
and **Prefix** conditions:

| Prefix | Delete after | Keeps roughly |
|---|---|---|
| `daily/` | 14 days | two weeks of nightly copies |
| `weekly/` | 56 days | eight weekly copies |
| `monthly/` | 365 days | a year of monthly copies |

⚠ **This is the one part of backups no test can verify.** Everything else is asserted in
`tests/test_backups.py` or proven monthly by `restore_check`; retention lives outside the
repository and is only ever confirmed by looking. Check the bucket after the first month.

At roughly 3 MB per copy, all of this is about 100 MB and well under ₹1/month.

**Why twelve monthly copies.** Daily and weekly copies cover mistakes noticed quickly. They
cannot cover the failure where wrong data is written and then faithfully copied every night
afterwards — at that point every recent copy contains the fault, and only one predating it
holds the truth. The monthlies also let you find *when* it started.

**Verifying it works.** The honest test is to break it on purpose: set `BACKUP_BUCKET` to a
name that does not exist, run `python -m app.jobs.run db_backup`, and confirm the failure
notification reaches your phone. Then set it back. An alarm nobody has ever set off is the
same class of thing as a backup nobody has ever restored.

### Trace retention

`turns` and `spans` are written on every model call — including the ones nobody sees, so
roughly four provider calls per message. Left alone they grow forever on a 10 GB disk, so
`services/retention.py` sweeps them once a local day, off the back of a real turn.

Three tiers, and the sweep always rolls up **before** it prunes:

| Table | Kept for | Setting |
|---|---|---|
| `spans` — the per-stage waterfall | 30 days | `SPAN_RETENTION_DAYS` |
| `turns` — one row per model call | 400 days | `TURN_RETENTION_DAYS` |
| `daily_usage` — one row per day per model | forever | — |

**Measured cost**, at 256 provider calls/day with 3 spans each (roughly four times the
observed rate, for headroom): `turns` are **319 bytes/row** and `spans` **183 bytes/row**,
so a full year unpruned is about **28 MiB + 49 MiB**. Under the windows above the steady
state settles near **35 MiB total**, and `daily_usage` adds well under a MiB a year.

So this is precautionary, not urgent — at today's volume the disk would last decades
either way. It exists so the footprint stays bounded if usage changes shape, and so the
Insights page keeps its history: **pruning never changes a spend figure.** The rollup is
what the page reads for any day it covers, and a turn is only ever deleted once its own
day has been rolled up.

What does NOT survive pruning, by nature: **latency percentiles and error kinds**. A
median cannot be re-derived from daily medians. Those panels are therefore bounded by
`TURN_RETENTION_DAYS`, and go blank rather than invent a number.

To change a window, set the variable in the server `.env` and restart the api. Shortening
one takes effect on the next sweep and is irreversible — the rows are gone.

## Troubleshooting

- **No certificate / HTTPS fails** → DuckDNS must resolve to the VM IP and ports
  80/443 must be open (the "Allow HTTP/HTTPS" firewall tags). Check `caddy` logs.
- **Login works but the app can't stay logged in** → `FRONTEND_ORIGIN` must exactly
  match the Vercel URL. Restart the api after changing `.env`. *(Auth is a bearer
  token in `localStorage`, not a cookie — `COOKIE_SECURE`/`COOKIE_SAMESITE` still
  exist but no longer affect login.)*
- **`403 PERMISSION_DENIED` / `ACCESS_TOKEN_SCOPE_INSUFFICIENT`** → the VM has the
  IAM role but not the **access scope**. Both gates are required — see step 5.3.
- **Out of memory / killed** → confirm swap (`free -h`); the `e2-micro` needs it.
- **App won't start in prod** → you left `JWT_SECRET` as the sample; set a real one.
