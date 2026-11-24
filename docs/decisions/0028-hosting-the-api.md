# 0028 – Hosting the API

**Date:** 2026-11-24
**Status:** Accepted

## Context
The mobile app (ADR 0029) needs the API online. The brief's rule stands: no paid services
until usage outgrows free tiers. Free tiers were re-checked on 2026-11-24, because they
change:

| Option | What its free plan does to us |
|---|---|
| Render (the brief's plan) | Web service sleeps after 15 idle minutes; the next request waits about a minute. Free Postgres **expires after 30 days** and has no backups. |
| Vercel Hobby (checked at the user's request) | **Personal, non-commercial use only**; Lock In Mode is a startup. Runs the API as short-lived functions: our in-process hourly cleanup (ADR 0024/0027) can't run, and Hobby cron jobs run at most once a day. |
| Fly.io, Koyeb | No free plan for new accounts. |
| **Northflank Sandbox** | Always on (no sleeping), no card, 2 services + 2 jobs + 1 database, up to 0.2 vCPU / 512 MB per service (the same size as Render's free service). Support is best effort. |
| **Neon** (Postgres) | Free with no time limit and no card: 1 GB, 100 compute-hours a month, sleeps after 5 idle minutes and wakes in a few hundred ms. Can roll back up to 6 hours. |
| **Upstash** (Redis) | Free: 500K commands a month, 256 MB. We only use Redis for rate limits (2 commands per limited request). |

What the code gives us (main `bebb712`): settings from environment variables; one Docker
image; migrations and the exercise library loaded by one-off compose services; the hourly
account cleanup running inside the API process; `/health` that queries the database; the
per-IP limiter reading the connection's address (ADR 0008 left proxy support for now).

## Decisions

### 1. The API runs on Northflank's free Sandbox (user's choice, after a Vercel check)
Always on, so the app never waits a minute on first open and the hourly cleanup really
runs every hour. One project in region **Asia Southeast (Singapore)**, the closest to
Pakistan (a project's region can't be changed later), with one "combined" service that
builds `backend/Dockerfile` from GitHub.
- ❌ Render free: the one-minute wake-up hits exactly the moment that matters (opening
  the app), and its database expires.
- ❌ Render + a keep-awake ping: pings can be late, and it bends the free plan's purpose.
- ❌ Vercel Hobby: not allowed for a business; no hourly jobs.
- Cost: $0. Non-money: a newer, smaller platform; if it changes its free plan we move.
  Nothing here is Northflank-specific apart from clicks in its dashboard: the same image
  runs anywhere (Render, Cloud Run, a VPS).

### 2. Postgres on Neon, Redis on Upstash, both in Singapore
Data lives apart from the API host, so changing hosts never means moving data. Neon's
project must be created on **Postgres 17**, the same major version as local Docker and
CI, so dumps and restores work in both directions.
- New setting `POSTGRES_SSLMODE` (`prefer` locally, as before; `verify-full` hosted). One
  property, `settings.database_connect_args`, feeds both the app's engine and Alembic's,
  so migrations can't forget it. **Found while building:** given the plain string
  `verify-full`, asyncpg looks for `~/.postgresql/root.crt` like psql does, which no
  server image has, so the first deploy would have failed. `verify-full` therefore uses
  Python's default TLS context: certificate and host name checked against the system's
  trusted certificates.
- The direct (not pooled) Neon endpoint: one long-running process with its own small
  pool. Neon closes idle connections when it sleeps; `pool_pre_ping` replaces them.
  Idle connections don't keep Neon awake (checked against current reports).
- Redis via `REDIS_URL=rediss://…` (TLS). The limiter already fails open if Redis is down.

### 3. Two health checks: `/health/live` for the platform, `/health` for people
**Found while building:** `/health` runs `SELECT 1`. A platform probe every few seconds
would keep Neon awake all month (about 180 compute-hours at the smallest size, past the
free 100), and the database would then be suspended until the next month. New
`GET /health/live` never touches the database and returns `{"status", "version"}`;
Northflank's health checks use it. `/health` (database included) stays for people and
for the deploy check. The hourly cleanup wakes Neon about 5 minutes an hour, roughly
15 compute-hours a month.

### 4. Start = migrate, load the library, run (`backend/start-production.sh`)
The service's command is `sh start-production.sh`: `alembic upgrade head`, then
`python -m lock_in_mode_api.seed` (safe to repeat; about 1.5 s), then `exec uvicorn`.
`set -e`: a failed migration or seed never starts the API. Compose keeps its separate
`migrate`/`seed` services and ignores the script. With one instance, two migrations can
never run at once. Rule from now on: a migration must keep the PREVIOUS code working
(add first, remove in a later release), because the old version keeps serving while the
new one migrates.

### 5. Deploy from CI, only after the tests pass, and prove it landed
Northflank's own "build on every push" is switched off. A `deploy` job in `ci.yml` runs on
pushes to main after the backend job passes: it asks Northflank's API to build that exact
commit, passing the commit id as the `APP_VERSION` build argument, then polls
`/health/live` until it reports that commit, then calls `/health`. 15 minutes without it
fails the job. Skipped until the repository variables exist, so CI stays green before
hosting is set up. A failing test therefore can't reach users, and "deployed" means
"seen running", not "build started".
- CI also builds the image with a test version and checks the start script is inside and
  parses, and that the version reaches the app.

### 6. Real caller IP behind the proxy (`TRUSTED_PROXY_HOPS`)
Behind the platform's proxy every request comes from the proxy, so the per-IP sign-in
limit (ADR 0008) would be shared by every user. New setting `TRUSTED_PROXY_HOPS` (0 locally,
1 hosted): with N hops, the caller is the Nth entry from the END of `X-Forwarded-For`.
Entries before it are typed by the caller, so a script can't dodge the limit by sending a
new fake address each time (Uvicorn's own proxy option with "trust everyone" would take
the first entry, which can be faked). Missing or short header: the connection's address.
To check after the first deploy: 21 quick guest sign-ins with made-up `X-Forwarded-For`
values must still get a 429 (docs/deploy.md).

### 7. Nightly backups, tested, encrypted, kept 30 days (user's choice)
Neon's free plan only rolls back 6 hours: a mistake found the next day couldn't be undone.
`.github/workflows/backup.yml`, every night at 02:17 Pakistan time and on a button:
1. `pg_dump` (custom format, no owners) with the Postgres 17 image.
2. **Restore drill every night:** the dump is restored into a throwaway Postgres 17 and
   checked (schema version present, exercise library not empty). A backup nobody ever
   restored is only a hope.
3. Encrypted with AES-256 (`gpg --symmetric`) using the `BACKUP_PASSPHRASE` secret; only
   the encrypted file leaves the job.
4. Kept as a run artifact for 30 days, then GitHub deletes it.
- The repository is public, so the encryption is the only protection. The passphrase
  lives in GitHub secrets and in his password manager: lose it and the backups are
  useless, leak it and they're readable.
- Off until `BACKUP_ENABLED=true` is set (after the secrets exist).
- GitHub pauses scheduled workflows after 60 days without repository activity.
- ❌ Neon's 6-hour rollback alone: too short.
- ❌ Northflank's own database: its free-tier backup rules aren't documented, and the data
  would move with the host.

## Deletion promise and backups (ADR 0024)
An erased account can still be inside backups for up to 30 days, until they expire. The
privacy policy must say so ("removed from backups within 30 days").
**Known gap, found while building:** restoring a backup brings back accounts erased after
that backup was taken. Accounts still waiting for their date are erased again by the
hourly cleanup, but ones already erased (guests erased at once, accounts past their date)
would come back. Until there's a fix, a restore is a last resort and must be followed by
erasing those accounts by hand. Later: a small `erased_accounts` list (ids and dates only,
kept 30 days like the backups) that the cleanup replays after a restore.

## Settings (new)
`POSTGRES_SSLMODE` (`prefer`) · `TRUSTED_PROXY_HOPS` (0, max 5) · `APP_VERSION` (`dev`).
Hosted values and the full setup: `docs/deploy.md`.

## API
`GET /health/live` → `{"status": "ok", "version": "<commit>"}`. Never uses the database.

## Data
No migration.

## Consequences
- The API is reachable at Northflank's `*.code.run` address; a custom domain can come
  later without code changes.
- Free-tier limits to watch: Neon 100 compute-hours and 5 GB transfer a month; Upstash
  500K commands; Northflank $20 of resources. Each one stops (no surprise bills) rather
  than charging.
- Swagger docs (`/docs`) are public, as the repository already is.
- Later: the `erased_accounts` list for restores; a custom domain; uptime alerts;
  monitoring beyond platform logs; moving the cleanup to a Northflank cron job if the API
  ever runs more than one instance.
