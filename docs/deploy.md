# Putting the API online

Decisions: [ADR 0028](decisions/0028-hosting-the-api.md) (how we deploy, back up and check),
[ADR 0030](decisions/0030-supabase-and-northflank-in-london.md) (Supabase and its own
certificate) and [ADR 0031](decisions/0031-vercel-and-mumbai.md) (where: Vercel,
Supabase and Upstash, all in Mumbai). Everything is free and needs no card. Do the parts
in order: each gives you values the next needs. Keep the values in your password manager
(never in the repo or a chat).

```
phone ──https──▶ Vercel (API, Mumbai) ──TLS, Supabase CA, port 6543──▶ Supabase (Postgres, Mumbai)
                                      └──TLS──────────────────────────▶ Upstash (Redis, Mumbai)
GitHub Actions, on main:  tests ─▶ migrate + seed (port 5432) ─▶ vercel deploy ─▶ live check
GitHub Actions, hourly:   account cleanup (port 5432)
GitHub Actions, nightly:  pg_dump ─▶ test restore ─▶ encrypt ─▶ keep 30 days
```

The Vercel project is **not connected to GitHub**: only the CI deploy job deploys, with
Vercel's command-line tool and a token. Vercel never reads the repository on its own.

## 1. Supabase: the database
1. supabase.com → **New project**:
   - Name `lock-in-mode`, region **South Asia (Mumbai)** (`ap-south-1`).
   - **Database password**: *Generate a password*, copy it into your password manager.
   - **Enable Data API → OFF.** Our API is the only way in; Supabase's automatic REST
     API over our tables must not exist (ADR 0030).
2. **Connect** (top bar) → **Direct → Connection string**. Two of the methods matter:
   - **Transaction pooler** (port **6543**): what the API on Vercel uses.
   - **Session pooler** (port **5432**): migrations, the seed, backups, the cleanup job.
   (*Direct connection* is IPv6 only on the free plan: GitHub's machines can't reach it.)
   Both look like
   ```
   postgresql://postgres.abcdefghijklmnop:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
   ```
   | Setting | From the example |
   |---|---|
   | `POSTGRES_USER` | `postgres.abcdefghijklmnop` (with the dot and the project ref) |
   | `POSTGRES_PASSWORD` | the password from step 1 |
   | `POSTGRES_HOST` | `aws-0-ap-south-1.pooler.supabase.com` |
   | `POSTGRES_DB` | `postgres` |
   The **session pooler** string (port 5432), with the real password in place of
   `[YOUR-PASSWORD]` and **no** `?sslmode=…`, is the backup job's `BACKUP_DATABASE_URL`.
3. **Database → Settings → SSL configuration → Download certificate**. Open
   `prod-ca-2021.crt` in a text editor: `-----BEGIN CERTIFICATE----- … -----END
   CERTIFICATE-----`. That whole text is `POSTGRES_SSL_ROOT_CERT` (and the backup's
   `BACKUP_DATABASE_CA`). It's public, not a secret.
4. Same page: switch **Enforce SSL on incoming connections** on.

## 2. Upstash: Redis
1. upstash.com → **Create Database**: name `lock-in-mode`, primary region
   **Mumbai, India (ap-south-1)**, Free.
2. The database → **Connect** → copy the URL that starts with **`rediss://`** (two s's =
   TLS). That's `REDIS_URL`.

## 3. Vercel: the API
1. vercel.com (Hobby) → **Add New → Project** → at the bottom, **Create an empty project**.
   Don't import the repository (that would connect GitHub and deploy on every push).
2. Project → Settings:
   - General → **Project Name** `lock-in-mode-api`.
   - Build and Deployment → **Framework Preset: FastAPI**, **Root Directory: `backend`**
     (Save each). Leave the commands alone.
   - Domains → **Edit** the `….vercel.app` domain to `lock-in-mode-api.vercel.app`.
3. **Environment Variables**, for Production. The secrets as type **Secret**, the rest as
   **Config** (pasting several `KEY=value` lines into the Key box adds them all):
   ```
   POSTGRES_USER=postgres.<project ref>          (part 1)
   POSTGRES_PASSWORD=...                         (part 1)       secret
   POSTGRES_HOST=aws-0-ap-south-1.pooler.supabase.com            (yours from part 1)
   POSTGRES_PORT=6543                            transaction pooler
   POSTGRES_DB=postgres
   POSTGRES_TRANSACTION_POOLER=true
   POSTGRES_SSLMODE=verify-full
   POSTGRES_SSL_ROOT_CERT=-----BEGIN CERTIFICATE-----...         (part 1.3, the whole text)
   REDIS_URL=rediss://...                        (part 2)       secret
   JWT_SECRET=...                                (a NEW one)    secret
   TRUSTED_PROXY_HOPS=1
   ACCOUNT_CLEANUP_INTERVAL_SECONDS=0            GitHub Actions does it hourly
   ```
   `JWT_SECRET`: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
   If a field won't take several lines, paste the certificate on one line with `\n`
   between its lines (the API accepts both).
