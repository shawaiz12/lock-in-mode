"""The funnel report (ADR 0025, 0034) on a small, hand-made history with known answers."""

import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api import reports
from lock_in_mode_api.models import AccountDeletionReason, Event, User
from lock_in_mode_api.models.enums import EventName, LeavingReason

E = EventName


async def _user(db: AsyncSession, now: datetime, signed_up_days_ago: float) -> "_Timeline":
    user = User()
    db.add(user)
    await db.flush()
    timeline = _Timeline(db, user, now - timedelta(days=signed_up_days_ago))
    await timeline.add(0, E.SIGNED_UP, method="guest")
    return timeline


class _Timeline:
    def __init__(self, db: AsyncSession, user: User, start: datetime) -> None:
        self.db, self.user, self.start = db, user, start

    async def add(self, day: float, name: EventName, **props: Any) -> None:
        self.db.add(
            Event(
                user_id=self.user.id,
                name=name,
                at=self.start + timedelta(days=day),
                props=props,
            )
        )
        await self.db.flush()


@pytest.fixture
async def report(db_session: AsyncSession) -> reports.Report:
    now = await db_session.scalar(select(func.now()))
    assert now is not None
    # Four people who signed up 30 days ago:
    a = await _user(db_session, now, 30)  # the whole way, and back in week 4
    await a.add(0.1, E.ONBOARDING_DONE)
    await a.add(1, E.WORKOUT_FINISHED, number=1)
    await a.add(3, E.WORKOUT_FINISHED, number=2)
    await a.add(8, E.WORKOUT_FINISHED, number=3)
    await a.add(20, E.BLOCK_COMPLETE, block=1, level_up_offered=True)
    await a.add(21, E.PLAN_STARTED, block=2, level="beginner", reason="next_block")
    await a.add(22, E.WORKOUT_FINISHED, number=4)
    await a.add(5, E.ACCOUNT_LINKED, provider="google")
    await a.add(1.1, E.REMINDER_SET, days=3, hour=18)
    b = await _user(db_session, now, 30)  # one workout, in week 1
    await b.add(0.1, E.ONBOARDING_DONE)
    await b.add(2, E.WORKOUT_FINISHED, number=1)
    await b.add(3, E.DELETION_REQUESTED)
    c = await _user(db_session, now, 30)  # onboarding, then changed answers: not block 2
    await c.add(0.1, E.ONBOARDING_DONE)
    await c.add(1, E.PLAN_STARTED, block=2, level="beginner", reason="answers_changed")
    await _user(db_session, now, 30)  # signed up, nothing else
    # Signed up 2 days ago: in the funnel, but no retention week is over yet.
    d = await _user(db_session, now, 2)
    await d.add(0.5, E.ONBOARDING_DONE)
    # Signed up 200 days ago: outside the 90 days.
    old = await _user(db_session, now, 200)
    await old.add(1, E.ONBOARDING_DONE)
    await old.add(2, E.DELETION_CANCELLED)

    for reason, days_ago in [("privacy", 1), ("privacy", 10), ("no_time", 5), ("too_hard", 200)]:
        db_session.add(
            AccountDeletionReason(
                reason=LeavingReason(reason),
                was_guest=False,
                left_on=(now - timedelta(days=days_ago)).date(),
            )
        )
    await db_session.flush()
    return await reports.build_report(db_session, days=90)


def test_the_funnel(report: reports.Report) -> None:
    assert [(s.label, s.users) for s in report.funnel] == [
        ("Signed up", 5),
        ("Onboarding done", 4),
        ("Workout 1 finished", 2),
        ("Workout 2 finished", 1),
        ("Workout 3 finished", 1),
        ("Block 1 complete", 1),
        ("Block 2 started", 1),
    ]
    assert [None if s.kept is None else round(s.kept, 2) for s in report.funnel] == [
        None,
        0.8,
        0.5,
        0.5,
        1.0,
        1.0,
        1.0,
    ]


def test_weekly_retention(report: reports.Report) -> None:
    thirty_days, two_days = report.retention
    assert thirty_days.users == 4
    assert thirty_days.trained == {1: 0.5, 2: 0.25, 4: 0.25, 8: None}  # week 8: not yet
    assert two_days.users == 1
    assert two_days.trained == {1: None, 2: None, 4: None, 8: None}  # not over yet
    assert thirty_days.week_of.weekday() == 0  # Mondays


def test_other_counts_and_reasons(report: reports.Report) -> None:
    assert report.counts == {
        "Accounts linked (guest → Google/Apple)": 1,
        "Level-up offered (block complete)": 1,
        "Level-up accepted": 0,
        "Comebacks after a break": 0,
        "Deletions asked (Google/Apple)": 1,
        "Deletions cancelled": 0,  # the one cancel was 200 days ago
        "Reminders set or changed": 1,
        "Reminders turned off": 0,
    }
    assert report.reasons == {"privacy": 2, "no_time": 1}


def _lines(text: str) -> list[str]:
    """Each printed line with its column spacing squashed to single spaces."""
    return [" ".join(line.split()) for line in text.splitlines()]


