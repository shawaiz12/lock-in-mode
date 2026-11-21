"""See the routine for any set of answers, without the API or a database.

    uv run python -m lock_in_mode_api.training.preview --goal lose_fat --level beginner \\
        --location home --days 3 --minutes 20
"""

import argparse
from dataclasses import dataclass

from lock_in_mode_api.models.enums import FitnessLevel, Goal, Location, ShoulderDay
from lock_in_mode_api.training.routine import choose_routine

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


def _parse(argv: list[str] | None) -> _Answers:
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
    )


def main(argv: list[str] | None = None) -> str:
    routine = choose_routine(_parse(argv))
    by_day = dict(zip(routine.weekdays, routine.sessions, strict=True))
    lines = [f"Routine: {routine.kind.value}", ""]
    for day, name in enumerate(WEEKDAYS):
        session = by_day.get(day)
        label = "rest" if session is None else session.kind.value.replace("_", " ")
        if session is not None and session.finisher:
            label += " + finisher"
        lines.append(f"  {name}  {label}")
    lines += ["", "Why:"] + [f"  - {reason}" for reason in routine.reasons]
    return "\n".join(lines)


if __name__ == "__main__":
    print(main())
