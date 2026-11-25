# 0030 – Supabase and Northflank, all in London

**Date:** 2026-11-25
**Status:** Accepted. Changes the *where* of ADR 0028 (Neon + Northflank in Singapore);
its *how* (start script, health checks, deploy from CI, nightly tested backups, real
caller IP) is unchanged.
**Superseded in part by [ADR 0031](0031-vercel-and-mumbai.md):** the API moved to Vercel and
everything to Mumbai. Supabase, its own CA and the Data API being off still stand.

## Context
Setting up the accounts on 2026-11-25 found three things the free-tier research had not:
1. **Northflank's free plan has one project and offers only two regions**: Europe – West
   (London) and US – Central. Singapore is paid only. The free project already existed, in
   London.
2. **Northflank asks for a card on file** to create a service ("You will not be charged
   for this service"), although its pricing page says no card is needed.
3. Measuring our API (15 simulated users, 45 workouts): a workout is about 27 requests and
   175 ms of CPU, and one active user is about 400 requests, 3 s of CPU and 0.3 MB a month.
   **Neon's limit is hours awake** (100 CU-hours ≈ 400 h at 0.25 CU): our many small queries
   spread through the day would use it up at roughly 30–100 daily users.

Hosts compared again (user's questions): Render free (no card, Singapore, but sleeps after
15 idle minutes and takes about a minute to wake); Vercel Hobby (no card, 1.5–4 s cold
starts, hourly crons now allowed, but non-commercial use only and code changes needed);
Northflank (card, London, always on, no code changes). Databases compared: Neon, Supabase,
Aiven (no region choice on free, may land in North America; powered off when idle), Prisma
Postgres (200K queries a month ≈ 100 active users; 5 usable direct connections);
CockroachDB (not vanilla Postgres, free allowance tied to card-paying accounts), Xata
(managed free tier retired), Render Postgres (expires after 30 days), Firebase (not
Postgres: a rewrite of the whole data layer). Firebase/Firestore was rejected for that.

## Decisions (user's choices)
1. **API on Northflank, project Default, London.** He adds the card himself; nothing else
   about ADR 0028's setup changes.
2. **Postgres on Supabase (free), London (`eu-west-2`).** Real Postgres, so no code changes
   to the data layer; always on and not metered by hours, so activity never uses up the free
   plan. Its limits: 500 MB (about 300 active users for a year), 5 GB egress a month, a pause
   after 7 days without activity, no backups on free (our nightly backup covers that).
   Paid: Pro, $25/month.
   - Connect through the **shared pooler in session mode** (port 5432, user
     `postgres.<project ref>`): the direct host is IPv6 only on free, and transaction mode
     (6543) has no prepared statements, which asyncpg uses.
   - **Data API off** at project creation: Supabase would otherwise put a REST API in front
     of the `public` schema, where our tables live. Our API is the only way in.
3. **Redis on Upstash, London.** Unchanged otherwise.
4. The empty Singapore Neon project and Upstash database are deleted (user agreed).

## Change in code: trust a database's own CA (`POSTGRES_SSL_ROOT_CERT`)
**Found while building:** Supabase signs its database and pooler certificates with its own
CA ("Supabase Root 2021 CA"), which no system trusts. With ADR 0028's verify-full (system
CAs) the API could not connect. Settings gain `POSTGRES_SSL_ROOT_CERT`: the CA's PEM text
(a one-line value with literal `\n` works too, for dashboards that take one line).
- With it, verify-full trusts **only** that CA (still checking the host name): stronger
  than the system list, since nothing else can pass for our database.
- It must be a real certificate, and only works with `POSTGRES_SSLMODE=verify-full`;
  anything else stops the app at start-up instead of silently skipping the check.
- It goes through `settings.database_connect_args`, so the app and Alembic both use it.
- The nightly backup gains the optional secret `BACKUP_DATABASE_CA`: set, `pg_dump` runs
  with `PGSSLMODE=verify-full` and that CA.

Checked: against a local Postgres whose certificate stood in for Supabase's, the right CA
connected (also pasted on one line) with an empty system trust store; another CA was
refused even where the system trusted the server; `require` + a CA and a non-certificate
were refused at start-up; `pg_dump` with the right CA dumped, with another failed.

## Limits and when to pay (estimates from the measurements above)
| Service | Runs out at about | Then |
|---|---|---|
| Supabase | 500 MB ≈ 300 active users for a year | Pro $25/month |
| Upstash | never in practice (only sign-ins and exports) | pay per use |
| Northflank | handles about 15 requests a second | its paid plan at public launch |

## Consequences
- Phone → London adds about 150 ms per request from Pakistan; API ↔ database is local.
- `docs/deploy.md` rewritten for Supabase, Upstash and Northflank in London.
- Later: watch Supabase's database size; keep the API's queries few per request.
