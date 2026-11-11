# Lock In Mode

A minimal, gamified fitness app where you're the main character.
Personalised home or gym workouts, explained simply, and every workout levels you up.

**Status:** 🚧 Phase 1 – Foundation

## Tech stack

FastAPI · PostgreSQL · SQLAlchemy 2 (async) · Alembic · Redis · Docker Compose · uv

## Local development

**Requirements:** Docker Desktop, Python 3.13, [uv](https://docs.astral.sh/uv/)

```powershell
# 1. Start the database and cache (from the repo root)
cp .env.example .env        # first time only, then fill in values
docker compose up -d

# 2. Run migrations and the API (from backend/)
cd backend
uv run alembic upgrade head
uv run fastapi dev src/lock_in_mode_api/main.py
```

- API docs: http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

## Architecture decisions

Key design decisions and their reasoning are recorded in [`docs/decisions/`](docs/decisions/).