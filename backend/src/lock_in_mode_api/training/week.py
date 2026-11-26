"""The week and the weekly streak (ADR 0034). Pure rules, no database.

Lock In Mode is a weekly habit (2–6 planned workouts a week), so its streak counts WEEKS,
not days: a daily streak would push people to open the app, or train, on rest days.

- A week runs Monday to Sunday in the user's time zone.
- A week is KEPT with at least 2 trained workouts (his choice: a "minimum week", so a hard
  week still counts). The ring on Home shows the full plan ("2 of 4"); closing it is the
  bigger win, but the streak only needs 2.
- The streak is the number of kept weeks in a row. The week in progress joins it once it's
  kept; until then it can't break anything (there's still time).
- FREEZES save a missed week (his choice: earned, used by themselves): one is earned for
  every 4 kept weeks, at most 2 are held, and a missed week uses one automatically. A
  frozen week keeps the streak going but doesn't add to it. A missed week with no streak
  to protect uses nothing.
- Weeks before the first trained workout don't count.

.NET: a pure static class over a list of dates, like a LINQ GroupBy week + Aggregate.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

KEEP_AT = 2  # trained workouts that keep a week
FREEZE_EVERY = 4  # kept weeks per freeze earned
MAX_FREEZES = 2

type WeekState = Literal["kept", "frozen", "missed"]


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def local_monday(at: datetime, zone: ZoneInfo) -> date:
    """The Monday of the week `at` falls in, on the user's own calendar."""
    return monday(at.astimezone(zone).date())


@dataclass(frozen=True)
class Week:
    start: date  # Monday of this week
    done: int  # trained workouts this week
    kept: bool  # done >= KEEP_AT
    streak: int  # kept weeks in a row, this week included once it's kept
    best: int  # the longest streak so far
    freezes: int  # held right now (0 … MAX_FREEZES)
    last_week: WeekState | None  # how last week ended; None: before they started


def summarize(trained_weeks: Iterable[date], this_week: date) -> Week:
    """`trained_weeks`: the Monday of each trained workout (one entry per workout)."""
    per_week = Counter(trained_weeks)
    done_now = per_week.get(this_week, 0)
    past = sorted(w for w in per_week if w < this_week)

    streak = best = freezes = kept_total = 0
    # Every week from the first trained one up to last week, in order: the last one
    # walked through IS last week, so its state is how last week ended.
    last_week: WeekState | None = None
    week = past[0] if past else this_week
    while week < this_week:
        if per_week.get(week, 0) >= KEEP_AT:
            streak += 1
            kept_total += 1
            if kept_total % FREEZE_EVERY == 0:
                freezes = min(MAX_FREEZES, freezes + 1)
            last_week = "kept"
        elif freezes > 0:  # held only while a streak runs: it ends once they're gone
            freezes -= 1
            last_week = "frozen"
        else:
            streak = 0
            last_week = "missed"
        best = max(best, streak)
        week += timedelta(weeks=1)

    kept = done_now >= KEEP_AT
    if kept:
        streak += 1
        kept_total += 1
        if kept_total % FREEZE_EVERY == 0:
            freezes = min(MAX_FREEZES, freezes + 1)
    return Week(
        start=this_week,
        done=done_now,
        kept=kept,
        streak=streak,
        best=max(best, streak),
        freezes=freezes,
        last_week=last_week,
    )
