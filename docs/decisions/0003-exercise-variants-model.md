# 0003 – Model exercise variants with a self-referencing key and a join table

- **Date:** 2026-11-11
- **Status:** Accepted

## Context
Every exercise can have an easier and a harder version (knee push-up → push-up →
decline push-up), so the plan generator can make workouts easier or harder based on
user feedback. Exercises also need equipment alternatives (e.g. no pull-up bar →
use a resistance-band row instead). The brief's first-draft data model needed review
before the tables were created.

## Options considered

### 1. Separate `exercise_variants` table (from the brief)
Columns: `exercise_id`, `easier_id`, `harder_id`, `alternative_ids[]`.
- ❌ **Arrays can't have foreign keys.** Postgres cannot check that the IDs inside
  `alternative_ids[]` point to real exercises. Deleting an exercise leaves dangling
  IDs, and the app breaks when it follows them.
- ❌ **The same fact is stored twice.** "Push-up → harder → decline push-up" and
  "decline push-up → easier → push-up" describe one relationship. Sooner or later
  one gets updated and the other doesn't, and they disagree.

### 2. Self-referencing key + join table (chosen)
- `exercises.harder_variant_id` → `exercises.id`
  - `UNIQUE`: each exercise has at most one easier version, so a ladder can't split.
  - `ON DELETE SET NULL`: deleting a variant unlinks it instead of deleting its neighbour.
  - `CHECK (harder_variant_id <> id)`: an exercise can't be its own harder version,
    which would make the plan generator loop forever.
- `exercise_alternatives(exercise_id, alternative_id)`
  - Both columns are real foreign keys with `ON DELETE CASCADE`: a link means nothing
    once either exercise is gone.
  - Composite primary key: the same pair can't be added twice.
  - `CHECK (exercise_id <> alternative_id)`: an exercise isn't its own alternative.

## Decision
Use option 2.

General rule adopted for the project:
**arrays for lists of simple values** (muscle groups, equipment),
**join tables for lists of references to other rows** (alternatives).

## Consequences
- ✅ The database guarantees every link points to a real exercise.
- ✅ Each relationship is stored exactly once (single source of truth).
- ✅ Delete behaviour is chosen per relationship (SET NULL vs CASCADE).
- ⚠️ Finding the *easier* version needs a reverse lookup
  (`WHERE harder_variant_id = :id`) instead of reading a column. This is a cheap query
  on an indexed column; the unique constraint already creates that index.
- ⚠️ Alternatives are one-directional. If A and B are alternatives for each other,
  both pairs must be added (the admin panel can do this automatically later).
- ⚠️ Cycles across several rows (A → B → C → A) are not blocked by the database.
  The seed script and admin validation must prevent them.