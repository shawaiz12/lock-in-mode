# Lock In Mode

[![CI](https://github.com/shawaiz12/lock-in-mode/actions/workflows/ci.yml/badge.svg)](https://github.com/shawaiz12/lock-in-mode/actions/workflows/ci.yml)

A minimal, gamified fitness app where you're the main character.
Personalised home or gym workouts, explained simply, and every workout levels you up.

**Status:** 🚧 Phase 1 – Foundation

## Tech stack

FastAPI · PostgreSQL · SQLAlchemy 2 (async) · Alembic · Redis · Docker Compose · uv ·
pytest · Ruff · mypy (strict) · GitHub Actions

## Run it (Docker only)

The quickest way to run the whole backend. You only need Docker Desktop and Git.

```bash
git clone https://github.com/shawaiz12/lock-in-mode.git
cd lock-in-mode
cp .env.example .env              # then fill in the POSTGRES_* values

docker compose up -d --build      # postgres, redis, migrations, API
docker compose ps -a              # migrate: "Exited (0)", everything else: "healthy"
```

Open http://localhost:8000/health (API docs at http://localhost:8000/docs).

What starts:

| Service    | What it does                                                                 |
|------------|------------------------------------------------------------------------------|
| `postgres` | PostgreSQL 17, data kept in the `postgres_data` volume                       |
| `redis`    | Redis 8 (cache, rate limits, background job broker)                          |
| `migrate`  | One-off job: runs `alembic upgrade head`, then exits                         |
| `api`      | FastAPI app (uvicorn) on port 8000; starts only after `migrate` succeeds     |

After changing backend code, rebuild with `docker compose up -d --build api`.

## Local development (hot reload)

For day-to-day coding, run the API on your machine with auto-reload and keep only
the databases in Docker.

### Prerequisites
- Python 3.13 and [uv](https://docs.astral.sh/uv/)
- Docker Desktop (WSL2 backend on Windows)
- Git

### First-time setup
```bash
cp .env.example .env              # if you haven't already

docker compose up -d postgres redis
docker compose ps                 # wait until both show "healthy"

cd backend
uv sync                           # creates .venv and installs locked deps (incl. dev tools)
uv run alembic upgrade head       # applies all migrations
uv run fastapi dev src/lock_in_mode_api/main.py
```

> Port 8000 is used by both the `api` container and `fastapi dev`. Stop one before
> starting the other: `docker compose stop api`.

> **Windows note:** if uv's cache and the project are on different drives, set
> `UV_LINK_MODE=copy` to silence hardlink warnings.

### Every session
```bash
docker compose up -d postgres redis
cd backend && uv run fastapi dev src/lock_in_mode_api/main.py
```

## Quality checks

The same checks run in CI on every push (see `.github/workflows/ci.yml`). Run them
from `backend/` before pushing:

```bash
uv run ruff check .               # lint
uv run ruff format --check .      # formatting
uv run mypy                       # strict type checking
uv run pytest -v                  # tests (needs the postgres container running)
```

Tests never touch your dev data: they create a separate `lockin_test` database,
apply all migrations to it, and roll back every test
(see [ADR 0004](docs/decisions/0004-test-database-strategy.md)).

## Architecture decisions

Key design decisions and their reasoning are recorded in [`docs/decisions/`](docs/decisions/).
