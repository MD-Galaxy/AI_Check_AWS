.DEFAULT_GOAL := up
.PHONY: up down restart build logs ps migrate reset-db clean john-carter

# One command to run the whole project: builds the image, starts Postgres +
# the app (EmailPOC and the Bedrock Availability POC in one process, one
# port), and the app's entrypoint applies database migrations automatically
# (safe to run every time — see docker/entrypoint.sh).
up:
	@if [ ! -f .env ]; then \
		cp .env.docker.example .env; \
		echo ""; \
		echo "==> Created .env from .env.docker.example."; \
		echo "==> Open .env and fill in: SECRET_KEY, INBOUND_DOMAIN, FROM_EMAIL,"; \
		echo "==> ENGAGELAB_API_USER, ENGAGELAB_API_KEY (or the SENDCLOUD_* pair"; \
		echo "==> instead), and AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY (or"; \
		echo "==> AWS_PROFILE) for the Bedrock check — then run 'make up' again."; \
		echo ""; \
		exit 1; \
	fi
	docker compose up -d --build
	@PORT=$$(grep -m1 '^APP_PORT=' .env | cut -d= -f2); PORT=$${PORT:-8000}; \
	echo ""; \
	echo "Starting up. Give it a few seconds, then open:"; \
	echo "  http://localhost:$$PORT/                   (landing page — links to both POCs)"; \
	echo "  http://localhost:$$PORT/email_poc/          (EmailPOC)"; \
	echo "  http://localhost:$$PORT/check-bedrock/      (Bedrock Availability check)"; \
	echo "Follow logs with: make logs"

down:
	docker compose down

restart:
	docker compose restart

build:
	docker compose build --no-cache

logs:
	docker compose logs -f

ps:
	docker compose ps

# Re-run migrations by hand (the app container already does this on every
# start; this is only useful for troubleshooting).
migrate:
	docker compose exec app alembic upgrade head

# Wipe the database volume too — the next 'make up' starts from an empty DB.
reset-db:
	docker compose down -v

clean: down
	docker image prune -f

# Local-dev shortcut: bypass login/registration and land on the Send RFQ
# page as a fixed "John Carter" user. Requires DEV_BYPASS_LOGIN=true in .env
# (off by default — see src/auth/dev_bypass.py); the route 404s otherwise.
# Combine with 'up' in one command: `make up john-carter` builds+starts the
# stack, waits for it to answer, then opens the browser logged in.
john-carter:
	@if [ ! -f .env ] || ! grep -qi '^DEV_BYPASS_LOGIN=true' .env; then \
		echo "DEV_BYPASS_LOGIN is not enabled."; \
		echo "Add 'DEV_BYPASS_LOGIN=true' to .env, then run 'make restart' (or 'make up')."; \
		exit 1; \
	fi
	@PORT=$$(grep -m1 '^APP_PORT=' .env | cut -d= -f2); \
	PORT=$${PORT:-8000}; \
	echo "Waiting for EmailPOC to be ready on port $$PORT..."; \
	for i in $$(seq 1 30); do \
		curl -sf -o /dev/null "http://localhost:$$PORT/email_poc/login" && break; \
		sleep 1; \
	done; \
	URL="http://localhost:$$PORT/email_poc/dev/login-john-carter"; \
	echo "Logging in as John Carter: $$URL"; \
	(xdg-open "$$URL" >/dev/null 2>&1 || open "$$URL" >/dev/null 2>&1) || echo "Open manually: $$URL"
