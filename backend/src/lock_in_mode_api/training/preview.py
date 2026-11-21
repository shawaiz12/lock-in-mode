"""See the routine for any set of answers, without the API or a database.

    uv run python -m lock_in_mode_api.training.preview --goal lose_fat --level beginner \\
        --location home --days 3 --minutes 20
"""

import argparse
from dataclasses import dataclass

from lock_in_mode_api.models.enums import FitnessLevel, Goal, Location, ShoulderDay
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training.routine import choose_routine
from lock_in_mode_api.training.sessions import Workout, build_block

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class _Answers:
    goal: Goal
    level: FitnessLevel
    location: Location
    equipment: list[str]
    days_per_week: int
    minutes_per_session: int | None
    needs_low_intensity: bool
    prefers_bro_split: bool
    shoulder_day: ShoulderDay
    limits: list[str]
    women_home_track: bool


def _parse(argv: list[str] | None) -> tuple[_Answers, int]:
    parser = argparse.ArgumentParser(description="Preview a Lock In Mode routine.")
    parser.add_argument("--goal", type=Goal, choices=list(Goal), default=Goal.BUILD_MUSCLE)
    parser.add_argument(
        "--level", type=FitnessLevel, choices=list(FitnessLevel), default=FitnessLevel.BEGINNER
    )
    parser.add_argument("--location", type=Location, choices=list(Location), default=Location.GYM)
    parser.add_argument("--equipment", nargs="*", default=[], help="home kit, e.g. dumbbells")
    parser.add_argument("--days", type=int, choices=range(2, 7), default=3)
    parser.add_argument("--minutes", type=int, default=None, help="leave out for no limit")
    parser.add_argument("--low-intensity", action="store_true")
    parser.add_argument("--bro-split", action="store_true")
    parser.add_argument("--shoulders-on-legs", action="store_true")
    parser.add_argument("--limits", nargs="*", default=[], help="knees back shoulders")
    parser.add_argument("--quiet-track", action="store_true", help="women-at-home track")
    parser.add_argument("--weeks", type=int, default=1, help="weeks of workouts to show")
    args = parser.parse_args(argv)
    return _Answers(
        goal=args.goal,
        level=args.level,
        location=args.location,
        equipment=args.equipment,
        days_per_week=args.days,
        minutes_per_session=args.minutes,
        needs_low_intensity=args.low_intensity,
        prefers_bro_split=args.bro_split,
        shoulder_day=ShoulderDay.LEGS if args.shoulders_on_legs else ShoulderDay.PUSH,
        limits=args.limits,
        women_home_track=args.quiet_track,
    ), args.weeks


def _workout_lines(workout: Workout) -> list[str]:
    head = f"  {workout.title}  ({workout.format.value.replace('_', ' ')}"
    head += f", about {workout.main_minutes} min)" if workout.exercises else ")"
    if workout.finisher:
        head += " + finisher"
    lines = [head]
    for e in workout.exercises:
        amount = f"{e.reps_min}-{e.reps_max} reps" if e.seconds is None else f"{e.seconds} s"
        pair = f"[{e.group + 1}] " if workout.format.value != "straight_sets" else ""
        lines.append(
            f"      {pair}{e.name}: {e.sets} x {amount}, rest {e.rest_seconds} s, "
            f"stop {e.reps_in_reserve} short"
        )
    if not workout.exercises:
        lines.append("      (filled in stage 2b)")
    return lines


def main(argv: list[str] | None = None) -> str:
    answers, weeks = _parse(argv)
    routine = choose_routine(answers)
    by_day = dict(zip(routine.weekdays, routine.sessions, strict=True))
    lines = [f"Routine: {routine.kind.value}", ""]
    for day, name in enumerate(WEEKDAYS):
        session = by_day.get(day)
        label = "rest" if session is None else session.kind.value.replace("_", " ")
        if session is not None and session.finisher:
            label += " + finisher"
        lines.append(f"  {name}  {label}")
    lines += ["", "Why:"] + [f"  - {reason}" for reason in routine.reasons]
    block = build_block(answers, routine, load_library().exercises, weeks)
    for number, week in enumerate(block, start=1):
        lines += ["", f"Week {number}:"]
        for workout in week:
            lines += _workout_lines(workout)
    return "\n".join(lines)


if __name__ == "__main__":
    print(main())
