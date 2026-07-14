# AI Check AWS

Two proofs of concept, served by **one process on one port** from this one
repo (`src/app.py` mounts the Bedrock POC's routes into the same FastAPI app
EmailPOC runs):

- **EmailPOC** — RFQ (Request for Quotation) email conversations with
  suppliers using dynamic email addressing, backed by PostgreSQL. Served at
  **`/email_poc`**. See [`RFQ_EMAIL_FLOW.md`](RFQ_EMAIL_FLOW.md),
  [`registration_guide.md`](registration_guide.md) and
  [`email_tracking.md`](email_tracking.md) for how the app itself works.
- **Bedrock Availability POC** ([`bedrock_availability_poc/`](bedrock_availability_poc/)) —
  checks which AI model providers (Claude, DeepSeek, Qwen, ChatGPT, Zhipu
  GLM) your AWS account can actually access on Amazon Bedrock, by really
  invoking each one. Served at **`/check-bedrock`**. See
  [`bedrock_availability_poc/README.md`](bedrock_availability_poc/README.md)
  for how the check itself works (that doc also still covers running it
  entirely standalone, on its own port, if you want that instead).

Once running, open **`/`** — a landing page with three sections that link
into both: running the Bedrock check, a "default user" login bypass, and
the normal EmailPOC register/login/track flow.

This README covers **installation only** — running the stack with Docker,
or running it manually.

---

## Option A: Docker (recommended — no Python setup required)

Runs two containers with one command: Postgres, and the app (EmailPOC +
Bedrock Availability POC together, one image, one port).

### 1. Install Docker Desktop

Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
and make sure it's running. That's the only prerequisite — you do **not**
need Python, `uv`, or Postgres installed on your machine.

### 2. Get credentials

- **EmailPOC**: an `API_USER`/`API_KEY` pair from either
  [EngageLab](setup_docs/engagelab_guide/engagelab_setup.md) or
  [SendCloud](setup_docs/aurora_send_cloud), plus a sending domain.
- **Bedrock Availability POC**: AWS credentials (access key/secret, or a
  profile) with `bedrock:ListFoundationModels` and `bedrock:InvokeModel`.
  Optionally an `ANTHROPIC_API_KEY` for the extra direct-API check.

You can skip this step to just click through the UI without sending mail or
running a real Bedrock check — the app still starts, it just can't do the
real work until these are set.

### 3. Run it

```bash
make up
```

**No `make`?**

```bash
cp .env.docker.example .env
docker compose up -d --build
```

The first run creates `.env` from [`.env.docker.example`](.env.docker.example)
and stops so you can fill in your credentials. Open `.env`, fill in
`SECRET_KEY`, the EngageLab and/or SendCloud block (`{PROVIDER}_API_USER`,
`{PROVIDER}_API_KEY`, `{PROVIDER}_OUTBOUND_DOMAIN`), and the AWS/Anthropic
variables — then run the same command again.
This time it builds the image, starts Postgres, waits for it to be
healthy, and starts the app container. Its entrypoint also applies
database migrations automatically on every start (safe to re-run — see
[`docker/entrypoint.sh`](docker/entrypoint.sh)).

Once it's up, open:

| URL | What it is |
| --- | --- |
| `http://localhost:8000/` | Landing page — links to both POCs |
| `http://localhost:8000/email_poc/` | EmailPOC |
| `http://localhost:8000/check-bedrock/` | Bedrock Availability check (JSON) |

### Everyday commands

| Command         | What it does                                       |
| ---------------- | --------------------------------------------------- |
| `make up`        | Build (if needed) and start everything               |
| `make logs`      | Follow every container's logs                        |
| `make down`      | Stop everything (data is kept)                        |
| `make restart`   | Restart the containers                                |
| `make ps`        | Show container status                                 |
| `make migrate`   | Manually re-run EmailPOC's database migrations         |
| `make reset-db`  | Stop everything **and delete the database volume**     |
| `make john-carter` | Open EmailPOC pre-logged-in as the demo "John Carter" user (needs `DEV_BYPASS_LOGIN=true`) |

No `make`? Run the equivalent `docker compose ...` commands directly — see
the [`Makefile`](Makefile), each target is a one-liner.

---

## Option B: Manual (no Docker)

One process serves both POCs — start it once and both `/email_poc` and
`/check-bedrock` are live.

Prerequisites: Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), PostgreSQL
16 (or just `docker compose up -d db`), and an AWS account with Bedrock
access for the Bedrock check.

```bash
# 1. Install dependencies (uv creates .venv automatically; this also pulls
#    in boto3/rich/anthropic for the Bedrock POC — see pyproject.toml)
uv sync

# 2. Start Postgres (or point DATABASE_URL at one you already have)
docker compose up -d db

# 3. Configure environment
cp .env.example .env
nano .env            # EngageLab/SendCloud credentials, and AWS_REGION + credentials

# 4. Apply database migrations
uv run alembic upgrade head

# 5. Run the hot-reload development server
uv run python main.py
# or directly:
uv run uvicorn src.app:app --host 0.0.0.0 --port 8000 --reload
```

Open **http://localhost:8000/** (landing page), or go straight to
**http://localhost:8000/email_poc/** or
**http://localhost:8000/check-bedrock/**. See
[`bedrock_availability_poc/README.md`](bedrock_availability_poc/README.md)
for the full breakdown of what the Bedrock check does and how to read its
output (and how to run that POC entirely on its own, on its own port,
instead of merged into this app).

---

## Environment variables

- [`.env.docker.example`](.env.docker.example) — the template for the
  Docker quick start above (Option A). One `.env`, shared by both
  containers.
- [`.env.example`](.env.example) — the template for manual/local EmailPOC
  development (Option B), covering EngageLab, SendCloud, and the Bedrock
  Availability POC's AWS/Anthropic variables.
- [`bedrock_availability_poc/.env.example`](bedrock_availability_poc/.env.example) —
  the template for running the Bedrock POC entirely standalone (its own
  `.env`, independent of the root one).

Copy whichever applies to `.env` and fill in your values — each app fails
fast at startup with a clear message if something required is missing.
