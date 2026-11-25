# Putting the API online

Decisions: [ADR 0028](decisions/0028-hosting-the-api.md) (how we deploy, back up and check)
and [ADR 0030](decisions/0030-supabase-and-northflank-in-london.md) (where: Supabase,
Upstash and Northflank, all in London). Everything is free; Northflank needs a card on file
but says it doesn't charge the free plan. Do the parts in order: each gives you values the
next needs. Keep the values in your password manager (never in the repo or a chat).

```
phone ──https──▶ Northflank (API, London) ──TLS, Supabase CA──▶ Supabase (Postgres, London)
                                           └──TLS────────────────▶ Upstash (Redis, London)
GitHub Actions: tests ─▶ deploy job ─▶ Northflank builds that commit ─▶ live check
GitHub Actions (nightly): pg_dump ─▶ test restore ─▶ encrypt ─▶ keep 30 days
```

## 1. Supabase: the database
1. Sign in at supabase.com (GitHub is fine). **New project**:
   - Name `lock-in-mode`, region **Europe West (London)** (`eu-west-2`).
   - **Database password**: click *Generate a password*, copy it into your password manager
     before you leave the page.
   - Security: **Enable Data API → OFF.** Our API is the only way in; Supabase's automatic
     REST API over our tables must not exist (ADR 0030). Auto RLS may stay as offered.
2. When it's ready: **Connect** (top bar) → **Session pooler** (port **5432**). Not *Direct*
   (IPv6 only on the free plan) and not *Transaction pooler* (port 6543, no prepared
   statements). It looks like:
   ```
   postgresql://postgres.abcdefghijklmnop:[YOUR-PASSWORD]@aws-0-eu-west-2.pooler.supabase.com:5432/postgres
   ```
   | Setting | From the example |
   |---|---|
   | `POSTGRES_USER` | `postgres.abcdefghijklmnop` (with the dot and the project ref) |
   | `POSTGRES_PASSWORD` | the password from step 1 |
   | `POSTGRES_HOST` | `aws-0-eu-west-2.pooler.supabase.com` |
   | `POSTGRES_PORT` | `5432` |
   | `POSTGRES_DB` | `postgres` |
   The whole string, with the real password in place of `[YOUR-PASSWORD]` and **no**
   `?sslmode=…` at the end, is the backup job's `BACKUP_DATABASE_URL`.
