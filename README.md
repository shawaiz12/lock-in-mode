# Lock In Mode

A minimal, gamified fitness app where you're the main character.
Personalised home or gym workouts, explained simply, and every workout levels you up.

**Status:** 🚧 Phase 1 – Foundation

## Tech stack

FastAPI · PostgreSQL · SQLAlchemy 2 (async) · Alembic · Redis · Docker Compose · uv

## Local development

### Prerequisites
- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Docker Desktop (WSL2 backend on Windows)
- Git

### First-time setup
```bash
git clone https://github.com/shawaiz12/lock-in-mode.git
cd lock-in-mode
cp .env.example .env              # then fill in the POSTGRES_* values

docker compose up -d              # starts postgres + redis
docker compose ps                 # wait until both show "healthy"

cd backend
uv sync                           # creates .venv and installs locked deps
uv run alembic upgrade head       # applies all migrations
uv run fastapi dev src/lock_in_mode_api/main.py
```

Check it's running: open http://127.0.0.1:8000/health (API docs at http://127.0.0.1:8000/docs).

> **Windows note:** if uv's cache and the project are on different drives, set `UV_LINK_MODE=copy` to silence hardlink warnings.

### Every session
```bash
docker compose up -d
cd backend && uv run fastapi dev src/lock_in_mode_api/main.py
```

## Architecture decisions

Key design decisions and their reasoning are recorded in [`docs/decisions/`](docs/decisions/).