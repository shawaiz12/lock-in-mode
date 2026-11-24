"""Coming back after a break (ADR 0021): noticing it, saving it, ending it.

Reads and writes models only, so the plans service can use it to serve eased workouts
(services: sessions → progress → plans → comeback).

A comeback is **due** when the last ticked set is 14+ days old and no saved comeback
covers that break yet (`trained_until`). Nothing is written while it's only due: every
read works it out again. Starting the next workout saves it (`start`), "I kept training
elsewhere" ends it (`opt_out`), and it ends by itself once its workouts are trained
(`after_finish`).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Comeback, Profile, SetLog, WorkoutSession
from lock_in_mode_api.models.enums import ComebackEndReason
from lock_in_mode_api.services import events
from lock_in_mode_api.training import comeback as rules

MAX_AWAY_DAYS = 32_000  # fits the SMALLINT column; anything past this is "very long"


class NoComebackError(Exception):
    """No break to come back from. Callers answer 404."""


@dataclass(frozen=True)
class Now:
    """A comeback that applies right now: saved and still open, or due (found, not saved).

    `done`: comeback workouts trained so far. `replaces`: the open comeback that a new
    break ends when this one is saved.
    """

    away_days: int
    weeks: int
    per_week: int
    done: int
    trained_until: datetime
    saved: Comeback | None = None
    replaces: Comeback | None = None

    @property
    def due(self) -> bool:
        return self.saved is None

    @property
    def saved_id(self) -> uuid.UUID | None:
        return self.saved.id if self.saved is not None else None

    @property
    def workouts_left(self) -> int:
        return self.weeks * self.per_week - self.done

    def week_of(self, index: int) -> int | None:
        """The comeback week of the `index`-th comeback workout still to train (from 0)."""
        return rules.week_of(self.done + index, self.per_week, self.weeks)


async def last_trained(session: AsyncSession, user_id: uuid.UUID) -> datetime | None:
    """When this user last ticked a set, in any workout, finished or not."""
    return await session.scalar(
        select(func.max(SetLog.logged_at))
        .join(WorkoutSession, WorkoutSession.id == SetLog.session_id)
        .where(WorkoutSession.user_id == user_id)
    )


async def _open(session: AsyncSession, user_id: uuid.UUID) -> Comeback | None:
    return await session.scalar(
        select(Comeback).where(Comeback.user_id == user_id, Comeback.ended_at.is_(None))
    )


async def _done(session: AsyncSession, comeback_id: uuid.UUID) -> int:
    """Comeback workouts trained: finished, with at least one ticked set."""
    count = await session.scalar(
        select(func.count())
        .select_from(WorkoutSession)
        .where(
            WorkoutSession.comeback_id == comeback_id,
            WorkoutSession.finished_at.is_not(None),
            exists().where(SetLog.session_id == WorkoutSession.id),
        )
    )
    return count or 0


async def find(
    session: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> Now | None:
    """The comeback that applies now, if any. Writes nothing."""
    last = await last_trained(session, user_id)
    if last is None:
        return None  # never trained: workout 1 is the strength test, not a comeback
    current = await _open(session, user_id)
    away = min(((now or datetime.now(UTC)) - last).days, MAX_AWAY_DAYS)
    weeks = rules.weeks_for(away)
    if weeks:
        covered = await session.scalar(
            select(func.max(Comeback.trained_until)).where(Comeback.user_id == user_id)
        )
        per_week = await session.scalar(
            select(Profile.days_per_week).where(Profile.user_id == user_id)
        )
        if (covered is None or covered < last) and per_week is not None:
            return Now(away, weeks, per_week, done=0, trained_until=last, replaces=current)
    if current is None:
        return None
    done = await _done(session, current.id)
    if done >= current.workouts:
        return None  # finished: after_finish ends it in the same transaction
    return Now(
        current.away_days,
        current.weeks,
        current.workouts_per_week,
        done,
        current.trained_until,
        saved=current,
    )


def _end(comeback: Comeback, reason: ComebackEndReason) -> None:
    comeback.ended_at = datetime.now(UTC)
    comeback.end_reason = reason


async def start(session: AsyncSession, user_id: uuid.UUID, due: Now) -> Comeback:
    """Save a due comeback, ending the open one a new break replaces. The caller commits."""
    if due.replaces is not None:
        _end(due.replaces, ComebackEndReason.NEW_BREAK)
        await session.flush()  # the new one can't be open alongside it
    comeback = Comeback(
        user_id=user_id,
        trained_until=due.trained_until,
        away_days=due.away_days,
        weeks=due.weeks,
        workouts_per_week=due.per_week,
        started_at=datetime.now(UTC),
    )
    session.add(comeback)
    await session.flush()
    await events.comeback_started(
        session, user_id, away_days=comeback.away_days, weeks=comeback.weeks
    )
    return comeback


async def after_finish(session: AsyncSession, workout_session: WorkoutSession) -> None:
    """A comeback workout was finished: end the comeback once all of them are trained.
    The caller commits."""
    if workout_session.comeback_id is None:
        return
    comeback = await session.get(Comeback, workout_session.comeback_id, with_for_update=True)
    if comeback is None or comeback.ended_at is not None:
        return
    if await _done(session, comeback.id) >= comeback.workouts:
        _end(comeback, ComebackEndReason.DONE)
        await session.flush()


async def opt_out(session: AsyncSession, user_id: uuid.UUID) -> None:
    """ "I kept training elsewhere": no more easing for workouts not started yet. A due
    comeback is saved already ended, so the same break isn't found again."""
    current = await find(session, user_id)
    if current is None:
        raise NoComebackError
    try:
        saved = current.saved or await start(session, user_id, current)
        _end(saved, ComebackEndReason.OPTED_OUT)
        await session.commit()
    except IntegrityError:
        # A double tap saved it at the same moment: that request's answer stands.
        await session.rollback()
