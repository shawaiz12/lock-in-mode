"""Stage 1 of the plan generator: pick the routine and lay out the week (ADR 0014).

Input: the onboarding answers. Output: one week of sessions in queue order, a suggested
weekday for each, and plain-language reasons for the "building your plan" screen.
Rules: Knowledge Base sections 4 (routine, goal, time, equipment, layout) and 7 (HIIT).
Pure: no database, no clock, so the same answers always give the same week.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import combinations, permutations
from typing import Protocol

from lock_in_mode_api.models.enums import (
    Equipment,
    FitnessLevel,
    Goal,
    Location,
    RoutineKind,
    SessionKind,
    ShoulderDay,
)
from lock_in_mode_api.training.routine_rules import RoutineInputs, bro_split_available

S = SessionKind

DAYS_IN_WEEK = 7
SHORT_SESSION_MINUTES = 20  # 10 and 20 minutes: full body only (KB section 4)
PPL_MIN_MINUTES = 30
BEGINNER_MAX_HARD_DAYS = 3
PULLING_KIT = frozenset({Equipment.RESISTANCE_BANDS, Equipment.DUMBBELLS, Equipment.PULL_UP_BAR})

# The KB's example weeks (section 4), tried first so ordinary plans look familiar.
PREFERRED_DAYS: dict[int, tuple[int, ...]] = {
    2: (0, 3),
    3: (0, 2, 4),
    4: (0, 1, 3, 4),
    5: (0, 1, 2, 4, 5),
    6: (0, 1, 2, 3, 4, 5),
}


class PlanInputs(RoutineInputs, Protocol):
    """Every answer stage 1 reads. Profile rows fit."""

    @property
    def needs_low_intensity(self) -> bool: ...
    @property
    def prefers_bro_split(self) -> bool: ...
    @property
    def shoulder_day(self) -> ShoulderDay: ...


@dataclass(frozen=True)
class PlannedSession:
    kind: SessionKind
    finisher: bool = False  # 4 to 8 minutes of intervals after strength (lose fat, 2-3 days)


@dataclass(frozen=True)
class Routine:
    kind: RoutineKind
    sessions: tuple[PlannedSession, ...]  # one week, in the order the queue serves them
    weekdays: tuple[int, ...]  # suggested day for each session: 0 = Monday ... 6 = Sunday
    reasons: tuple[str, ...]

    @property
    def uses_push_pull_legs(self) -> bool:
        """Ask "shoulders with push day or leg day?" on the plan screen (ADR 0012)."""
        return any(s.kind in (S.PUSH, S.LEGS) for s in self.sessions)


# --- what each session works hard, for the layout rules ------------------------------

_FULL_BODY = frozenset({"chest", "back", "shoulders", "legs"})
_UPPER = frozenset({"chest", "back", "shoulders", "biceps", "triceps"})
_HARD_MUSCLES: dict[SessionKind, frozenset[str]] = {
    S.FULL_BODY: _FULL_BODY,
    S.CIRCUIT: _FULL_BODY,
    S.UPPER: _UPPER,
    S.LOWER: frozenset({"legs"}),
    S.PULL: frozenset({"back", "biceps"}),
    S.BRO_CHEST: frozenset({"chest"}),
    S.BRO_BACK: frozenset({"back"}),
    S.BRO_LEGS: frozenset({"legs"}),
    S.BRO_SHOULDERS: frozenset({"shoulders"}),
    S.BRO_ARMS: frozenset({"biceps", "triceps"}),
}
EASY_KINDS = frozenset({S.STEADY_CARDIO, S.LONG_CARDIO, S.EASY_CARDIO, S.MOBILITY})


def hard_muscles(kind: SessionKind, shoulder_day: ShoulderDay) -> frozenset[str]:
    """Muscle groups a session trains hard. Push and legs depend on where shoulders go."""
    shoulders_on_legs = shoulder_day == ShoulderDay.LEGS
    if kind == S.PUSH:
        base = frozenset({"chest", "triceps"})
        return base if shoulders_on_legs else base | {"shoulders"}
    if kind == S.LEGS:
        return frozenset({"legs", "shoulders"}) if shoulders_on_legs else frozenset({"legs"})
    return _HARD_MUSCLES.get(kind, frozenset())


def is_hard(kind: SessionKind) -> bool:
    return kind not in EASY_KINDS


# --- the layout rules (KB section 4 "Laying out the week", section 7 "Rules") --------


def _valid_week(
    kinds: Sequence[SessionKind], days: Sequence[int], beginner: bool, shoulder_day: ShoulderDay
) -> bool:
    by_day: dict[int, SessionKind] = dict(zip(days, kinds, strict=True))
    if DAYS_IN_WEEK - len(days) < 1:
        return False  # at least one full rest day for everyone
    if (
        beginner
        and sum(1 for d in range(DAYS_IN_WEEK) if not is_hard(by_day.get(d, S.MOBILITY))) < 2
    ):
        return False  # beginners: at least two days without a hard session
    for day in range(DAYS_IN_WEEK):
        today = by_day.get(day)
        tomorrow = by_day.get((day + 1) % DAYS_IN_WEEK)  # Sunday runs into next Monday
        if today is None or tomorrow is None:
            continue
        if hard_muscles(today, shoulder_day) & hard_muscles(tomorrow, shoulder_day):
            return False  # same muscle hard on back-to-back days
        if beginner and is_hard(today) and is_hard(tomorrow):
            return False  # beginners rest or go easy after every hard day
        if today == S.HIIT and tomorrow == S.HIIT:
            return False  # no two HIIT days in a row
        if today == S.HIIT and "legs" in hard_muscles(tomorrow, shoulder_day):
            return False  # no HIIT the day before legs
    return True


def _day_options(count: int) -> Iterator[tuple[int, ...]]:
    preferred = PREFERRED_DAYS[count]
    yield preferred
    for days in combinations(range(DAYS_IN_WEEK), count):
        if days != preferred:
            yield days


def lay_out_week(
    sessions: Sequence[PlannedSession], beginner: bool, shoulder_day: ShoulderDay
) -> tuple[tuple[PlannedSession, ...], tuple[int, ...]]:
    """Find weekdays (and if needed a new order) that keep every layout rule.

    Tries the given order on the KB's example days first, then other days, then other
    orders. At most 720 orders x 35 day choices, so brute force is fine and easy to trust.
    """
    seen: set[tuple[SessionKind, ...]] = set()
    for order in permutations(sessions):
        kinds = tuple(s.kind for s in order)
        if kinds in seen:
            continue
        seen.add(kinds)
        for days in _day_options(len(order)):
            if _valid_week(kinds, days, beginner, shoulder_day):
                return tuple(order), days
    raise ValueError(f"No week layout keeps the rules for {[s.kind.value for s in sessions]}")


# --- choosing the sessions -----------------------------------------------------------


def _can_pull(answers: PlanInputs) -> bool:
    return answers.location == Location.GYM or bool(PULLING_KIT & set(answers.equipment))


def _fill_with_easy(strength: list[SessionKind], days: int) -> list[SessionKind]:
    """Strength days first, then easy cardio for the rest of the days."""
    return strength + [S.EASY_CARDIO] * (days - len(strength))


def _muscle_or_strength(
    answers: PlanInputs, short: bool, reasons: list[str]
) -> tuple[RoutineKind, list[SessionKind]]:
    """Base routine (KB section 4: days x level), with the time, kit and goal limits."""
    days = answers.days_per_week
    level = answers.level
    strength_goal = answers.goal == Goal.STRENGTH

    if level == FitnessLevel.BEGINNER and days > BEGINNER_MAX_HARD_DAYS:
        reasons.append(
            "Beginner: 3 hard workouts a week at most. Your other days are easy cardio or "
            "mobility, so your body can recover and come back stronger."
        )
        extras = [S.EASY_CARDIO, S.EASY_CARDIO, S.MOBILITY][: days - 3]
        return RoutineKind.FULL_BODY, [S.FULL_BODY] * 3 + extras
    if days <= 3:
        return RoutineKind.FULL_BODY, [S.FULL_BODY] * days
    if short:
        reasons.append(
            "Short sessions train your whole body each time, so the same muscles can't go "
            "on back-to-back days: 3 full-body workouts, and easy cardio on the other days."
        )
        return RoutineKind.FULL_BODY, _fill_with_easy([S.FULL_BODY] * 3, days)
    if days == 4:
        return RoutineKind.UPPER_LOWER, [S.UPPER, S.LOWER, S.UPPER, S.LOWER]

    wants_bro = answers.prefers_bro_split and bro_split_available(answers)
    if days == 5 and wants_bro:
        reasons.append(
            "Bro split, as you chose: one body part a day, plus a light second dose of each "
            "muscle later in the week so nothing is trained only once."
        )
        return RoutineKind.BRO_SPLIT, [
            S.BRO_CHEST,
            S.BRO_BACK,
            S.BRO_LEGS,
            S.BRO_SHOULDERS,
            S.BRO_ARMS,
        ]

    long_enough = (
        answers.minutes_per_session is None or answers.minutes_per_session >= PPL_MIN_MINUTES
    )
    ppl_allowed = _can_pull(answers) and long_enough and not strength_goal
    if not ppl_allowed:
        if strength_goal:
            reasons.append(
                "Build strength: upper/lower and full body, so your main lifts come back "
                "2 to 3 times a week. Practice is how strength grows."
            )
        else:
            reasons.append(
                "No pulling equipment at home yet, so upper/lower instead of push pull legs. "
                "A pull-up bar or bands would open up more back exercises."
            )
        if days == 5:
            return RoutineKind.UPPER_LOWER, [S.UPPER, S.LOWER, S.FULL_BODY, S.UPPER, S.LOWER]
        return RoutineKind.UPPER_LOWER, [S.UPPER, S.LOWER] * 3

    if days == 5:
        if level == FitnessLevel.EXPERIENCED:
            return RoutineKind.UPPER_LOWER_PPL, [S.PUSH, S.PULL, S.LEGS, S.UPPER, S.LOWER]
        return RoutineKind.UPPER_LOWER_PPL, [S.UPPER, S.LOWER, S.PUSH, S.PULL, S.LEGS]
    return RoutineKind.PUSH_PULL_LEGS, [S.PUSH, S.PULL, S.LEGS] * 2


def _lose_fat(
    answers: PlanInputs, short: bool, reasons: list[str]
) -> tuple[RoutineKind, list[PlannedSession]]:
    days = answers.days_per_week
    reasons.append(
        "Lose fat: strength training keeps your muscle while you lose fat. Fat loss itself "
        "comes mostly from eating a bit less than you burn."
    )
    if days <= 3:
        return RoutineKind.FULL_BODY, [PlannedSession(S.FULL_BODY, finisher=True)] * days
    if answers.level == FitnessLevel.BEGINNER and days >= 5:
        # 4 hard days can't each be followed by an easy one in 7 days, so beginners keep
        # 3 hard days: full body with a finisher, plus easy cardio (KB section 4).
        reasons.append(
            "Beginner: 3 hard workouts a week at most. Your other days are steady cardio "
            "and easy walks."
        )
        easy = [S.STEADY_CARDIO, S.EASY_CARDIO, S.MOBILITY][: days - 3]
        return RoutineKind.STRENGTH_AND_CARDIO, [
            *[PlannedSession(S.FULL_BODY, finisher=True)] * 3,
            *[PlannedSession(k) for k in easy],
        ]
    full_body_only = short or answers.level == FitnessLevel.BEGINNER
    week: dict[int, list[SessionKind]] = {
        4: [S.FULL_BODY, S.HIIT, S.FULL_BODY, S.STEADY_CARDIO],
        5: [S.UPPER, S.LOWER, S.HIIT, S.FULL_BODY, S.STEADY_CARDIO],
        6: [S.UPPER, S.LOWER, S.HIIT, S.UPPER, S.LOWER, S.STEADY_CARDIO],
    }
    if full_body_only:
        week[5] = [S.FULL_BODY, S.HIIT, S.FULL_BODY, S.STEADY_CARDIO, S.FULL_BODY]
        week[6] = [S.FULL_BODY, S.HIIT, S.FULL_BODY, S.STEADY_CARDIO, S.FULL_BODY, S.EASY_CARDIO]
    return RoutineKind.STRENGTH_AND_CARDIO, [PlannedSession(k) for k in week[days]]


def _stamina(reasons: list[str], days: int, beginner: bool) -> list[SessionKind]:
    reasons.append(
        "Improve stamina: about half your days are cardio, and strength days are "
        "full-body circuits that keep your heart rate up."
    )
    if beginner and days >= 5:
        reasons.append(
            "Beginner: one HIIT day a week to start; the other cardio days are steady, "
            "so you have 3 hard days at most."
        )
        easy_tail = [S.STEADY_CARDIO] if days == 5 else [S.STEADY_CARDIO, S.LONG_CARDIO]
        return [S.CIRCUIT, S.HIIT, S.STEADY_CARDIO, S.CIRCUIT, *easy_tail]
    week: dict[int, list[SessionKind]] = {
        2: [S.CIRCUIT, S.CIRCUIT],
        3: [S.CIRCUIT, S.HIIT, S.CIRCUIT],
        4: [S.CIRCUIT, S.HIIT, S.CIRCUIT, S.STEADY_CARDIO],
        5: [S.CIRCUIT, S.HIIT, S.STEADY_CARDIO, S.CIRCUIT, S.HIIT],
        6: [S.CIRCUIT, S.HIIT, S.STEADY_CARDIO, S.CIRCUIT, S.HIIT, S.LONG_CARDIO],
    }
    return week[days]


def _sessions_for_goal(
    answers: PlanInputs, short: bool, reasons: list[str]
) -> tuple[RoutineKind, list[PlannedSession]]:
    days = answers.days_per_week
    match answers.goal:
        case Goal.LOSE_FAT:
            return _lose_fat(answers, short, reasons)
        case Goal.STAMINA:
            kinds = _stamina(reasons, days, answers.level == FitnessLevel.BEGINNER)
            return RoutineKind.CIRCUITS_AND_CARDIO, [PlannedSession(k) for k in kinds]
        case Goal.STAY_ACTIVE:
            reasons.append(
                "Stay active: full body on 2 to 3 days. Your other days are easy walks, "
                "which still count."
            )
            kinds = _fill_with_easy([S.FULL_BODY] * min(days, 3), days)
            return RoutineKind.FULL_BODY, [PlannedSession(k) for k in kinds]
        case _:
            kind, kinds = _muscle_or_strength(answers, short, reasons)
            return kind, [PlannedSession(k) for k in kinds]


def _make_safe(
    sessions: list[PlannedSession], answers: PlanInputs, reasons: list[str]
) -> list[PlannedSession]:
    """Low intensity (any "yes" on the safety screen): no HIIT and no finishers."""
    if not answers.needs_low_intensity:
        return sessions
    if any(s.kind == S.HIIT or s.finisher for s in sessions):
        reasons.append(
            "From your safety check: brisk walks instead of HIIT, and no finishers. "
            "Check with a doctor before pushing harder."
        )
    return [
        PlannedSession(S.STEADY_CARDIO) if s.kind == S.HIIT else PlannedSession(s.kind)
        for s in sessions
    ]


def _days_reason(sessions: Sequence[PlannedSession]) -> str:
    hard = sum(1 for s in sessions if is_hard(s.kind))
    easy = len(sessions) - hard
    text = f"{len(sessions)} days a week: {hard} hard"
    if easy:
        text += f" and {easy} easy"
    return text + ". Rest days are spread so no muscle works hard two days in a row."


def choose_routine(answers: PlanInputs) -> Routine:
    """Pick this user's routine and suggested week (KB sections 4 and 7)."""
    reasons: list[str] = []
    minutes = answers.minutes_per_session
    short = minutes is not None and minutes <= SHORT_SESSION_MINUTES

    kind, sessions = _sessions_for_goal(answers, short, reasons)
    if short:
        reasons.append(
            f"{minutes}-minute sessions: full body, done as circuits or supersets so every "
            "minute counts."
        )
    sessions = _make_safe(sessions, answers, reasons)
    # Described from what is left after the safety rules, so the text never promises
    # a finisher or HIIT the user won't get.
    if any(s.finisher for s in sessions):
        reasons.append("A short burst of intervals (a finisher) ends each strength workout.")
    if any(s.kind == S.HIIT for s in sessions):
        if answers.level == FitnessLevel.BEGINNER:
            reasons.append("HIIT days: short intervals, kept low impact (no jumping) for now.")
        else:
            reasons.append("HIIT days: short, hard intervals. Never two in a row.")
    beginner = answers.level == FitnessLevel.BEGINNER
    ordered, weekdays = lay_out_week(sessions, beginner, answers.shoulder_day)
    reasons.insert(0, _days_reason(ordered))
    return Routine(kind=kind, sessions=ordered, weekdays=weekdays, reasons=tuple(reasons))
