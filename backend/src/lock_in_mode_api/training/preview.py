"""See the routine for any set of answers, without the API or a database.

    uv run python -m lock_in_mode_api.training.preview --goal lose_fat --level beginner \\
        --location home --days 3 --minutes 20
"""

import argparse
from dataclasses import dataclass

from lock_in_mode_api.models.enums import FitnessLevel, Goal, Location, ShoulderDay
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training.plan_types import PlannedExercise, Workout
from lock_in_mode_api.training.routine import choose_routine
from lock_in_mode_api.training.sessions import build_block

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


@dataclass(frozen=True)
class _Options:
    weeks: int
    first_block: bool
    block_number: int
    recovery_week: bool


def _parse(argv: list[str] | None) -> tuple[_Answers, _Options]:
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
    parser.add_argument("--first-block", action="store_true", help="show the strength test")
    parser.add_argument("--block", type=int, default=1, help="block number: 2 shows new picks")
    parser.add_argument(
        "--recovery-week", action="store_true", help="add the lighter week after the weeks"
    )
    args = parser.parse_args(argv)
    return (
        _Answers(
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
        ),
        _Options(args.weeks, args.first_block, args.block, args.recovery_week),
    )


def _amount(e: PlannedExercise) -> str:
    if e.test and e.reps_min is None and e.seconds is None:
        return "TEST: as many as you can with good form, stop with 2 left"
    if e.seconds is not None and e.reps_in_reserve is not None:  # a hold inside strength work
        return f"{e.sets} x {e.seconds} s, rest {e.rest_seconds} s"
    if e.seconds is not None and e.sets > 1:
        return f"{e.sets} x {e.seconds} s on / {e.rest_seconds} s off"
    if e.seconds is not None:
        return f"{e.seconds // 60} min" if e.seconds >= 120 else f"{e.seconds} s"
    text = f"{e.sets} x {e.reps_min}-{e.reps_max} reps, rest {e.rest_seconds} s"
    if e.reps_in_reserve is not None:
        text += f", stop {e.reps_in_reserve} short"
    if e.test:
        text += " (TEST: pick a weight you can lift with 3 left)"
    if e.practice_sets:
        text += f" (+{e.practice_sets} light practice set{'s' if e.practice_sets > 1 else ''})"
    return text


def _part(label: str, moves: tuple[PlannedExercise, ...], numbered: bool) -> list[str]:
    if not moves:
        return []
    lines = [f"      {label}:"]
    for e in moves:
        pair = f"[{e.group + 1}] " if numbered else ""
        effort = f", effort {e.effort}/10" if e.effort and e.reps_in_reserve is None else ""
        lines.append(f"        {pair}{e.name}: {_amount(e)}{effort}")
    return lines


def _workout_lines(workout: Workout) -> list[str]:
    fmt = workout.format.value.replace("_", " ")
    lines = [f"  {workout.title}  ({fmt}, about {workout.total_minutes} min in total)"]
    numbered = workout.format.value in ("supersets", "first_straight_then_supersets")
    lines += _part("Warm-up", workout.warm_up, False)
    lines += _part("Main", workout.exercises, numbered)
    lines += _part("Finisher", workout.finisher, False)
    lines += _part("Cool-down", workout.cool_down, False)
    return lines


def main(argv: list[str] | None = None) -> str:
    answers, options = _parse(argv)
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
    block = build_block(
        answers,
        routine,
        load_library().exercises,
        options.weeks,
        options.first_block,
        block_number=options.block_number,
        recovery_week=options.recovery_week,
    )
    for number, week in enumerate(block, start=1):
        recovery = bool(week) and week[0].recovery
        lines += ["", f"Week {number}" + (" (recovery week):" if recovery else ":")]
        for workout in week:
            lines += _workout_lines(workout)
    return "\n".join(lines)


if __name__ == "__main__":
    print(main())
