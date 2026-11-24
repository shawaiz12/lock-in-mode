# Putting the API online

The decisions are in [ADR 0028](decisions/0028-hosting-the-api.md). Everything here is
free and needs no card. Do the parts in order: each one gives you values the next needs.
Keep the values in your password manager as you go (never in the repo).

```
phone ──https──▶ Northflank (API, Singapore) ──TLS──▶ Neon (Postgres 17, Singapore)
                                              └─TLS──▶ Upstash (Redis, Singapore)
GitHub Actions: tests ─▶ deploy job ─▶ Northflank builds that commit ─▶ live check
GitHub Actions (nightly): pg_dump ─▶ test restore ─▶ encrypt ─▶ keep 30 days
```

## 1. Neon: the database
1. Sign up at neon.com (GitHub sign-in is fine). Create a project:
   - Name `lock-in-mode`, **Postgres version 17** (same as local Docker; backups need it),
     region **AWS Asia Pacific (Singapore)**.
2. On the project dashboard, **Connect**. Switch **Connection pooling OFF** (we want the
   direct address: its host has no `-pooler` in it). You'll see a string like:
   ```
   postgresql://neondb_owner:AbC123xyz@ep-cool-name-a1b2c3.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```
   Its parts are the API's settings:
   | Setting | From the example |
   |---|---|
   | `POSTGRES_USER` | `neondb_owner` |
   | `POSTGRES_PASSWORD` | `AbC123xyz` |
   | `POSTGRES_HOST` | `ep-cool-name-a1b2c3.ap-southeast-1.aws.neon.tech` |
   | `POSTGRES_DB` | `neondb` |
   Save the whole string too: it's the backup job's `BACKUP_DATABASE_URL`.

## 2. Upstash: Redis
1. Sign up at upstash.com. **Create Database**: name `lock-in-mode`, type Regional, region
   **ap-southeast-1 (Singapore)**, TLS on, Free plan.
