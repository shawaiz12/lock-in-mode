# 0031 – The API on Vercel, everything in Mumbai

**Date:** 2026-11-25
**Status:** Accepted. Replaces the *where* of ADR 0030: Vercel instead of Northflank, and
Mumbai instead of London. Supabase (with its own CA, ADR 0030), Upstash, the CI deploy
job, the nightly tested backups and the real-caller-IP rule (ADR 0028) stay.

## Context
- **Northflank couldn't verify the user's card**, and its free plan won't create a service
  without one. The user chose Vercel (Hobby: free, no card).
- **Regions were free again.** London was only chosen because Northflank's free project
  is there. Measured from the user's PC in Pakistan on 2026-11-25 (median of 5 requests):
  Dubai 56 ms, **Mumbai 77 ms**, Frankfurt 149 ms, London 158 ms, US East 235 ms,
  Singapore 277 ms. Supabase, Upstash and Vercel all offer Mumbai (`ap-south-1`, Vercel
  `bom1`); none of the three offers Dubai.
- **Vercel runs the API as a serverless function** (Fluid compute): an instance starts when
  requests come, may serve several at once, is frozen or stopped when quiet, and only runs
  while it answers a request. Nothing runs between requests.

## Decisions
1. **API on Vercel Hobby, region `bom1` (Mumbai).** `backend/app.py` hands Vercel the app
   (`[tool.vercel] entrypoint = "app:app"`); the project's Root Directory is `backend/`.
2. **Supabase in South Asia (Mumbai), Data API off; Upstash in Mumbai.**
3. **The API talks to Supabase through the transaction pooler (port 6543)**, Supabase's
   recommendation for serverless: many short-lived instances share a few real database
   connections. The pooler hands a connection to another client after every transaction,
   so with `POSTGRES_TRANSACTION_POOLER=true`:
   - asyncpg and SQLAlchemy cache no prepared statements, and SQLAlchemy names the few it
     still prepares with a fresh UUID (SQLAlchemy's documented PgBouncer setup);
   - the app keeps no pool of its own (`NullPool`): one fresh connection to the pooler per
     request. A pool inside a frozen instance would only hold stale connections.
   Found while building: without this, 12 users at once through PgBouncer (transaction
   mode, 2 connections, no prepared statements) failed with *prepared statement
   "\_\_asyncpg_stmt_29\_\_" does not exist* and dropped requests. With it, 30 users at once
   (1,830 requests, full workouts) had 0 failures. **CI now runs that check on every push**
   (`scripts/pooler_check.py`, through PgBouncer with 2 connections): 20 users doing the
   journey through the API started from `app.py`, then 10 connections each running 30
   transactions in a row. The second part is what catches SQLAlchemy's statement cache
   left on (10 of 10 failed: *prepared statement ... does not exist*); the unit tests
   pin each setting one by one.
4. **Migrations, the seed, backups and the cleanup use the session pooler (port 5432)**:
   they need one whole session, and they run from GitHub Actions, not on Vercel.
5. **Deploys only from CI.** The Vercel project is created empty and never connected to
   GitHub (Vercel needs no access to the repository), and `vercel.json` also turns off
   Vercel's own deploy per push (`git.deploymentEnabled: false`) in case it ever is: a
   preview deployment would run unreviewed code against the real database. The CI
   `deploy` job, after the tests: `alembic upgrade head` + seed → `vercel deploy --prod
   --env APP_VERSION=<commit>` → waits until `/health/live` reports that commit, then
   `/health`. Migrations stay backwards
   compatible (ADR 0028) because the old version serves while they run.
6. **The hourly account cleanup (ADR 0024) moves to GitHub Actions**
   (`.github/workflows/cleanup.yml`, every hour at :41), running the same code once:
   `python -m lock_in_mode_api.cleanup`. On Vercel the in-process task is off
   (`ACCOUNT_CLEANUP_INTERVAL_SECONDS=0`); anywhere the API runs all the time (Docker,
   another host) it still works as before. Signing in still erases a due account on
   the spot.
7. **`TRUSTED_PROXY_HOPS=1`.** Vercel overwrites `X-Forwarded-For` with the caller's
   address, so the last entry is the real caller.
8. `start-production.sh` and the Dockerfile stay: local Docker uses them, and they keep a
   container host (Render, Northflank, Fly) one setting away.

## Consequences and limits
- **Non-commercial only.** Vercel's Hobby plan is for personal, non-commercial use. Fine
  for building and testing; **before the app earns money (subscriptions, ads), move to
  Vercel Pro ($20/month) or a container host.** Decide that before launch, not after.
- **Free allowance** (Hobby, per month): 1M function invocations, 4 hours of active CPU,
  360 GB-hours of memory. Measured cost of one active user (ADR 0030): ~400 requests and
  ~3 s of CPU a month, so invocations run out first: **about 2,500 monthly active users**.
  Past a limit, Hobby stops serving until the 30 days are up: no surprise bill, but
  downtime.
- **Cold starts:** the first request after a quiet spell starts Python and imports the
  app, so it's slower. To measure once live.
- **Function body limit 4.5 MB** (request or response). Today's biggest response, the data
  export (ADR 0027), is far below it; a user would need years of history to come close.
- GitHub turns scheduled workflows off after 60 days without a commit. The cleanup and the
  backup then stop until switched on again in the Actions tab.
- Untested until live: Vercel's Python runtime itself (how it runs the lifespan, reuses
  instances and keeps the event loop). The first deploy's `/health` and the real-IP
  check (docs/deploy.md §5) are the proof.

