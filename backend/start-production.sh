#!/bin/sh
# How the API starts on the hosting platform (ADR 0028). The platform runs:
#   sh start-production.sh
# Locally, docker compose does the same three steps as separate services.
#
# 1) Bring the database schema up to date.
# 2) Load the exercise library (safe to repeat: unchanged exercises are left alone).
# 3) Start the API. `exec` hands the process over to uvicorn, so the platform's stop
#    signal reaches it and it shuts down cleanly (finishes requests, stops the cleanup).
#
# `set -e`: if step 1 or 2 fails, the script stops and the API never starts. The
# platform then sees a failed deploy instead of an API running on a half-updated database.
set -eu

alembic upgrade head
python -m lock_in_mode_api.seed
exec uvicorn lock_in_mode_api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
