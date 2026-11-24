"""The funnel report (ADR 0025), printed in the terminal:

    uv run python -m lock_in_mode_api.reports            # people who signed up in the last 90 days
    uv run python -m lock_in_mode_api.reports --days 30

It reads the database the settings point at (your .env), and only reads.

- Funnel: how many of the people who signed up reached each step, and the % kept from the
  step before.
- Weekly retention: per sign-up week, the share who finished a workout in week 1, 2 and 4
  after signing up. "…" = that week hasn't fully happened yet for everyone in the row.
- Other counts in the same days: linked accounts, level-ups, deletions, leaving reasons.

Users who switched "Share usage data" off have no events, so they aren't in it.
"""

import argparse
import asyncio
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import AccountDeletionReason, Event
from lock_in_mode_api.models.enums import EventName

RETENTION_WEEKS = (1, 2, 4)


@dataclass(frozen=True)
class Step:
    label: str
    users: int
    kept: float | None  # share of the step before; None: first step, or nobody before


@dataclass(frozen=True)
class Cohort:
    week_of: datetime  # Monday of the sign-up week
    users: int
    trained: dict[int, float | None]  # week after sign-up → share who finished a workout


@dataclass(frozen=True)
class Report:
    days: int
    now: datetime
    funnel: list[Step]
    retention: list[Cohort]
    counts: dict[str, int]
    reasons: dict[str, int]


def _number(at_least: int) -> ColumnElement[bool]:
    condition: ColumnElement[bool] = Event.props["number"].as_integer() >= at_least
    return condition


def _block(number: int) -> ColumnElement[bool]:
    condition: ColumnElement[bool] = Event.props["block"].as_integer() == number
    return condition


def _next_block(number: int) -> ColumnElement[bool]:
    """Block `number` started after the one before was complete. Not a plan rebuilt after
    changed answers: that gets the next block number too (ADR 0017)."""
    reason: ColumnElement[bool] = Event.props["reason"].as_string() == "next_block"
    return _block(number) & reason


# (label, event, extra condition): each step counts the sign-ups who have such an event.
FUNNEL: tuple[tuple[str, EventName, ColumnElement[bool] | None], ...] = (
    ("Signed up", EventName.SIGNED_UP, None),
    ("Onboarding done", EventName.ONBOARDING_DONE, None),
    ("Workout 1 finished", EventName.WORKOUT_FINISHED, _number(1)),
    ("Workout 3 finished", EventName.WORKOUT_FINISHED, _number(3)),
    ("Block 1 complete", EventName.BLOCK_COMPLETE, _block(1)),
    ("Block 2 started", EventName.PLAN_STARTED, _next_block(2)),
)


async def _signups(session: AsyncSession, since: datetime) -> dict[uuid.UUID, datetime]:
    rows = await session.execute(
        select(Event.user_id, func.min(Event.at))
        .where(Event.name == EventName.SIGNED_UP, Event.at >= since)
        .group_by(Event.user_id)
    )
    return {user_id: at for user_id, at in rows}


async def _funnel(session: AsyncSession, cohort: Sequence[uuid.UUID]) -> list[Step]:
    steps: list[Step] = []
    for label, name, condition in FUNNEL:
        query = select(func.count(func.distinct(Event.user_id))).where(
            Event.name == name, Event.user_id.in_(cohort)
        )
        if condition is not None:
            query = query.where(condition)
        users = await session.scalar(query) or 0
        before = steps[-1].users if steps else None
        kept = users / before if before else None
        steps.append(Step(label, users, kept))
    return steps


