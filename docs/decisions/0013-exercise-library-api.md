# 0013 – Exercise library API: pages, a data saver, "for me" and cautions

**Date:** 2026-11-19
**Status:** Accepted

## Context
The app needs to show the exercise library (257 exercises, ADR 0011): a browse screen,
an exercise screen with steps and form cues, and the easier / harder / alternative moves
for swaps. The brief asks for pagination on every list and an app that is light on
mobile data. The library list is about 73 KB of JSON (about 14 KB per page of 50), and it
rarely changes.

## Decisions

### 1. Pages: page number + page size (chosen) vs cursor vs no paging
`GET /exercises?page=2&page_size=50` (default 50, max 100). Responses include `total`.
- ✅ Simple to use and to explain. The library is fixed and small, so the usual weakness
  of page numbers (rows shifting while you scroll) doesn't apply.
- Sorted by name, then id. The id breaks ties so two exercises with the same name can
  never appear on two pages, or on none.
- ❌ Cursor pages were rejected: they're built for big feeds that change while you read
  them (a social feed). Overkill here.
- ❌ No paging was rejected: the brief asks for paging on every list, and it would break
  as the library grows.

### 2. Data saver: ETag + 304 Not Modified
Every list and detail response carries an `ETag`, a fingerprint of its body. The app
sends it back in `If-None-Match`. If nothing changed, the answer is **304 with an empty
body** and the app reuses its saved copy.
- ✅ After the first download, re-checking costs almost no data, which matters for users
  on mobile data in Pakistan.
- ✅ Correct by construction: the fingerprint is the SHA-256 of the exact bytes we would
  send, so any change (new exercise, edited steps, a new caution after a profile change)
  produces a new ETag. No version number to remember to bump.
- The server still runs the query; only the download is saved. Server-side caching (Redis)
  can come later if needed.
- `Cache-Control: private, no-cache`. *private* because cautions depend on the user, so
  shared caches must not keep it. *no-cache* means "keep it, but ask before reusing".
  `Vary: Authorization` for the same reason.

### 3. "For me" is a switch, not the default
`for_me=true` keeps only exercises the user's location and equipment allow (ADR 0010:
gym users have everything except bands and never get home tricks; home users need every
item an exercise lists). Without it, the full library.
- ✅ The main screen sends `for_me=true`. "Show all" is one tap away, so a home user can
  still browse gym moves for later.
- `for_me=true` without a profile is 404 `profile_not_found` (finish onboarding first).
- The filter runs **in SQL**, so `total` and the pages stay right. The same rule also
  exists as a pure Python function (`training.exercise_rules.can_do`) for the plan
  generator. A test runs both over the whole library for four setups and requires them to
  agree.

### 4. Cautions: show with a warning, don't hide
When the user has a profile, every exercise carries `cautions`: why it may not suit them.

| Caution | When |
|---|---|
| `knees`, `back`, `shoulders` | The user has that limit and the exercise is marked not suitable for it |
| `low_intensity` | Any "yes" on the safety screen and the exercise is medium or high impact |
| `not_quiet` | Women-at-home (quiet) track and the exercise is medium or high impact |

- ✅ Transparent: the user sees the whole library and *why* a move is flagged. The app
  shows e.g. "Not for your knees".
- ❌ Hiding was the safer alternative. We accept showing them because **the plan
  generator never picks a cautioned exercise**: the library is for browsing, the plan is
  what they actually train. The workout player's "this hurts, swap it" will also only
  offer uncautioned moves.
- Cautions don't depend on `for_me`: a gym move a home user browses is still flagged for
  their knees.

### 5. Other details
- Both endpoints need a token. Guests have one, so this isn't a sign-in wall.
- Unknown query parameters are a 422 (`catgory=push` would otherwise silently return
  everything).
- `muscle=` matches the primary or a secondary muscle.
- Detail shows `easier` (the exercise whose harder variant is this one; unique by
  ADR 0003), `harder` and `alternatives` as small links (id, slug, name, difficulty).
  They aren't filtered by the user's equipment yet; swaps will come from the plan
  generator.

## Consequences
- New pure module `training/exercise_rules.py` (`user_kit`, `can_do`, `cautions`) and the
  `Caution` enum, ready for the plan generator.
- `api/caching.py` can give any future read endpoint (plans, history) the same data
  saver in one line.
- Follow-up: a "this hurts, swap it" endpoint that only offers uncautioned alternatives
  the user can do.
