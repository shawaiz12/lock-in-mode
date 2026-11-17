# 0010 – Exercise model v2: slots, muscles, heads, equipment and safety fields

**Date:** 2026-11-17
**Status:** Accepted

## Context
The exercise library now has a source of truth outside the code: the
"Lock In Mode: Exercise Database" sheet (255 exercises, 40 marked to seed first) and the
"Lock In Mode: Training Knowledge Base" doc (the plan generator's rules). Both live in
this project's Claude workspace.

The rules need facts the `exercises` table can't hold yet:
- Templates are lists of **movement slots** ("horizontal push"), not exercises.
- Weekly volume counts sets per **muscle group**: 1 for the primary muscle, 0.5 for each
  secondary. Our `muscle_groups` list had 8 coarse groups (`arms`, `legs`, `full_body`)
  and no primary/secondary split.
- **Every head of a trained muscle must be hit** (all three shoulder heads, both biceps
  heads, every back muscle). The engine needs to know which heads an exercise emphasises.
- Limits and the low-intensity / women-at-home filters need **impact** and
  **not-suitable-for**. Exercise choice prefers higher **effectiveness**. Ordering puts
  **compound** before **isolation** moves.
- Equipment: the sheet has one tier per exercise (None / Bands / Dumbbells / Pull-up bar /
  Gym) plus free-text "also needs".

## Decisions

### 1. Head targets: structured tags (chosen) vs free text
A fixed `MuscleHead` list (33 heads) and a `targets` list on each exercise. Each head
maps to one muscle group (`HEAD_GROUP`).
- ✅ The engine can check coverage ("no `triceps_long` today → add an overhead extension").
- ✅ The seed file can check consistency: every target must belong to the primary or a
  secondary muscle, so the set count and the head check never disagree.
- ❌ Free text (the sheet's "Quads: vastus muscles; glute max") was rejected: readable,
  but no program can enforce the rule with it.

### 2. Equipment: a list of required kit (chosen) vs one tier
`equipment` lists everything an exercise needs from: `dumbbells`, `resistance_bands`,
`pull_up_bar`, `gym` (anything only a gym has: machines, cables, barbells, benches;
the exact item is in `also_needs`). An exercise is available when the user has every item.
- Home users own any mix of the first three.
- Gym users have `dumbbells`, `pull_up_bar` and `gym`, **never bands**: nobody trains
  with bands in a gym, so band exercises go only to home users who own bands.
- `home_only: true` marks home tricks (loaded backpack row, table row, chair squat).
  Gym users never get them because the gym has a proper version.
- Household items (chair, table, backpack, step) are assumed available at home and are
  only shown to the user through `also_needs`.
- ✅ Handles combinations (band-assisted pull-up needs a bar *and* a band) and hides
  dumbbell bench press from a home user with dumbbells but no bench.
- ❌ A single tier was rejected: it can't say "needs two things".
- The old values `barbell`, `bench`, `cable_machine`, `kettlebell` are removed (no rows
  used them).

### 3. Variant ladders
- A harder variant must fill the **same movement slot** (true for every link in the sheet;
  it also implies the same category).
- Its difficulty must be the **same or higher**. Difficulty only goes 1–5 while some
  ladders have 7 rungs, so neighbours can share a number (18 links in the sheet do).
  This replaces ADR 0009's "strictly higher".
- Because equal difficulties are allowed, difficulty can no longer rule out loops, so the
  loop check is now the real guard.
- Sheet fix: Step-up difficulty 2 → 3 (it followed Walking lunge, difficulty 3).
- When only part of the sheet is seeded, a link to an exercise that isn't in the file
  yet points to the next rung that is (push-up → ~~close-grip~~ → decline push-up).

### 4. New and changed columns on `exercises`
| Column | Type | Notes |
|---|---|---|
| `movement_slot` | enum (28 slots) | required |
| `exercise_type` | compound / isolation / cardio / mobility | required |
| `primary_muscle` | enum (13 groups), nullable | NULL only for cardio and mobility |
| `secondary_muscles` | text[] | replaces `muscle_groups` |
| `targets` | text[] of heads | empty only for cardio and mobility |
| `also_needs` | varchar(100) | plain words shown to the user |
| `home_only` | bool, default false | |
| `effectiveness` | smallint 1–5, nullable | `CHECK`; NULL only for mobility |
| `impact` | none / low / medium / high, default none | |
| `not_suitable_for` | text[] of body limits | |

> Changed by ADR 0011: mobility moves name the muscle they stretch (cardio stays NULL).

`muscle_groups` is dropped (no rows anywhere used it). Rules that need more than one
column (for example "cardio has no primary muscle") are checked by the seed file's
validation, not by the database.

## Consequences
- ✅ The plan generator can be written straight from the knowledge base's rules.
- ✅ Wrong data (a biceps head on a push-up, a band exercise marked for the gym, a ladder
  that goes down) fails CI before it reaches a database.
- ⚠️ Lists stored as arrays can't have foreign keys or enum checks in Postgres; the seed
  validation is the guard (same trade-off as ADR 0003's arrays).
- ⚠️ Not decided here (profile side, next ADR): five goals (adds build muscle), session
  lengths up to 90 min and "no limit", the push-pull-legs shoulder question, and the
  first-workout ability test.