async def _retention(
    session: AsyncSession, signups: dict[uuid.UUID, datetime], now: datetime
) -> list[Cohort]:
    finished: dict[uuid.UUID, list[datetime]] = defaultdict(list)
    rows = await session.execute(
        select(Event.user_id, Event.at).where(
            Event.name == EventName.WORKOUT_FINISHED, Event.user_id.in_(list(signups))
        )
    )
    for user_id, at in rows:
        finished[user_id].append(at)

    by_week: dict[datetime, list[uuid.UUID]] = defaultdict(list)
    for user_id, at in signups.items():
        monday = (at - timedelta(days=at.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        by_week[monday].append(user_id)

    cohorts = []
    for monday in sorted(by_week):
        users = by_week[monday]
        latest = max(signups[u] for u in users)
        trained: dict[int, float | None] = {}
        for week in RETENTION_WEEKS:
            if latest + timedelta(weeks=week) > now:
                trained[week] = None  # not over yet for everyone in this row
                continue
            start, end = timedelta(weeks=week - 1), timedelta(weeks=week)
            active = sum(
                1
                for u in users
                if any(start <= at - signups[u] < end for at in finished.get(u, ()))
            )
            trained[week] = active / len(users)
        cohorts.append(Cohort(monday, len(users), trained))
    return cohorts


async def _counts(session: AsyncSession, since: datetime) -> dict[str, int]:
    async def count(name: EventName, condition: ColumnElement[bool] | None = None) -> int:
        query = select(func.count()).where(Event.name == name, Event.at >= since)
        if condition is not None:
            query = query.where(condition)
        return await session.scalar(query) or 0

    return {
        "Accounts linked (guest → Google/Apple)": await count(EventName.ACCOUNT_LINKED),
        "Level-up offered (block complete)": await count(
            EventName.BLOCK_COMPLETE, Event.props["level_up_offered"].as_boolean()
        ),
        "Level-up accepted": await count(EventName.LEVEL_UP_ACCEPTED),
        "Comebacks after a break": await count(EventName.COMEBACK_STARTED),
        "Deletions asked (Google/Apple)": await count(EventName.DELETION_REQUESTED),
        "Deletions cancelled": await count(EventName.DELETION_CANCELLED),
    }


async def _reasons(session: AsyncSession, since: datetime) -> dict[str, int]:
    rows = await session.scalars(
        select(AccountDeletionReason.reason).where(AccountDeletionReason.left_on >= since.date())
    )
    return dict(Counter(str(reason) for reason in rows).most_common())


async def build_report(session: AsyncSession, days: int) -> Report:
    now: datetime | None = await session.scalar(select(func.now()))
    assert now is not None
    since = now - timedelta(days=days)
    signups = await _signups(session, since)
    return Report(
        days=days,
        now=now,
        funnel=await _funnel(session, list(signups)),
        retention=await _retention(session, signups, now),
        counts=await _counts(session, since),
        reasons=await _reasons(session, since),
    )


def _pct(share: float | None) -> str:
    return "…" if share is None else f"{share:.0%}"


def render(report: Report) -> str:
    lines = [f"Lock In Mode funnel: people who signed up in the last {report.days} days", ""]
    width = max(len(step.label) for step in report.funnel)
    lines.append(f"{'Step':<{width}}  {'Users':>6}  {'Kept':>5}")
    for n, step in enumerate(report.funnel):
        kept = "" if n == 0 else ("–" if step.kept is None else _pct(step.kept))
        lines.append(f"{step.label:<{width}}  {step.users:>6}  {kept:>5}")

    lines += ["", "Trained in week … after signing up"]
    header = "".join(f"  {'week ' + str(w):>7}" for w in RETENTION_WEEKS)
    lines.append(f"{'Signed up':<12}  {'Users':>6}{header}")
    for cohort in report.retention:
        cells = "".join(f"  {_pct(cohort.trained[w]):>7}" for w in RETENTION_WEEKS)
        lines.append(f"{cohort.week_of:%d %b %Y}  {cohort.users:>6}{cells}")
    if not report.retention:
        lines.append("(nobody signed up in these days)")

    lines += ["", "Other counts in these days"]
    width = max(len(label) for label in report.counts)
    lines += [f"{label:<{width}}  {n:>6}" for label, n in report.counts.items()]
    lines += ["", "Why people left (only those who said)"]
    lines += [f"{reason:<{width}}  {n:>6}" for reason, n in report.reasons.items()] or ["(none)"]
    return "\n".join(lines)


async def _main(days: int) -> None:
    from lock_in_mode_api.core.db import SessionLocal, engine

    async with SessionLocal() as session:
        print(render(await build_report(session, days)))
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lock In Mode funnel report (ADR 0025)")
    parser.add_argument("--days", type=int, default=90, help="sign-ups in the last N days")
    asyncio.run(_main(parser.parse_args().days))