4. Nothing deploys yet: the first deploy is CI's (part 4), after the migrations.
   `API_URL` is `https://lock-in-mode-api.vercel.app` (no `/` at the end). After it:
   ```bash
   curl https://lock-in-mode-api.vercel.app/health/live   # {"status":"ok","version":"<commit>"}
   curl https://lock-in-mode-api.vercel.app/health        # {"status":"ok","database":"ok"}
   ```
   If `/health` fails, the deployment's logs (Vercel → Deployments → the deployment → Logs) say why:
   - `certificate verify failed`: `POSTGRES_SSL_ROOT_CERT` isn't Supabase's, or is cut off.
   - `password authentication failed`: the user must be `postgres.<project ref>`.
   - `prepared statement ... does not exist`: `POSTGRES_TRANSACTION_POOLER=true` is missing.
5. Project → Settings → **Functions**: the region shows **Mumbai (bom1)** (from
   `backend/vercel.json`).

### The ids and token for CI
- Project → Settings → General: **Project ID** (`prj_…`) → `VERCEL_PROJECT_ID`.
- Team (top left) → Settings → General: **Team ID** (`team_…`; Hobby accounts are a
  one-person team) → `VERCEL_ORG_ID`.
- Account → Settings → **Tokens → Create**: name `github-deploy`, scope your account,
  an expiry date you'll remember. Copy it once → `VERCEL_TOKEN`.

## 4. GitHub: connect CI
Repository → Settings → Secrets and variables → **Actions**.

| Kind | Name | Value |
|---|---|---|
| Secret | `VERCEL_TOKEN` | the token above |
| Variable | `VERCEL_ORG_ID` | `team_…` |
| Variable | `VERCEL_PROJECT_ID` | `prj_…` |
| Variable | `API_URL` | e.g. `https://lock-in-mode-api.vercel.app` |
| Variable | `POSTGRES_HOST` | `aws-0-ap-south-1.pooler.supabase.com` |
| Variable | `POSTGRES_USER` | `postgres.<project ref>` |
| Secret | `POSTGRES_PASSWORD` | the database password |
| Variable | `POSTGRES_SSL_ROOT_CERT` | the certificate text |
| Secret | `BACKUP_DATABASE_URL` | the session pooler string with the password, no `?sslmode` |
| Secret | `BACKUP_DATABASE_CA` | the same certificate text |
| Secret | `BACKUP_PASSPHRASE` | a new long random one, also in your password manager |
| Variable | `BACKUP_ENABLED` | `true` (only after the backup secrets exist) |

Setting `VERCEL_PROJECT_ID` switches on the deploy job and the hourly cleanup.

Test the deploy: Actions → **CI → Run workflow** (branch `main`). `Deploy API` shows the
migrations, `Exercise library: 257 in the seed file`, the Vercel URL, then
`Live: {"status":"ok","version":"<this commit>"}` and the `/health` reply.

Test the cleanup: Actions → **Account cleanup → Run workflow**. It ends with
`Account cleanup: erased 0 account(s) and 0 lost guest(s)`.

Test the backup: Actions → **Database backup → Run workflow**. The log shows
`Restored: schema <revision>, 257 exercises, N users`; the run has one artifact.

## 5. Check the real-IP setting
Sign-ins are limited to 20 a minute per caller, and made-up `X-Forwarded-For` values must
not get around it (these calls create nothing: Google sign-in is off):
```bash
for i in $(seq 1 21); do
  curl -s -o /dev/null -w "%{http_code} " -X POST "$API_URL/api/v1/auth/google" \
    -H "Content-Type: application/json" -H "X-Forwarded-For: 10.0.0.$i" \
    -d '{"id_token":"not-a-real-token"}'
done; echo
```
Expected: 20 non-429 codes, then **429**. Never 429: tell Claude.

## Free-plan limits to watch (ADR 0031)
- **Vercel Hobby**: non-commercial use only: **move to Pro ($20/month) or a container
  host before the app earns money.** 1M invocations, 4 h of active CPU and 360 GB-h of
  memory a month (Usage tab): about 2,500 monthly active users. Past a limit it stops
  serving until the month is over.
- **Supabase**: 500 MB database (Database → Reports); past it the database turns
  read-only. Free projects pause after a week without activity: restore from the
  dashboard.
- **Upstash**: 500K commands a month (only sign-ins and exports use it).
- **GitHub**: scheduled workflows (cleanup, backup) switch off after 60 days without a
  commit. Switch them back on in the Actions tab.

## Every day after this
- Push or merge to `main` → tests → migrate → deploy → live check. A red `Deploy API` job
  means the new version isn't serving; the previous one still is (Vercel → Deployments).
- Migrations run before the new code goes live, while the old version still serves:
  keep them backwards-compatible (add first, remove in a later release).
- Never deploy from your laptop (`vercel` in a terminal): only CI deploys, after the tests.

## Restoring a backup (last resort)
1. Actions → Database backup → a run → download the artifact.
2. Decrypt: `gpg --decrypt --output lockin.dump lockin-<date>.dump.gpg` (asks for
   `BACKUP_PASSPHRASE`).
3. Restore into a **new, empty** Postgres (a second Supabase project, or local Docker),
   never straight over the live one:
   ```bash
   docker run --rm -v "$PWD:/in" postgres:17-alpine \
     pg_restore --no-owner --no-privileges --exit-on-error \
     --dbname="<that database's connection string>" /in/lockin.dump
   ```
4. Check it, then point the API's `POSTGRES_*` (Vercel and GitHub) at it.
5. **Accounts erased after the backup was taken come back** (ADR 0028, known gap): erase
   them again before opening the API to users.