## Found going live (2026-11-25)
- **The API ran with sign-in rate limiting off and nobody noticed but the logs.**
  `REDIS_URL` first pointed at the deleted Singapore Upstash, then started with
  `redis://` (Upstash's `redis-cli --tls -u redis://…` line) instead of `rediss://`:
  Upstash hangs up on plain connections. Rate limiting fails open by design (ADR 0008),
  so everything else worked. Now: the API refuses to start with a `redis://` URL to
  another machine (a host with a dot) or a non-Redis URL; `/health` adds
  `"redis": "ok" | "unavailable"` (still 200: the app works without it); the deploy job
  fails unless it's `ok`.
- **The database password leaked into a public log.** The backup job took a connection
  URL with the password inside; the password had a `%`, the URL didn't parse, and
  `pg_dump`'s error quoted that part of it. GitHub hides a secret's exact value only, not
  a piece of it. The log was deleted and the password changed the same hour. Now the
  backup uses the deploy job's settings, the password as `PGPASSWORD` (libpq never prints
  it, checked with a wrong password), verify-full with `POSTGRES_SSL_ROOT_CERT`; the
  secrets `BACKUP_DATABASE_URL` and `BACKUP_DATABASE_CA` are gone, and a test refuses any
  workflow line that puts a secret inside a URL.
- **The first backup dumped fine but couldn't be restored.** `pg_dump` copied the whole
  Supabase database: Supabase's own schemas (auth, storage, vault…), its extensions,
  event triggers and the realtime publication live next to ours, and the throwaway
  Postgres stopped at `extension "supabase_vault" is not available`. The app uses no
  extensions and keeps every table in `public`, so the backup now dumps only `public`
  (`--schema=public --no-publications --no-subscriptions`). Dumping one schema makes
  the restore try `CREATE SCHEMA public`, which every database already has, so the
  restore drops that line (and the schema's comment) from the dump's list first. Tested
  on a fake Supabase-like database before changing the workflow: only `public` came back,
  sequences and foreign keys worked. The restore drill in CI and the manual restore in
  `docs/deploy.md` are the same commands (a test keeps them in step). If the app ever
  needs an extension, the backup must add it (`--extension`).
- Vercel's dashboard *Redeploy* of a CLI deployment drops `--env APP_VERSION`; redeploy
  with CI's *Run workflow*.
- Measured live from Pakistan: warm requests about 100 ms (function and edge both in
  `bom1`); a full guest journey worked end to end and erased cleanly.