2. On the database page, copy the Redis URL that starts with `rediss://` (two s's = TLS):
   ```
   rediss://default:XyZ789@grand-owl-12345.upstash.io:6379
   ```
   That's `REDIS_URL`.

## 3. Merge the hosting branch first
Northflank builds the newest `main` as soon as you create the service, and the start
script only exists from this stage on. So merge `feat/hosting` into `main` before step 4.
(CI's deploy job is skipped until step 5, so nothing breaks.)

## 4. Northflank: the API
1. Sign up at northflank.com with GitHub, and allow it to read `shawaiz12/lock-in-mode`.
2. **Create project**: name `lock-in-mode`, Northflank Cloud, region **Asia - Southeast**,
   plan **Developer Sandbox**. (The region can't be changed later.)
3. In the project: **Create new → Service → Combined service**. Name `api`.
   - Repository `shawaiz12/lock-in-mode`, branch `main`.
   - Build type **Dockerfile**. Dockerfile location `/backend/Dockerfile`, build context
     `/backend`.
   - Networking: port **8000**, protocol HTTP, **Publicly expose** on.
   - Resources: the free plan (`nf-compute-20`, 0.2 vCPU / 512 MB), 1 instance.
   - Advanced → **Custom command**: `sh start-production.sh`
     (migrate, load the exercise library, start; the image's default command only starts).
4. **Environment** (runtime variables; mark the secret ones as secret):
   ```
   POSTGRES_USER=...            (step 1)
   POSTGRES_PASSWORD=...        (step 1)
   POSTGRES_HOST=...            (step 1)
   POSTGRES_DB=neondb
   POSTGRES_SSLMODE=verify-full
   REDIS_URL=rediss://...       (step 2)
   JWT_SECRET=...               (a NEW one, never your local one)
   TRUSTED_PROXY_HOPS=1
   ```
   Make `JWT_SECRET` with: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
5. **Health checks**: add a liveness AND a readiness check, HTTP, port 8000, path
   **`/health/live`**. Never `/health` here: it queries the database, and a check every few
   seconds would keep Neon awake and use up its free hours (ADR 0028).
6. **Build options**: turn OFF automatic builds on new commits ("CI" / "build on push").
   GitHub Actions decides when to deploy, after the tests pass.
7. Let the first build and deploy finish (logs: Builds, then Containers). The container log
   should show the migrations, `Exercise library: 257 in the seed file`, then uvicorn.
8. Copy the public address from the service's **Ports & DNS**: something like
   `https://p01--api--abcd1234.code.run`. That's `API_URL` (no `/` at the end).
9. Check it:
   ```bash
   curl https://p01--api--abcd1234.code.run/health/live   # {"status":"ok","version":"dev"}
   curl https://p01--api--abcd1234.code.run/health        # {"status":"ok","database":"ok"}
   ```
   (`dev`: this first build didn't come from CI. From now on it shows the commit.)

### The token for CI
Team/account settings → **API → Tokens → Create**. Give it a role that may update the
project's services (Project → Services → General → Update) and read them. Copy the token
once; Northflank won't show it again. Also note the **project id** and **service id**
(the service page's URL and its "Copy ID" buttons, e.g. `lock-in-mode` and `api`).

## 5. GitHub: connect CI
Repository → Settings → Secrets and variables → **Actions**.

| Kind | Name | Value |
|---|---|---|
| Secret | `NORTHFLANK_API_TOKEN` | the token above |
| Variable | `NORTHFLANK_PROJECT_ID` | e.g. `lock-in-mode` |
| Variable | `NORTHFLANK_SERVICE_ID` | e.g. `api` |
| Variable | `API_URL` | e.g. `https://p01--api--abcd1234.code.run` |
| Secret | `BACKUP_DATABASE_URL` | the whole Neon string from step 1 |
| Secret | `BACKUP_PASSPHRASE` | a new long random one (same command as `JWT_SECRET`), also in your password manager |
| Variable | `BACKUP_ENABLED` | `true` (only after the two backup secrets exist) |

Test the deploy: Actions → **CI → Run workflow** (branch `main`). The `Deploy API` job
should end with `Live: {"status":"ok","version":"<this commit>"}` and the `/health` reply.

Test the backup: Actions → **Database backup → Run workflow**. The log shows
`Restored: schema <revision>, 257 exercises, N users`, and the run has one artifact
`lockin-<date>.dump.gpg`.

## 6. Check the real-IP setting
Sign-ins are limited to 20 a minute per caller. Made-up `X-Forwarded-For` values must not
get around it (they create no accounts: Google sign-in is off, so each call just fails):
```bash
for i in $(seq 1 21); do
  curl -s -o /dev/null -w "%{http_code} " -X POST "$API_URL/api/v1/auth/google" \
    -H "Content-Type: application/json" -H "X-Forwarded-For: 10.0.0.$i" \
    -d '{"id_token":"not-a-real-token"}'
done; echo
```
Expected: 20 non-429 codes, then **429**. If you never see 429, tell Claude (the proxy adds
more than one hop). Wait a minute after, or your own sign-ins are blocked for that minute.

## Every day after this
- Push or merge to `main` → tests → deploy → live check. A red `Deploy API` job means the
  new version isn't serving; the previous one may still be (check Northflank's logs).
- Migrations run when the new version starts. Keep them backwards-compatible: the old
  version serves until the new one is up (add columns first, remove them in a later
  release).
- Logs: Northflank → service → Containers / Logs.

## Restoring a backup (last resort)
1. Actions → Database backup → a run → download the artifact (a zip with the `.gpg` file).
2. Decrypt (Linux PC, or Git Bash on Windows):
   ```bash
   gpg --decrypt --output lockin.dump lockin-<date>.dump.gpg   # asks for BACKUP_PASSPHRASE
   ```
3. In Neon, create a **new branch** (or a new project) to restore into, never straight over
   the live database. Restore with the Postgres 17 tools:
   ```bash
   docker run --rm -v "$PWD:/in" postgres:17-alpine \
     pg_restore --no-owner --no-privileges --exit-on-error \
     --dbname="<that branch's connection string>" /in/lockin.dump
   ```
4. Check it, then point the API's `POSTGRES_*` at it.
5. **Accounts erased after the backup was taken come back** (ADR 0028, known gap): erase
   them again before opening the API to users.
