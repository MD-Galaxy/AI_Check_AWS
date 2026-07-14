# syntax=docker/dockerfile:1

# ── App image: EmailPOC + Bedrock Availability POC (one process, one port) ────
# Builds the FastAPI app with uv (same tool + lockfile used for local dev, so
# the container gets the exact versions pinned in uv.lock). `COPY . .` below
# also brings in bedrock_availability_poc/, whose routes src/app.py mounts
# into this same app — see that file for how. The container's entrypoint
# (docker/entrypoint.sh) runs `alembic upgrade head` before every start —
# idempotent by design (Alembic tracks the applied revision in the
# `alembic_version` table), so re-running it on every container start never
# raises a duplicate/already-exists error.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first, in their own layer, so editing application code
# doesn't invalidate the (slow) dependency install on rebuild.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
# --no-access-log: our own middleware (src/app.py) already logs every
# request (with the real client IP, not just the ALB's) except /health
# probes - Uvicorn's built-in access log would otherwise duplicate that
# and, worse, still log every ALB health check every ~15s per AZ.
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
