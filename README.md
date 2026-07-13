# EmailPOC

A FastAPI proof-of-concept for managing RFQ (Request for Quotation) email
conversations with suppliers using **dynamic email addressing**, backed by
**PostgreSQL** and a simple session-based login/registration flow. The
supported and actively-documented providers are **SendGrid** and
**EngageLab**; Mailgun, Elastic Email and SendCloud are also implemented and
selectable via config, but have no written setup guide in this repo.
SendCloud outbound sending is fully implemented; its inbound reply parsing
is a stub (no SendCloud inbound webhook payload doc is available yet).
EngageLab has both outbound sending and inbound reply parsing implemented —
see [`setup_docs/engagelab_guide/engagelab_setup.md`](setup_docs/engagelab_guide/engagelab_setup.md).

Each conversation gets a unique email address that encodes the user and
conversation IDs directly in the local-part:

```
usr42_conv3fa9c1b2@mail.yourdomain.com
 ↑         ↑
user_id   conv_id
```

Supplier replies go back to the same address. The active provider's inbound
feature (SendGrid Inbound Parse / Mailgun Routes / Elastic Email inbound
notifications / EngageLab Inbound Route / SendCloud — not yet implemented)
posts the reply to the single `/email_poc/webhooks/inbound` endpoint, which parses
both IDs and stores the reply against the correct conversation — no lookup
tables needed on the mail side.

---

## Quick start with Docker (recommended — no Python setup required)

This is the fastest way to run the whole project — a Postgres database and
the web app — with **one command**. It works the same way on Windows,
macOS and Linux, and is what you should use if you're just trying the app
out or handing it to someone non-technical to run.

### 1. Install Docker Desktop

Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/)
and make sure it's running (you'll see its icon in your system tray/menu
bar). That's the only prerequisite — you do **not** need Python, `uv`, or
Postgres installed on your machine.

### 2. Get EngageLab credentials

You need an `API_USER` / `API_KEY` pair from the EngageLab dashboard and a
sending domain. The full walkthrough is in
[`setup_docs/engagelab_guide/engagelab_setup.md`](setup_docs/engagelab_guide/engagelab_setup.md).
(Skip this step if you only want to click through the UI without actually
sending mail — the app will still start, it just can't send/receive email
until these are set.)

### 3. Run it

**macOS / Linux (or Windows with `make` via WSL / Git Bash):**

```bash
make up
```

**Windows, no `make` installed:** double-click **`run.bat`**.

**Without `make` at all**, on any OS:

```bash
cp .env.docker.example .env
docker compose up -d --build
```

The first run creates `.env` from [`.env.docker.example`](.env.docker.example)
and stops so you can fill in your credentials (`SECRET_KEY`,
`INBOUND_DOMAIN`, `FROM_EMAIL`, `ENGAGELAB_API_USER`, `ENGAGELAB_API_KEY`).
Open `.env` in any text editor, fill those in, and run the same command
again — this time it builds the images, starts Postgres, waits for it to be
healthy, and starts the app.

