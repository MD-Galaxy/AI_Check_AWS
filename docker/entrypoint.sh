#!/bin/sh
# Runs once every time the "app" container starts, before the web server.
#
# `alembic upgrade head` is safe to run on every single start: Alembic
# records the last-applied revision in the `alembic_version` table, so if
# the schema is already up to date this is a no-op — it will NEVER raise a
# duplicate-table / duplicate-column error, no matter how many times the
# container is restarted or recreated.
set -e

echo "[entrypoint] Waiting for database migrations..."
alembic upgrade head
echo "[entrypoint] Migrations up to date."

echo "[entrypoint] Starting: $*"
exec "$@"
