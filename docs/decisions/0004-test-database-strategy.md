# 0004 – Run database tests against a dedicated test database with per-test rollback

**Date:** 2026-11-12
**Status:** Accepted

## Context
The schema enforces important rules in the database itself: CHECK constraints
(days per week 2–6, difficulty 1–5), foreign keys, unique keys and ON DELETE
behaviour (ADR 0003). These rules protect the data no matter which service writes
it (FastAPI now, the admin panel later), so they need tests that run against real
Postgres. Constraint tests deliberately insert bad rows, so we need answers to two
questions:

1. **Where does the test database come from?** It must be isolated from dev data, so
   tests can't damage it and existing rows can't make tests fail.
2. **How does each test start clean?** Rows from one test must never be visible to
   the next.

## Options considered

### 1. Dev database, each test rolled back
- ✅ No setup at all.
- ❌ One mistake (a real commit, a cleanup that truncates tables) destroys dev data.
- ❌ Dev data makes tests flaky: a seeded `push-up` exercise breaks any test that
  inserts the slug `push-up`, even though the code is correct.
- ❌ Tests run against whatever state the dev schema is in (e.g. after a downgrade).
- ❌ CI has no dev database, so CI would need a different approach anyway.

### 2. Testcontainers (a new Postgres container per test run)
- ✅ Fully self-contained: `pytest` alone is enough, nothing is left behind.
- ❌ Adds 2–5 seconds to every run, plus another dependency.
- ❌ Runs a second Postgres next to the one Docker Compose already provides.
- ❌ Occasionally unreliable with Docker Desktop on Windows.

### 3. SQLite or an in-memory database
- ✅ Very fast, no Docker needed.
- ❌ A different database engine. Our CHECK constraints, `gen_random_uuid()`, array
  columns and ON DELETE behaviour don't exist or behave differently, so passing tests
  would prove nothing about Postgres.

### 4. A separate `lockin_test` database in the Compose Postgres (chosen)
- ✅ Fastest feedback: Postgres is already running.
- ✅ Same Postgres 17 image as dev, so constraints behave exactly as in production.
- ✅ Same model as CI, where GitHub Actions runs Postgres as a service container.
- ❌ `docker compose up` must be running before `pytest`.

## Decision
Use option 4.

**Where the database comes from**
- `tests/conftest.py` sets `POSTGRES_DB=lockin_test` *before* importing the app.
  `settings` and `engine` are created at import time, and real environment variables
  override `.env` in pydantic-settings, so this is the one place to redirect them.
- A session-scoped fixture **drops and recreates** `lockin_test` at the start of every
  run (`DROP DATABASE ... WITH (FORCE)` from the `postgres` maintenance database, with
  `AUTOCOMMIT`), then runs `alembic upgrade head`. Every run starts from an empty
  database, and the real migrations are tested from scratch each time. The database is
  left in place after the run so failures can be inspected.
- **Safety guard:** the fixture refuses to run unless the database name ends in
  `_test`, because it drops a database.

**How each test starts clean**
- The `db_session` fixture opens one connection, begins a transaction, runs the test,
  and **rolls back**. Nothing a test writes survives it.
- The session uses `join_transaction_mode="create_savepoint"`. In Postgres, one failed
  statement aborts the whole transaction; constraint tests fail statements on purpose,
  so each flush runs inside a savepoint and only rolls back to it.
- Tests call `flush()` (sends the SQL, checks constraints) and never `commit()`.

## Consequences
- ✅ Dev data can't be touched by tests, and can't make tests fail.
- ✅ Migrations are applied to an empty database on every run, so a broken migration
  fails the test suite before it reaches production.
- ✅ Tests assert on constraint names (`ck_profiles_days_per_week_range`), thanks to the
  naming convention in `models/base.py`, so they check *which* rule fired.
- ⚠️ Rollback can't test anything that needs a real commit seen from another
  connection: a Celery worker reading what the API wrote, or two concurrent requests.
  Those tests will need to commit and then truncate tables instead.
- ⚠️ Running Alembic inside the test process exposed that `fileConfig()` disables
  existing loggers by default. `env.py` now passes `disable_existing_loggers=False`.
- ⚠️ The env-var override must stay above the app imports in `conftest.py`; moving it
  below them would silently point tests at the dev database. The `_test` guard is the
  safety net if that ever happens.
- 🔁 **Easy to reverse:** tests only depend on the `db_session` fixture, not on where the
  database comes from. Switching to Testcontainers later means changing one fixture.