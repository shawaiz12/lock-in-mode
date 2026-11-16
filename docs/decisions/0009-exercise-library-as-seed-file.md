# 0009 – Manage the exercise library as a validated seed file in Git (admin panel later)

**Date:** 2026-11-16
**Status:** Accepted

## Context
Phase 2 starts with the exercise library: ~40 hand-written exercises (steps, form cues,
a common mistake, a variant ladder and equipment alternatives). The plan generator,
`GET /exercises` and every workout depend on this content, so it must be correct.

The brief says "managed through an admin panel (Django admin)". Right now one person
writes all the content, and it is all written before launch. We had to decide how the
content gets into the database and who can change it.

ADR 0003 also left two jobs to "the seed script and admin validation":
cycles across several rows (A → B → C → A) are not blocked by the database, and
alternatives are stored one direction at a time.

## Options considered

### A. Django admin (separate small service, same database), as the brief says
- ✅ The most complete free admin panel: search, filters, logins, permissions, change history.
- ✅ "Django" on the CV; Python job posts often ask for it.
- ❌ The same tables described twice (SQLAlchemy for the API, Django for the admin).
  Django models must be `managed = False`, and every Alembic change must be copied
  into them by hand (needs a drift test in CI).
- ❌ Django still creates its own tables (users, sessions, admin log): a second migration
  system on the same database. They would need their own Postgres schema.
- ❌ One more container and CI job, about a day of setup, before any content exists.

### B. SQLAdmin mounted inside the FastAPI app (`/admin`)
- ✅ Reuses our SQLAlchemy models: one source of truth, no drift. No new service.
- ❌ Less polished; editing the variant ladder and alternatives needs custom work.
- ❌ Needs its own admin login, and puts an admin UI on the public API
  (we would switch it off in production).
- ❌ Moves away from the brief and drops "Django" from the CV.

### C. A YAML seed file in the repo, validated in CI, loaded by an idempotent script (chosen)
`backend/src/lock_in_mode_api/seed/exercises.yaml`, checked by Pydantic models, then
upserted ("insert if missing, update if changed") by a command.
- ✅ Cheapest now; no new service, no second ORM.
- ✅ Content is code: every change is a reviewable commit, and Git history is the audit log.
- ✅ The rules ADR 0003 left open (no cycles, references exist, ladders don't merge)
  become plain unit tests that run on every push.
- ✅ Still useful after an admin exists: fresh dev and test databases need the same content.
- ❌ Editing needs Git, so a non-developer can't change content.
- ❌ The brief's admin checkbox moves to later.

## Decision
Option C now. Revisit (most likely add Django admin, option A) when someone other than
the developer needs to edit content, or before launch.

Details:
- **YAML, read with `yaml.safe_load`.** YAML is easier to write and review than JSON for
  multi-line text and allows comments. `safe_load` only builds plain data (dicts, lists,
  strings, numbers); `yaml.load` can build arbitrary Python objects from a file, which is
  a code-execution risk.
- **Validation in two layers.** Each exercise: field types, allowed enum values (category,
  muscle groups, equipment), 3–5 steps, 2–3 cues, one common mistake, no unknown keys
  (catches typos like `harderr:`). The whole library: unique slugs and names, every
  reference points to a real slug, at most one easier version per exercise (mirrors the
  `UNIQUE` on `harder_variant_id`), no cycles, and a harder variant must be in the same
  category with a higher difficulty.
- **The slug is the stable key.** The file never contains UUIDs; the loader looks rows up
  by `slug` (already `UNIQUE`), so the database keeps its own ids across reloads.
- **Alternatives are written once.** The file lists a pair once; the loader stores both
  directions (ADR 0003 expected the admin to do this).
- **The loader never deletes.** An exercise removed from the file stays in the database
  (later, plans and logged sets will point at it); the loader reports it instead.
- **The file ships inside the package**, so the Docker image can seed a database the same
  way locally and on Render.

## Consequences
- ✅ Bad content fails CI before it reaches any database.
- ✅ One source of truth for both the schema (Alembic) and the content (the seed file).
- ⚠️ When an admin panel arrives, the file stops being the source of truth for production
  content. Before that, decide whether the loader keeps updating existing rows in
  production (it would overwrite admin edits) or only inserts new ones.
- ⚠️ The demo source (open-licensed library vs. self-made) is still open; `demo_url`
  stays empty until it is decided.
