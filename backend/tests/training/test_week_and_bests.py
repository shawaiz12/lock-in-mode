"""The weekly streak and personal bests (ADR 0034): pure rules, worked examples."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from lock_in_mode_api.training.bests import Best, SetValues, best_of, new_best
from lock_in_mode_api.training.week import local_monday, monday, summarize

NOW = date(2026, 11, 23)  # a Monday: "this week"


def weeks(*done: int, this_week: int = 0) -> list[date]:
    """weeks(2, 0, 3, this_week=1): 2 workouts 3 weeks ago, none 2 weeks ago, 3 last
    week, 1 this week. One entry per trained workout, as the service passes them."""
    out: list[date] = []
    for back, n in enumerate(reversed(done), start=1):
        out += [NOW - timedelta(weeks=back)] * n
    return out + [NOW] * this_week


def test_nothing_trained_yet() -> None:
    week = summarize([], NOW)
    assert (week.done, week.kept, week.streak, week.best, week.freezes) == (0, False, 0, 0, 0)
    assert week.last_week is None


def test_two_workouts_keep_the_week_and_start_the_streak() -> None:
    assert summarize(weeks(this_week=1), NOW).kept is False
    week = summarize(weeks(this_week=2), NOW)
    assert (week.kept, week.streak) == (True, 1)


def test_the_week_in_progress_never_breaks_the_streak() -> None:
    week = summarize(weeks(2, 3, 2), NOW)  # three kept weeks, nothing yet this week
    assert (week.streak, week.kept, week.last_week) == (3, False, "kept")


def test_a_missed_week_without_a_freeze_ends_the_streak() -> None:
    week = summarize(weeks(2, 2, 1, this_week=2), NOW)
    assert week.last_week == "missed"
    assert (week.streak, week.best) == (1, 2)


def test_every_four_kept_weeks_earn_a_freeze_that_saves_a_missed_week() -> None:
    four = weeks(2, 2, 2, 2)
    assert summarize(four, NOW).freezes == 1

    saved = summarize(weeks(2, 2, 2, 2, 0), NOW)
    assert (saved.last_week, saved.streak, saved.freezes) == ("frozen", 4, 0)

    # A frozen week keeps the streak but doesn't add to it.
    after = summarize(weeks(2, 2, 2, 2, 0, 2), NOW)
    assert after.streak == 5

    gone = summarize(weeks(2, 2, 2, 2, 0, 0), NOW)
    assert (gone.last_week, gone.streak, gone.best) == ("missed", 0, 4)


def test_at_most_two_freezes() -> None:
    assert summarize(weeks(*[2] * 12), NOW).freezes == 2


def test_a_missed_week_with_no_streak_uses_no_freeze() -> None:
    week = summarize(weeks(2, 2, 2, 2, 0, 0, 1), NOW)
    assert week.freezes == 0  # the first missed week used it, the rest had nothing to save
    earned = summarize(weeks(2, 2, 2, 2, 0, 0, 1, 2, 2, 2, 2), NOW)
    assert (earned.freezes, earned.streak) == (1, 4)  # 8 kept weeks so far: 2nd freeze


def test_the_week_in_progress_can_earn_a_freeze() -> None:
    assert summarize(weeks(2, 2, 2, this_week=2), NOW).freezes == 1


def test_weeks_run_monday_to_sunday_on_the_users_own_calendar() -> None:
    assert monday(date(2026, 11, 29)) == NOW  # Sunday → its Monday
    late_sunday_utc = datetime(2026, 11, 29, 20, 0, tzinfo=UTC)
    assert local_monday(late_sunday_utc, ZoneInfo("UTC")) == NOW
    # 01:00 on Monday in Karachi (UTC+5): already the next week there.
    assert local_monday(late_sunday_utc, ZoneInfo("Asia/Karachi")) == NOW + timedelta(weeks=1)


# --- personal bests ----------------------------------------------------------------------


def s(
    weight: float | None = None, reps: int | None = None, seconds: int | None = None
) -> SetValues:
    return SetValues(weight, reps, seconds)


def test_the_best_of_a_workout() -> None:
    best = best_of([s(40, 8), s(42.5, 6), s(None, 5), s(seconds=30), s(seconds=45)])
    # Reps only from sets without weight: 8 reps at 40 kg isn't a bodyweight best.
    assert best == Best(weight_kg=42.5, reps=5, seconds=45)


def test_more_than_before_is_a_new_best() -> None:
    assert new_best(Best(reps=14), Best(reps=12)) == ("reps", 14, 12)
    assert new_best(Best(seconds=50), Best(seconds=45)) == ("seconds", 50, 45)
    assert new_best(Best(weight_kg=45, reps=None), Best(weight_kg=42.5)) == ("weight", 45, 42.5)


def test_equal_or_less_is_not() -> None:
    assert new_best(Best(reps=12), Best(reps=12)) is None
    assert new_best(Best(weight_kg=40), Best(weight_kg=42.5)) is None


def test_the_first_time_is_never_a_best() -> None:
    assert new_best(Best(reps=14), Best()) is None
    assert new_best(Best(weight_kg=20), Best(reps=10)) is None  # first time with weight


def test_weight_comes_first() -> None:
    assert new_best(Best(weight_kg=45, reps=20), Best(weight_kg=40, reps=10)) == ("weight", 45, 40)
