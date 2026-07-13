# AI Check AWS

Two proofs of concept, run together from this one repo:

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
  for how the check itself works.

Once running, open **`/`** — a landing page with three sections that link
into both: running the Bedrock check, a "default user" login bypass, and
the normal EmailPOC register/login/track flow.

This README covers **installation only** — running the stack with Docker,
or running each service manually.

---

## Option A: Docker (recommended — no Python setup required)

Runs three containers with one command: Postgres, EmailPOC, and the
Bedrock Availability POC.

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
running a real Bedrock check — both services still start, they just can't
do the real work until these are set.

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
`SECRET_KEY`, `INBOUND_DOMAIN`, `FROM_EMAIL`, the EngageLab or SendCloud
pair, and the AWS/Anthropic variables — then run the same command again.
This time it builds the images, starts Postgres, waits for it to be
healthy, and starts both app containers. EmailPOC's container also applies
database migrations automatically on every start (safe to re-run — see
[`docker/entrypoint.sh`](docker/entrypoint.sh)).

Once it's up, open:

| URL | What it is |
| --- | --- |
| `http://localhost:7000/` | Landing page — links to both POCs |
| `http://localhost:7000/email_poc/` | EmailPOC |
| `http://localhost:8080/check-bedrock/` | Bedrock Availability check (JSON) |

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

Each service is run independently — use this if you're actively developing
one of them and want hot-reload.

### EmailPOC

Prerequisites: Python ≥ 3.11, [uv](https://docs.astral.sh/uv/), PostgreSQL
16 (or just `docker compose up -d db`).

```bash
# 1. Install dependencies (uv creates .venv automatically)
uv sync

# 2. Start Postgres (or point DATABASE_URL at one you already have)
docker compose up -d db

# 3. Configure environment
cp .env.example .env
nano .env            # set EMAIL_PROVIDER (engagelab/sendcloud) + its credentials

# 4. Apply database migrations
uv run alembic upgrade head

# 5. Run the hot-reload development server
uv run python main.py
# or directly:
uv run uvicorn src.app:app --host 0.0.0.0 --port 7000 --reload
```

Open **http://localhost:7000/** (landing page) or
**http://localhost:7000/email_poc/** directly.

### Bedrock Availability POC

Prerequisites: Python ≥ 3.9, an AWS account with Bedrock access.

```bash
cd bedrock_availability_poc
pip install -r requirements.txt
cp .env.example .env
nano .env             # set AWS_REGION + credentials

# CLI (one-off check, prints a table + writes a JSON report)
python main.py

# Or as a web service (FastAPI, hot-reload)
uvicorn app:app --host 0.0.0.0 --port 8080 --reload
```

Open **http://localhost:8080/check-bedrock/**. See
[`bedrock_availability_poc/README.md`](bedrock_availability_poc/README.md)
for the full breakdown of what the check does and how to read its output.

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