The app container automatically creates the database schema (via Alembic
migrations) every time it starts — see
[Database & migrations](#database--migrations) below for why that's always
safe to re-run.

Once it's up, open **http://localhost:7000/email_poc/** in your browser.

### Everyday commands

| Command             | What it does                                              |
| ------------------- | ---------------------------------------------------------- |
| `make up`           | Build (if needed) and start everything                     |
| `make logs`         | Follow the app + database logs                             |
| `make down`         | Stop everything (data is kept)                             |
| `make restart`      | Restart the containers                                     |
| `make ps`           | Show container status                                      |
| `make migrate`      | Manually re-run database migrations (rarely needed)         |
| `make reset-db`     | Stop everything **and delete the database volume**          |

No `make`? Run the equivalent `docker compose ...` commands directly — see
the [`Makefile`](Makefile), each target is a one-liner.

---

## Features

- **SendGrid-first** — domain-level authentication + Inbound Parse, fully
  documented in [`setup_docs/sendgrid_guide/sendgrid_dynamic_domain_auth.md`](setup_docs/sendgrid_guide/sendgrid_dynamic_domain_auth.md).
- **EngageLab** — dynamic sender addresses + Inbound Route webhook, fully
  documented in [`setup_docs/engagelab_guide/engagelab_setup.md`](setup_docs/engagelab_guide/engagelab_setup.md).
- **Pluggable providers** — the code also supports Mailgun, Elastic Email and
  SendCloud via a single `EMAIL_PROVIDER` env var (no code changes), but they
  have no written setup guide in this repo yet. SendCloud inbound reply
  parsing is not implemented (outbound sending only).
- **Send RFQ emails** from a per-conversation dynamic address.
- **One inbound webhook** for every provider — a factory selects the right
  parser to normalise each provider's payload (and attachments).
- **Accounts & sessions** — a 3-step registration wizard, login/logout, and
  sliding-expiry sessions backed by the database (see [`src/auth/`](src/auth)).
- **Track conversations** per user — statuses `open`, `replied`, `declined`.
- **Full conversation thread** view with HTML preview, attachment downloads
  and DKIM/SPF metadata.
- **PostgreSQL storage**, schema managed by Alembic migrations.
- **Single shared logger** with an env-configurable level (`LOG_LEVEL`).
- **Docker Compose setup** that runs the database and the app with one
  command, migrations included.

---

## Architecture

The application uses the **strategy + factory** pattern on both the outbound
and inbound sides, so providers are swappable and share all common logic.

```
EmailPOC/
├── main.py                       # Local dev entry point — boots Uvicorn with hot-reload
├── Dockerfile                    # App image (uv-based build)
├── docker-compose.yml            # Postgres + app, wired together
├── docker/entrypoint.sh          # Runs `alembic upgrade head`, then starts Uvicorn
├── Makefile                      # `make up` / `make down` / ... — one-command operation
├── run.bat                       # Windows double-click launcher (no `make` needed)
├── .env.docker.example           # Env template for Docker (EngageLab only)
├── .env.example                  # Env template for local (non-Docker) dev, all providers
├── alembic/                      # Database migrations (source of truth for the schema)
│   └── versions/
├── sql/schema.sql                # Plain-SQL mirror of the schema, for reference/manual psql
├── src/
│   ├── config.py                 # Settings — all env vars in one place
│   ├── logger.py                 # AppLogger — the single shared logger
│   ├── app.py                    # create_app() factory + `app` object
│   ├── route.py                  # HTTP routes — UI + the inbound webhook
│   ├── db/
│   │   ├── session.py            # Async SQLAlchemy engine/session factory
│   │   ├── models.py             # ORM models (mirrors sql/schema.sql)
│   │   └── repository.py         # All queries — routes never touch SQL/ORM directly
│   ├── auth/
│   │   ├── routes.py             # /login, /register (3 steps), /logout
│   │   ├── sessions.py           # Session token issuance/validation
│   │   ├── security.py           # Password hashing
│   │   └── dependencies.py       # `require_login` FastAPI dependency
│   ├── services/
│   │   └── conversation_service.py   # Business logic / orchestration
│   ├── email_platform/           # OUTBOUND providers
│   │   ├── email_master.py       # EmailMaster ABC (shared helpers)
│   │   ├── sendgrid_provider.py  # SendGrid SDK (primary, documented)
│   │   ├── mailgun_provider.py   # Mailgun HTTP API (requests)
│   │   ├── elasticemail_provider.py  # Elastic Email SDK
│   │   ├── sendcloud_provider.py # SendCloud HTTP API (requests)
│   │   ├── engagelab_provider.py # EngageLab HTTP API (requests, Basic Auth)
│   │   └── factory.py            # EmailProviderFactory
│   └── webhook_factory/          # INBOUND parsers
│       ├── webhook_master.py     # WebhookParserMaster ABC + InboundEmail
│       ├── sendgrid_webhook.py
│       ├── mailgun_webhook.py    # + HMAC signature verification
│       ├── elasticemail_webhook.py
│       ├── sendcloud_webhook.py  # Stub — no inbound doc yet
│       ├── engagelab_webhook.py  # EngageLab Inbound Route parser
│       └── factory.py            # WebhookParserFactory
├── templates/                    # Jinja2 UI templates
├── static/                       # Static assets (served at /static)
└── data/
    └── attachments/              # Saved inbound email attachments (persisted via a Docker volume)
```

Flow:

```
Browser UI ──(provider API)──▶ Supplier inbox
   │                                  │
   │            reply email           │
   ▼                                  ▼
POST /send                MX ──▶ provider inbound feature
   │                                  │
   ▼                                  ▼  HTTP POST
ConversationService ◀──── POST /email_poc/webhooks/inbound (one URL, any provider)
   │
   ▼
PostgreSQL
```

---

## Database & migrations

The schema lives in [`alembic/versions/`](alembic/versions) (the source of
truth) and is mirrored in [`sql/schema.sql`](sql/schema.sql) as a plain,
reviewable reference. Both use `IF NOT EXISTS` everywhere a table/index is
created, and Alembic additionally tracks which revisions have already been
applied in an `alembic_version` table it manages itself.

That combination is what makes migrations safe to run automatically, every
single time, with zero risk of a "duplicate object" error:

- Fresh database → `alembic upgrade head` runs every migration in order.
- Database already up to date → `alembic upgrade head` sees there's nothing
  left to apply and does **nothing**.

`docker/entrypoint.sh` runs exactly that command before starting the app on
**every** container start/restart, so the schema — including the seed data
in `0002_seed_products_and_users.py` — is always present without you having
to run anything by hand, and re-running it (as often as you like) never
raises an error.

If you ever want to start from a completely empty database, run
`make reset-db` (or `docker compose down -v`) — this deletes the Postgres
volume, so the next start applies every migration from scratch.

---

## Environment variables

Two templates are provided:

- **[`.env.docker.example`](.env.docker.example)** — everything needed to
  run the project with Docker Compose using **EngageLab only**. This is the
  one to use for the one-command Docker quick start above.
- **[`.env.example`](.env.example)** — the full template for local
  (non-Docker) development, covering every supported provider.

Copy whichever one applies to `.env` and fill in your values. Only the
active provider's credentials are required — the app fails fast at startup
with a clear message if the selected provider is misconfigured.

| Variable                      | Required     | Default                           | Description                                          |
| ----------------------------- | ------------ | --------------------------------- | ----------------------------------------------------- |
| `DATABASE_URL`                | ✅           | `postgresql+asyncpg://postgres:postgres@localhost:5433/emailpoc` | Async SQLAlchemy connection string |
| `SECRET_KEY`                  | ✅           | random per restart                | Signs the pending-registration cookie                 |
| `SESSION_TTL_DAYS`            | ❌           | `7`                                | Login session sliding expiry, in days                 |
| `SESSION_COOKIE_SECURE`       | ❌           | `true`                            | Set `false` only for plain `http://` (local dev)       |
| `EMAIL_PROVIDER`              | ✅           | `sendgrid`                        | `sendgrid` \| `mailgun` \| `elasticemail` \| `sendcloud` \| `engagelab` |
| `LOG_LEVEL`                   | ❌           | `INFO`                            | `DEBUG`/`INFO`/`WARNING`/`ERROR`                       |
| `INBOUND_DOMAIN`              | ✅           | —                                 | Subdomain whose MX points at the provider              |
| `FROM_EMAIL`                  | ✅           | —                                 | Verified sender (From header)                          |
| `COMPANY_NAME`                | ❌           | `Your Company`                    | Display name in From + signature                       |
| `SENDGRID_API_KEY`            | sendgrid     | —                                 | API key with Mail Send                                 |
| `MAILGUN_API_KEY`             | mailgun      | —                                 | Private API key                                        |
| `MAILGUN_DOMAIN`              | mailgun      | —                                 | Sending domain                                         |
| `MAILGUN_API_BASE`            | ❌           | `https://api.mailgun.net`         | Region base (US/EU)                                    |
| `MAILGUN_WEBHOOK_SIGNING_KEY` | ❌           | —                                 | Verifies inbound POSTs (recommended)                    |
| `ELASTICEMAIL_API_KEY`        | elasticemail | —                                 | API key with Send access                                |
| `ELASTICEMAIL_API_URL`        | ❌           | `https://api.elasticemail.com/v4` | v4 REST base URL                                        |
| `SENDCLOUD_API_USER`          | sendcloud    | —                                 | API user from the SendCloud console                     |
| `SENDCLOUD_API_KEY`           | sendcloud    | —                                 | API key from the SendCloud console                       |
| `SENDCLOUD_API_BASE`          | ❌           | `https://api.aurorasendcloud.com` | Region base (Singapore/US/HK)                            |
| `ENGAGELAB_API_USER`          | engagelab    | —                                 | API_USER created in the EngageLab dashboard              |
| `ENGAGELAB_API_KEY`           | engagelab    | —                                 | API_KEY generated for that API_USER                      |
| `ENGAGELAB_API_BASE`          | ❌           | `https://email.api.engagelab.cc`  | Region base (Singapore/Turkey)                           |

Docker-only variables (in `.env.docker.example`, read directly by
`docker-compose.yml`, not by the app):

| Variable          | Default    | Description                                  |
| ----------------- | ---------- | --------------------------------------------- |
| `POSTGRES_USER`   | `postgres` | Postgres role created in the `db` container    |
| `POSTGRES_PASSWORD` | `postgres` | Its password — keep in sync with `DATABASE_URL` |
| `POSTGRES_DB`     | `emailpoc` | Database name                                  |
| `POSTGRES_PORT`   | `5433`     | Host port the database is published on         |
| `APP_PORT`        | `7000`     | Host port the web app is published on          |

---

## Provider setup guide (SendGrid)

SendGrid is the primary, fully-documented provider. Domain authentication,
the inbound MX record, Inbound Parse webhook configuration and working code
samples are all covered end-to-end in:

- **[`setup_docs/sendgrid_guide/sendgrid_dynamic_domain_auth.md`](setup_docs/sendgrid_guide/sendgrid_dynamic_domain_auth.md)**

It walks through:

1. Authenticating the sending subdomain (domain-level auth, no per-address
   sender verification needed for dynamic addresses).
2. Adding the CNAME records SendGrid generates at your DNS provider.
3. Pointing an MX record at `mx.sendgrid.net` for inbound mail.
4. Configuring the Inbound Parse webhook to POST to `/email_poc/webhooks/inbound`.
5. Generating dynamic `From`/`Reply-To` addresses and sending/receiving RFQ
   emails end-to-end.

Mailgun, Elastic Email and SendCloud are implemented in
`src/email_platform/` and `src/webhook_factory/` and can be selected via
`EMAIL_PROVIDER`, but none has a written setup guide in this repo yet —
refer to each provider's own docs for domain authentication and inbound
routing if you switch to them. SendCloud specifically only sends outbound
mail today; its `src/webhook_factory/sendcloud_webhook.py` parser is a
stub that raises a clear error until SendCloud's inbound webhook payload
format is documented and implemented.

---

## Provider setup guide (EngageLab)

EngageLab is the second fully-documented provider — both outbound sending
(dynamic `from`/`reply_to` addresses) and inbound reply parsing (Inbound
Route webhook) are implemented. The complete walkthrough is in:

- **[`setup_docs/engagelab_guide/engagelab_setup.md`](setup_docs/engagelab_guide/engagelab_setup.md)**

It walks through:

1. Creating a Trigger Email `API_USER`/`API_KEY` pair in the EngageLab
   dashboard and binding it to your sending subdomain.
2. Authenticating the subdomain (SPF/DKIM TXT records + MX record) at your
   DNS provider.
3. Sending with dynamic, unregistered `from`/`reply_to` prefixes once the
   subdomain suffix is verified.
4. Binding an Inbound Route webhook to the `API_USER` so supplier replies
   POST to `/email_poc/webhooks/inbound`.
5. Testing outbound via `curl` and inbound via `ngrok`.

---

## Local development (without Docker)

Use this if you're actively developing the app and want hot-reload.

### Prerequisites

| Tool                             | Version | Notes                              |
| -------------------------------- | ------- | ----------------------------------- |
| Python                           | ≥ 3.11  | Union type hints `X \| Y`           |
| [uv](https://docs.astral.sh/uv/) | latest  | Fast Python package manager         |
| PostgreSQL                       | 16      | Or run just the `db` service: `docker compose up -d db` |
| A SendGrid or EngageLab account  | —       | Free tier is fine to start          |
| Domain with DNS control          | —       | Needed for domain auth + MX record  |

### Install & run

```bash
# 1. Install dependencies (uv creates .venv automatically)
uv sync

# 2. Start Postgres (or point DATABASE_URL at one you already have)
docker compose up -d db

# 3. Configure environment
cp .env.example .env
nano .env            # set EMAIL_PROVIDER + that provider's credentials

# 4. Apply database migrations
uv run alembic upgrade head

# 5. Run the hot-reload development server
uv run python main.py
# or directly:
uv run uvicorn src.app:app --host 0.0.0.0 --port 7000 --reload
```

Open **http://localhost:7000/email_poc/** in your browser.

### Creating a new migration

```bash
uv run alembic revision -m "describe your change"
# edit the generated file in alembic/versions/, then:
uv run alembic upgrade head
```

---

## Routes

Every path below is served under the `/email_poc` prefix, e.g. `/login` is
actually `/email_poc/login`.

### UI

| Method | Path                       | Description                     |
| ------ | --------------------------- | -------------------------------- |
| `GET`  | `/login`                    | Login page                       |
| `POST` | `/login`                    | Submit login                     |
| `POST` | `/logout`                   | End the current session          |
| `GET`  | `/register`                 | Registration wizard, step 1      |
| `POST` | `/register`                 | Submit step 1                    |
| `GET`  | `/register/confirm-name`    | Registration wizard, step 2      |
| `POST` | `/register/confirm-name`    | Submit step 2                    |
| `GET`  | `/register/assign-email`    | Registration wizard, step 3      |
| `POST` | `/register/assign-email`    | Submit step 3                    |
| `GET`  | `/`                          | Redirects to `/tracking`         |
| `GET`  | `/send`                      | Send RFQ form                    |
| `POST` | `/send`                      | Create a conversation and send   |
| `GET`  | `/tracking`                  | Personal dashboard — stats + list |
| `GET`  | `/tracking/{conv_id}`        | Full conversation thread         |
| `POST` | `/tracking/{conv_id}/delete` | Delete one of your conversations |

Every route above except the inbound webhook requires a logged-in user (see
[`src/auth/`](src/auth)).

### API

| Method | Path                      | Description                              |
| ------ | ------------------------- | ---------------------------------------- |
| `POST` | `/email_poc/webhooks/inbound`       | Inbound handler (any provider)           |
| `GET`  | `/email_poc/webhooks/inbound`       | Validation probe (Elastic Email GETs it) |
| `GET`  | `/email_poc/attachments/{filename}` | Download a saved attachment              |

---

## Development tips

### Expose localhost to your provider (for webhook testing)

```bash
ngrok http 7000
# Copy the https URL into the provider's inbound webhook config:
#   https://<subdomain>.ngrok-free.app/email_poc/webhooks/inbound
```

### Simulate an inbound reply (without a real email)

The payload field names differ per provider. Example for **SendGrid**:

```bash
curl -X POST http://localhost:7000/email_poc/webhooks/inbound \
  -F "from=buyer@acme.com" \
  -F "to=usr42_conv3fa9c1b2@mail.yourdomain.com" \
  -F "subject=RE: RFQ" \
  -F "text=Our price is \$11.50 per unit. MOQ 200 units." \
  -F "spam_score=0.1"
```

See [`setup_docs/sendgrid_guide/sendgrid_dynamic_domain_auth.md`](setup_docs/sendgrid_guide/sendgrid_dynamic_domain_auth.md)
for SendGrid's exact inbound field names; other providers use different
field names for the same data.

### Reset local data

- **Database**: `make reset-db` (Docker) or `docker compose down -v` — wipes
  the Postgres volume; the next start re-applies every migration from
  scratch.
- **Saved attachments**: `rm -rf data/attachments/*`
