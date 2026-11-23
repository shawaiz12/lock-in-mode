"""Rules the database keeps for comebacks after a break (ADR 0021), even if the service has
a bug."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Comeback, Plan, PlannedWorkout, User, WorkoutSession
from lock_in_mode_api.models.enums import (
    ComebackEndReason,
    RoutineKind,
    SessionKind,
    WorkoutFormat,
)


async def _user(session: AsyncSession) -> User:
    user = User()
    session.add(user)
    await session.flush()
    return user


def _comeback(user: User, **fields: Any) -> Comeback:
    defaults = {
        "trained_until": datetime.now(UTC) - timedelta(days=20),
        "away_days": 20,
        "weeks": 1,
        "workouts_per_week": 3,
    }
    return Comeback(user_id=user.id, **(defaults | fields))


async def test_a_valid_comeback_saves(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    db_session.add(_comeback(user))
    await db_session.flush()


@pytest.mark.parametrize(
    ("fields", "constraint"),
    [
        ({"away_days": 13}, "ck_comebacks_away_days_min"),
        ({"weeks": 2}, "ck_comebacks_weeks_allowed"),
        ({"workouts_per_week": 7}, "ck_comebacks_workouts_per_week_range"),
        ({"workouts_per_week": 1}, "ck_comebacks_workouts_per_week_range"),
        # (parameters are built at collection time: a day ahead keeps it after started_at)
        ({"ended_at": datetime.now(UTC) + timedelta(days=1)}, "ck_comebacks_ended_with_reason"),
        ({"end_reason": ComebackEndReason.DONE}, "ck_comebacks_ended_with_reason"),
    ],
)
async def test_comeback_rules(
    db_session: AsyncSession, fields: dict[str, Any], constraint: str
) -> None:
    user = await _user(db_session)
    db_session.add(_comeback(user, **fields))
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()


async def test_a_comeback_cant_end_before_it_starts(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    now = datetime.now(UTC)
    db_session.add(
        _comeback(
            user,
            started_at=now,
            ended_at=now - timedelta(days=1),
            end_reason=ComebackEndReason.OPTED_OUT,
        )
    )
    with pytest.raises(IntegrityError, match="ck_comebacks_end_order"):
        await db_session.flush()


async def test_only_one_open_comeback_per_user(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    now = datetime.now(UTC)
    db_session.add(_comeback(user, ended_at=now, end_reason=ComebackEndReason.NEW_BREAK))
    db_session.add(_comeback(user))
    await db_session.flush()  # an ended one doesn't count

    db_session.add(_comeback(user, weeks=3, away_days=40))
    with pytest.raises(IntegrityError, match="uq_comebacks_one_open_per_user"):
        await db_session.flush()


async def _session(db: AsyncSession, user: User, **fields: Any) -> WorkoutSession:
    workout = PlannedWorkout(
        position=1,
        week=1,
        kind=SessionKind.FULL_BODY,
        title="Full body A",
        format=WorkoutFormat.STRAIGHT_SETS,
        main_minutes=20,
        total_minutes=30,
    )
    db.add(
        Plan(
            user_id=user.id,
            block_number=1,
            routine_kind=RoutineKind.FULL_BODY,
            reasons=[],
            weekdays=[0],
            uses_push_pull_legs=False,
            weeks=5,
            generated_from={},
            workouts=[workout],
        )
    )
    await db.flush()
    workout_session = WorkoutSession(user_id=user.id, planned_workout_id=workout.id, **fields)
    db.add(workout_session)
    return workout_session


async def test_a_session_links_a_comeback_with_its_week(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    comeback = _comeback(user)
    db_session.add(comeback)
    await db_session.flush()
    await _session(db_session, user, comeback_id=comeback.id, comeback_week=1)
    await db_session.flush()


@pytest.mark.parametrize(
    ("week", "linked", "constraint"),
    [
        (None, True, "ck_workout_sessions_comeback_with_week"),
        (1, False, "ck_workout_sessions_comeback_with_week"),
        (4, True, "ck_workout_sessions_comeback_week_range"),
        (0, True, "ck_workout_sessions_comeback_week_range"),
    ],
)
async def test_session_comeback_rules(
    db_session: AsyncSession, week: int | None, linked: bool, constraint: str
) -> None:
    user = await _user(db_session)
    comeback = _comeback(user)
    db_session.add(comeback)
    await db_session.flush()
    await _session(
        db_session, user, comeback_id=comeback.id if linked else None, comeback_week=week
    )
    with pytest.raises(IntegrityError, match=constraint):
        await db_session.flush()