3. **Project Settings → Database → SSL Configuration → Download certificate**. Open the
   file in a text editor: it's `-----BEGIN CERTIFICATE----- … -----END CERTIFICATE-----`.
   That whole text is `POSTGRES_SSL_ROOT_CERT` (and the backup's `BACKUP_DATABASE_CA`).
   It's a public certificate, not a secret, but keep it with the rest.
4. Leave **Enforce SSL** on.

## 2. Upstash: Redis
1. upstash.com → **Create Database**: name `lock-in-mode`, Regional, region
   **eu-west-2 (London)** (or the closest Europe region it offers), TLS on, Free.
2. Copy the URL that starts with **`rediss://`** (two s's = TLS). That's `REDIS_URL`.

## 3. Northflank: the API (free project = London)
The free plan has one project; ours is **Default**, in **Europe – West (London)**.
1. Team → **Billing**: add a card (needed to create a service; the free plan isn't charged).
2. Team → **Integrations → Git**: link **GitHub** (`shawaiz12`), with access to
   `shawaiz12/lock-in-mode`.
3. Project **Default** → **Create service → Combined service**. Name `api`.
   - Repository `shawaiz12/lock-in-mode`, branch `main`.
   - Build: **Dockerfile**, build context `/backend`, Dockerfile `/backend/Dockerfile`.
   - Networking: port **8000**, HTTP, **Publicly expose** on.
   - Resources: the free size, 1 instance.
   - Advanced → **Custom command**: `sh start-production.sh`
     (migrate, load the exercise library, start; the image's default command only starts).
4. **Environment** (mark the secrets as secret):
   ```
   POSTGRES_USER=postgres.<project ref>     (step 1)
   POSTGRES_PASSWORD=...                    (step 1)            secret
   POSTGRES_HOST=aws-0-eu-west-2.pooler.supabase.com            (yours from step 1)
   POSTGRES_PORT=5432
   POSTGRES_DB=postgres
   POSTGRES_SSLMODE=verify-full
   POSTGRES_SSL_ROOT_CERT=-----BEGIN CERTIFICATE-----...        (step 1.3, the whole text)
   REDIS_URL=rediss://...                   (step 2)            secret
   JWT_SECRET=...                           (a NEW one)         secret
   TRUSTED_PROXY_HOPS=1
   ```
   `JWT_SECRET`: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
   If a field won't take several lines, paste the certificate on one line with `\n`
   between its lines (the API accepts both).
5. **Health checks**: liveness AND readiness, HTTP, port 8000, path **`/health/live`**
   (never `/health`: it queries the database every few seconds for nothing).
6. **Build options**: turn OFF automatic builds on new commits. GitHub Actions deploys,
   after the tests pass.
7. Let the first build and deploy finish. The container log shows the migrations,
   `Exercise library: 257 in the seed file`, then uvicorn.
   - `certificate verify failed`: `POSTGRES_SSL_ROOT_CERT` isn't Supabase's certificate,
     or is cut off.
   - `Network is unreachable` / a hang: `POSTGRES_HOST` is the *Direct* host; use the
     *Session pooler* host.
   - `password authentication failed`: the user must be `postgres.<project ref>`.
8. **Ports & DNS**: copy the public address, e.g. `https://p01--api--abcd1234.code.run`.
   That's `API_URL` (no `/` at the end). Check:
   ```bash
   curl https://p01--api--abcd1234.code.run/health/live   # {"status":"ok","version":"dev"}
   curl https://p01--api--abcd1234.code.run/health        # {"status":"ok","database":"ok"}
   ```

### The token for CI
Team → **API tokens → Create**, with permission to read and update the project's
services (Project → Services → General). Copy it once. Note the **project id**
(`default`) and **service id** (`api`).

## 4. GitHub: connect CI
Repository → Settings → Secrets and variables → **Actions**.

| Kind | Name | Value |
|---|---|---|
| Secret | `NORTHFLANK_API_TOKEN` | the token above |
| Variable | `NORTHFLANK_PROJECT_ID` | `default` |
| Variable | `NORTHFLANK_SERVICE_ID` | `api` |
| Variable | `API_URL` | e.g. `https://p01--api--abcd1234.code.run` |
| Secret | `BACKUP_DATABASE_URL` | the session pooler string with the password, no `?sslmode` |
| Secret | `BACKUP_DATABASE_CA` | the same certificate text as `POSTGRES_SSL_ROOT_CERT` |
| Secret | `BACKUP_PASSPHRASE` | a new long random one, also in your password manager |
| Variable | `BACKUP_ENABLED` | `true` (only after the backup secrets exist) |

Test the deploy: Actions → **CI → Run workflow** (branch `main`). `Deploy API` ends with
`Live: {"status":"ok","version":"<this commit>"}` and the `/health` reply.

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
Expected: 20 non-429 codes, then **429**. Never 429: tell Claude (more than one proxy hop).

## Free-plan limits to watch (ADR 0030)
- **Supabase**: 500 MB database (Database → Reports). Past it the database becomes
  read-only. Projects pause after 7 days without activity: restore from the dashboard.
- **Upstash**: 500K commands a month (only sign-ins and exports use it).
- **Northflank**: the free plan's resources; watch Billing for anything unexpected.

## Every day after this
- Push or merge to `main` → tests → deploy → live check. A red `Deploy API` job means the
  new version isn't serving; the previous one may still be (Northflank logs).
- Migrations run when the new version starts: keep them backwards-compatible (add first,
  remove in a later release).

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
4. Check it, then point the API's `POSTGRES_*` at it.
5. **Accounts erased after the backup was taken come back** (ADR 0028, known gap): erase
   them again before opening the API to users.
