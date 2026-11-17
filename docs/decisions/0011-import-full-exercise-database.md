# 0011 – Import the whole Exercise Database into the seed file

**Date:** 2026-11-18
**Status:** Accepted

## Context
The "Lock In Mode: Exercise Database" sheet has 255 exercises. It marked 40 as
"seed first" so the work could start small. But tailored workouts depend on choice:
every equipment setup, every ability level and every limit needs its own options for
every slot. With only 40 exercises, most users would get the same few moves. So the
whole sheet goes in now.

The sheet holds the facts (category, slot, muscles, equipment, difficulty, ladders),
but not the plain-language steps, cues and common mistake each exercise needs.

## Decisions

### 1. Import all 255, in one go
A one-time script turned each sheet row into the seed format (ADR 0010), and the
missing steps, cues and common mistakes were written for every exercise. The seed
validation (ADR 0009/0010) checks all of it in CI.

### 2. The seed file is the source of truth from now on
Two editable copies would drift apart. After the import, exercises change in
`seed/exercises.yaml` (reviewed in Git), and the sheet is kept as a read-only reference.
The import script isn't kept in the repo, since the sheet isn't either.

### 3. How sheet columns became fields
- **Names** keep the sheet's sentence case ("Push-up", "Dumbbell bench press").
- **Muscles:** Abs, Obliques and Core → `core`; Rear shoulders → `shoulders`;
  Lower back, Upper back and Lats → `back`. Hip flexors, "Legs", "Arms" and "Full body"
  aren't tracked groups and are dropped.
- **Head targets:** each of the sheet's 70 target phrases maps to `MuscleHead` values.
  Pressing moves get `triceps_lateral`, because arms by the sides emphasise the lateral
  head (knowledge base, section 5). The rotator cuff isn't a tracked head, so band
  external rotation targets `delt_rear`.
- **Missing secondary muscles were added** where a target belonged to an unlisted
  group (27 cases, e.g. rows target the rear delt, so `shoulders` became secondary).
- **Equipment:** the sheet's tier becomes the list (Bands → `resistance_bands`, etc.).
  A dumbbell move whose "also needs" is a real bench (bench, incline or adjustable bench)
  also needs `gym`, so home users without a bench don't get it. Band-assisted pull-up
  needs both `pull_up_bar` and `resistance_bands`.
- **Home only:** 12 home tricks, such as chair squat, backpack and table rows, and
  towel leg curls. Gym users never get these.
- **Ladders:** every "harder variant" link is kept as written. All links already fill
  the same slot, and the Step-up fix from ADR 0010 is included.
- **Alternatives:** none. The plan generator swaps exercises within the same movement
  slot. The `exercise_alternatives` table stays for special cases; we'll decide whether
  it's needed when building "this hurts, swap it".

### 4. Mobility moves name the muscle they stretch
The knowledge base's cool-down picks "3 or 4 held stretches for the muscles trained",
so a stretch must say which muscle it stretches (hamstring stretch → `hamstrings`).
Mobility moves may now have a primary muscle, but no head targets, and they never count
towards weekly sets. Cardio still has no muscles at all. This changes one rule in
ADR 0010.

### 5. Coverage is tested
New tests run against the shipped file and fail if an edit breaks a promise:
- Gym users can hit **every head** and fill **every movement slot**, and never get bands
  or home tricks.
- Home users with dumbbells, or with dumbbells, bands and a bar, can hit every head.
- Home users with no equipment miss only the known gaps from the knowledge base:
  brachialis, brachioradialis and forearm extensors, plus no vertical pull.
- Every category has a difficulty-1 exercise for beginners.

## Consequences
- ✅ 209 exercises for gym users, 110 to 187 for home users depending on kit.
- ✅ Content mistakes fail CI instead of reaching users.
- ⚠️ The written steps were produced in bulk; they follow the plain-language rule but
  should be spot-checked, and reviewed by a qualified trainer before launch
  (knowledge base, section 13).
- ⚠️ The no-equipment gaps could be closed with two more home moves (a backpack hammer
  curl and a backpack reverse curl). Not done; they'd be new exercises outside the sheet.
  > Update 2026-11-18: both added (257 exercises). Home users with no equipment, or
  > with only bands, now hit every head; only the vertical pull slot stays empty without kit.
- ⚠️ Demo GIFs/illustrations are still open (`demo_url` empty everywhere).