def test_the_printed_report(report: reports.Report) -> None:
    lines = _lines(reports.render(report))

    assert "Lock In Mode funnel: people who signed up in the last 90 days" in lines
    assert "Onboarding done 4 80%" in lines
    assert "Workout 1 finished 2 50%" in lines
    assert any(line.endswith(" 4 50% 25% 25% …") for line in lines)
    assert any(line.endswith(" 1 … … … …") for line in lines)
    assert "Weekly lifecycle: who finished a workout each week (Monday, UTC)" in lines
    assert "* this week, so far" in lines
    assert "privacy 2" in lines


async def test_an_empty_database(db_session: AsyncSession) -> None:
    lines = _lines(reports.render(await reports.build_report(db_session, days=30)))

    assert "Signed up 0" in lines
    assert "Onboarding done 0 –" in lines
    assert "(nobody signed up in these days)" in lines
    assert "(none)" in lines


# --- protect your progress (ADR 0026) ---------------------------------------------------


async def test_offered_then_linked_within_7_days(db_session: AsyncSession) -> None:
    now = await db_session.scalar(select(func.now()))
    assert now is not None
    a = await _user(db_session, now, 40)  # linked 2 days after the workout 3 offer
    await a.add(1, E.SIGN_IN_OFFERED, milestone="workout_3", number=3)
    await a.add(3, E.ACCOUNT_LINKED, provider="google")
    b = await _user(db_session, now, 40)  # two offers: the link goes to the later one
    await b.add(1, E.SIGN_IN_OFFERED, milestone="workout_3", number=3)
    await b.add(10, E.SIGN_IN_OFFERED, milestone="workout_10", number=10)
    await b.add(12, E.ACCOUNT_LINKED, provider="apple")
    c = await _user(db_session, now, 40)  # linked 8 days later: not from the offer
    await c.add(1, E.SIGN_IN_OFFERED, milestone="workout_3", number=3)
    await c.add(9, E.ACCOUNT_LINKED, provider="google")
    d = await _user(db_session, now, 40)  # linked before any offer
    await d.add(2, E.ACCOUNT_LINKED, provider="google")
    await d.add(5, E.SIGN_IN_OFFERED, milestone="workout_3", number=3)
    e = await _user(db_session, now, 40)  # offered, never linked
    await e.add(20, E.SIGN_IN_OFFERED, milestone="first_block", number=12)
    f = await _user(db_session, now, 40)  # exactly 7 days still counts
    await f.add(20, E.SIGN_IN_OFFERED, milestone="first_block", number=9)
    await f.add(27, E.ACCOUNT_LINKED, provider="google")
    await _user(db_session, now, 40)  # never offered
    old = await _user(db_session, now, 200)  # signed up outside the 90 days
    await old.add(1, E.SIGN_IN_OFFERED, milestone="workout_3", number=3)
    await old.add(2, E.ACCOUNT_LINKED, provider="google")

    report = await reports.build_report(db_session, days=90)

    assert [(o.label, o.offered, o.linked) for o in report.offers] == [
        ("After workout 3", 4, 1),
        ("After workout 10", 1, 1),
        ("First block finished", 2, 1),
        ("Any offer", 6, 3),
    ]
    lines = _lines(reports.render(report))
    assert "Protect your progress: guests offered sign-in, linked within 7 days" in lines
    assert "After workout 3 4 1 25%" in lines
    assert "Any offer 6 3 50%" in lines


async def test_no_offers_yet(db_session: AsyncSession) -> None:
    report = await reports.build_report(db_session, days=30)

    assert all((o.offered, o.linked, o.rate) == (0, 0, None) for o in report.offers)
    assert "After workout 10 0 0 –" in _lines(reports.render(report))


# --- the weekly lifecycle (ADR 0034) -----------------------------------------------------

W = [date(2026, 11, 2) + timedelta(weeks=n) for n in range(8)]  # eight Mondays


def _active(**weeks: int) -> Counter[date]:
    """_active(w0=1, w3=2): 1 workout in week 0, 2 in week 3."""
    return Counter({W[int(key[1:])]: n for key, n in weeks.items()})


def test_every_kind_of_week() -> None:
    people = {
        uuid.uuid4(): _active(w5=1),  # new in week 5
        uuid.uuid4(): _active(w4=2, w5=2),  # current in week 5, kept it
        uuid.uuid4(): _active(w2=1, w5=1),  # back after 2 weeks away
        uuid.uuid4(): _active(w1=1, w5=3),  # back after 3 weeks away (still "1-3")
        uuid.uuid4(): _active(w0=1, w5=1),  # back after 4 weeks away
        uuid.uuid4(): _active(w4=1),  # went quiet in week 5
    }

    [week5] = reports.lifecycle(people, [W[5]])

    assert week5 == reports.WeekLife(
        week_of=W[5], trained=5, new=1, current=1, back_short=2, back_long=1, quiet=1, kept=2
    )


def test_the_lifecycle_covers_eight_weeks_up_to_this_one(report: reports.Report) -> None:
    weeks = [life.week_of for life in report.weeks]
    assert len(weeks) == 8
    assert all(w.weekday() == 0 for w in weeks)
    assert weeks == sorted(weeks)
    assert weeks[-1] == report.now.date() - timedelta(days=report.now.weekday())
    # User a trained 8 days after 30 days ago and again on day 22: someone trained.
    assert sum(life.trained for life in report.weeks) >= 2
