"""Placing the user on each exercise ladder from the strength test (KB section 2, ADR 0018).

Overall level sets how much work; the starting exercise is set per movement, because a
person can be strong at squats and unable to do one push-up. The first workout's open
test sets (as many good reps as you can, stop with 2 left) give one result per movement.

A placement is a **rung**: a difficulty (1-5) for the bodyweight moves of that movement.
The picker then prefers bodyweight moves at exactly that difficulty, whatever the level.
Weighted lifts are placed by the weight the user logs instead (KB: "gym users pick
starting weights"), so they never get a rung.
"""

from collections.abc import Mapping

from lock_in_mode_api.models.enums import MovementSlot as M

# result (reps, or seconds for the plank) → the exercise to start on. Read top-down: the
# last row whose minimum the result reaches wins. KB section 2, with two adjustments:
# 0 push-ups starts on the incline push-up (the KB groups 0-4 as "incline or knee"),
# and 25+ squats goes to the one-and-a-half squat, because the KB's tempo squat is the
# same difficulty as a bodyweight squat in our library.
RUNG_BY_RESULT: Mapping[M, tuple[tuple[int, str], ...]] = {
    M.HORIZONTAL_PUSH: (
        (0, "incline-push-up"),
        (1, "knee-push-up"),
        (5, "push-up"),
        (15, "decline-push-up"),
        (30, "archer-push-up"),
    ),
    M.SQUAT: ((0, "chair-squat"), (10, "bodyweight-squat"), (25, "one-and-a-half-squat")),
    M.BRACE: ((0, "knee-plank"), (20, "plank"), (60, "plank-shoulder-taps")),  # seconds
    M.VERTICAL_PULL: ((0, "negative-pull-up"), (1, "chin-up"), (6, "pull-up")),
}


def placed_exercise(movement: M, result: int) -> str | None:
    """The slug to start on for this test result, or None if the movement isn't tested."""
    rows = RUNG_BY_RESULT.get(movement)
    if rows is None:
        return None
    slug = rows[0][1]
    for minimum, candidate in rows:
        if result >= minimum:
            slug = candidate
    return slug
