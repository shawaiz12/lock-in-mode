"""XP and the Lock In level (ADR 0035, plan: lock-in-mode/xp-levels-plan.md). Pure rules.

XP sits in the background: real progress (new bests, "This week counts") stays the
headline. What earns XP, per trained workout (finished with a ticked set):

    workout     100 × the share of its planned sets done (half the sets = 50); a recovery
                week workout earns the same: rest is rewarded
    week        +150 once a week is kept (its 2nd trained workout, ADR 0034)
    bests       +25 per new best, at most 3 per workout
    comeback    +100 for the first trained workout after a break (ADR 0021)
    bonus       the "Locked-in bonus": now and then (about 1 in 8, never twice in a row),
                the workout's XP once more. Only ever on top of real XP.

Safety (the Safe principle): only `days_per_week + 1` workouts a week earn XP. More
still count as training, but earn nothing, with a calm line instead. Nothing pays for
opening the app, and XP is never taken away.

The level is called the "Lock In level", so it isn't confused with the training level
(beginner / some experience / experienced, ADR 0022).
"""

import hashlib
import uuid
from dataclasses import dataclass

WORKOUT_XP = 100
WEEK_XP = 150
BEST_XP = 25
MAX_BESTS = 3
COMEBACK_XP = 100
BONUS_EVERY = 8  # about 1 trained workout in 8
FLAT_GAP_FROM = 10  # from this level on, every level is FLAT_GAP XP
FLAT_GAP = 1000


def level_start(level: int) -> int:
    """XP at which `level` starts: 0, 100, 300, 600, 1000 … 4500 at level 10, then +1000.

    The gap to the next level grows by 100 up to level 10: level 2 comes with the first
    workout (an early win), level 5 after about two kept weeks."""
    if level <= FLAT_GAP_FROM:
        return 50 * (level - 1) * level
    return level_start(FLAT_GAP_FROM) + FLAT_GAP * (level - FLAT_GAP_FROM)


@dataclass(frozen=True)
class Level:
    level: int
    xp_into: int  # XP since this level started
    xp_needed: int  # XP from this level's start to the next


def level_of(total: int) -> Level:
    level = 1
    while level_start(level + 1) <= total:
        level += 1
    start = level_start(level)
    return Level(level=level, xp_into=total - start, xp_needed=level_start(level + 1) - start)


def workout_xp(sets_done: int, sets_planned: int) -> int:
    """100 × the share of planned sets done, never more than 100 (extra sets don't pay)."""
    if sets_done <= 0:
        return 0
    if sets_planned <= 0:
        return WORKOUT_XP
    return round(WORKOUT_XP * min(1.0, sets_done / sets_planned))


def bests_xp(new_bests: int) -> int:
    return BEST_XP * min(new_bests, MAX_BESTS)


def lucky(session_id: uuid.UUID) -> bool:
    """The Locked-in bonus roll: about 1 in BONUS_EVERY, decided by the workout itself
    (a hash of its id), so it's the same answer every time it's asked: a retried finish
    can't roll again, and tests know which ids are lucky."""
    return int.from_bytes(hashlib.sha256(session_id.bytes).digest()[:4], "big") % BONUS_EVERY == 0


def gets_bonus(session_id: uuid.UUID, previous_had_bonus: bool) -> bool:
    return not previous_had_bonus and lucky(session_id)


def capped(trained_before_this_week: int, days_per_week: int) -> bool:
    """This workout is past the week's XP limit: days a week + 1."""
    return trained_before_this_week >= days_per_week + 1
