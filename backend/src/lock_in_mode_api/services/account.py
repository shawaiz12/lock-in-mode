"""Deleting an account (ADR 0024).

- Guests are erased at once: they could never sign back in to cancel.
- Google/Apple accounts wait 30 days, signed out everywhere. Signing in cancels.
- Erasing = deleting the `users` row. Every user table has ON DELETE CASCADE, so one
  statement takes the profile, plans, workouts, sets, progress, swaps, comebacks and
  tokens with it.
- The optional leaving reason is copied to `account_deletion_reasons` (no user id) only
  when the account is really erased.
- Lost guests (ADR 0027): a guest with no usable refresh token left (expired, signed out,
  or locked after a stolen token was reused) can never get back in, so the hourly cleanup
  erases them too.

Every time comparison here uses the database clock (`now()`), never the app's.
Functions that take a request's session own the transaction and commit (like the other
services); `erase_due_now` is a building block that leaves committing to its caller.
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime

from sqlalchemy import ColumnElement, Row, delete, exists, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core.db import SessionLocal
from lock_in_mode_api.models import AccountDeletionReason, RefreshToken, User
from lock_in_mode_api.models.enums import LeavingReason
from lock_in_mode_api.services import events

logger = logging.getLogger(__name__)

DELETION_GRACE_DAYS = 30  # shown to users: "deleted on <date>"
# make_interval(years, months, weeks, days): the 30 days as a Postgres interval.
GRACE = func.make_interval(0, 0, 0, DELETION_GRACE_DAYS)
CLEANUP_BATCH = 200  # accounts per transaction: one account can own thousands of set logs
# Lost guests (ADR 0027): a token's expiry was set by the app's clock, the check uses the
# database's; a day's margin keeps a small difference between them from mattering.
LOST_GUEST_MARGIN = func.make_interval(0, 0, 0, 1)


def _left_on(asked_at: datetime) -> date:
    """The UTC day a deletion was asked for."""
    return asked_at.astimezone(UTC).date()


async def _keep_reasons(
    session: AsyncSession, gone: Sequence[Row[LeavingReason | None, bool, datetime | None]]
) -> None:
    """Save the reasons of erased accounts. Row = (reason, was_guest, when they asked).

    `when they asked` is never None here: only waiting accounts are erased this way.
    """
    rows = [
        {"reason": reason, "was_guest": was_guest, "left_on": _left_on(asked_at)}
        for reason, was_guest, asked_at in gone
        if reason is not None and asked_at is not None
    ]
    if rows:
        await session.execute(insert(AccountDeletionReason), rows)


async def erase_due_now(
    session: AsyncSession, *, only: ColumnElement[bool] | None = None, limit: int = CLEANUP_BATCH
) -> int:
    """Erase up to `limit` accounts whose 30 days are over. Doesn't commit.

    `only` narrows it to one account, e.g. `User.google_sub == sub` at sign-in, so a
    sleeping server's late cleanup can never bring an account back.

    SKIP LOCKED: an account that another transaction is busy with (a sign-in) is left
    for the next run instead of making this one wait.
    """
    due = select(User.id).where(User.delete_after <= func.now())
    if only is not None:
        due = due.where(only)
    due = due.order_by(User.delete_after).limit(limit).with_for_update(skip_locked=True)

    asked_at = User.delete_after - GRACE
    gone = (
        await session.execute(
            delete(User)
            .where(User.id.in_(due.scalar_subquery()))
            .returning(User.deletion_reason, User.is_guest, asked_at)
        )
    ).all()
    await _keep_reasons(session, gone)
    return len(gone)


async def purge_due(session: AsyncSession, *, batch: int = CLEANUP_BATCH) -> int:
    """The cleanup: erase every account whose 30 days are over, one batch per commit."""
    total = 0
    while True:
        erased = await erase_due_now(session, limit=batch)
        await session.commit()
        total += erased
        if erased < batch:
            return total


def _can_get_back_in() -> ColumnElement[bool]:
    """The user has a refresh token that still works: unused (the newest of its family),
    not revoked, and not expired (with the margin)."""
    return exists().where(
        RefreshToken.user_id == User.id,
        RefreshToken.used_at.is_(None),
        RefreshToken.revoked_at.is_(None),
        RefreshToken.expires_at > func.now() - LOST_GUEST_MARGIN,
    )


async def erase_lost_guests(session: AsyncSession, *, limit: int = CLEANUP_BATCH) -> int:
    """Erase up to `limit` guests nobody can ever open again (ADR 0027). Doesn't commit.

    A guest made in the last day is never touched: its first token is written in the same
    transaction, but the margin keeps this rule from depending on that.
    """
    lost = (
        select(User.id)
        .where(
            User.is_guest,
            User.created_at < func.now() - LOST_GUEST_MARGIN,
            ~_can_get_back_in(),
        )
        .order_by(User.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    gone = await session.execute(
        delete(User).where(User.id.in_(lost.scalar_subquery())).returning(User.id)
    )
    return len(gone.all())


async def purge_lost_guests(session: AsyncSession, *, batch: int = CLEANUP_BATCH) -> int:
    """The cleanup's second job: erase every lost guest, one batch per commit."""
    total = 0
    while True:
        erased = await erase_lost_guests(session, limit=batch)
        await session.commit()
        total += erased
        if erased < batch:
            return total


async def delete_guest(session: AsyncSession, user: User, reason: LeavingReason | None) -> None:
    """A guest asked: erase it now."""
    asked_at: datetime = (
        await session.execute(delete(User).where(User.id == user.id).returning(func.now()))
    ).scalar_one()
    if reason is not None:
        await session.execute(
            insert(AccountDeletionReason).values(
                reason=reason, was_guest=True, left_on=_left_on(asked_at)
            )
        )
    await session.commit()
    session.expunge(user)  # the row is gone; don't let the session try to refresh it


async def schedule_deletion(
    session: AsyncSession, user: User, reason: LeavingReason | None
) -> datetime:
    """A Google/Apple account asked: erase it in 30 days and sign it out everywhere."""
    delete_after: datetime | None = (
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                delete_after=func.now() + GRACE,
                deletion_reason=reason,
            )
            .returning(User.delete_after)
        )
    ).scalar_one()
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    await events.deletion_requested(session, user.id)
    await session.commit()
    assert delete_after is not None  # just set above
    return delete_after


async def cancel_deletion(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Signing in again: keep the account. True if a deletion was waiting. Doesn't commit.

    Call `erase_due_now` for the same account first in the same transaction: then any
    account still waiting here is one whose 30 days aren't over.
    """
    cancelled = await session.scalar(
        update(User)
        .where(User.id == user_id, User.delete_after.is_not(None))
        .values(delete_after=None, deletion_reason=None)
        .returning(User.id)
    )
    return cancelled is not None


# --- the hourly cleanup: in the API process, or a scheduled job (ADR 0031) -----------


async def cleanup_once() -> tuple[int, int]:
    """Erase due accounts and lost guests, once. Returns (accounts, lost guests).

    The hosted API (Vercel, ADR 0031) only runs while it answers a request, so there an
    hourly GitHub Actions job calls this through `python -m lock_in_mode_api.cleanup`.
    Anywhere the API runs all the time, `run_cleanup` below calls it every hour instead.
    """
    async with SessionLocal() as session:
        erased = await purge_due(session)
        lost = await purge_lost_guests(session)
    if erased:
        logger.info("Account cleanup: erased %d account(s)", erased)
    if lost:
        logger.info("Account cleanup: erased %d lost guest(s)", lost)
    return erased, lost


async def run_cleanup(
    interval_seconds: float, *, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
) -> None:
    """Erase due accounts and lost guests now, then every `interval_seconds`, until
    cancelled.

    Runs in the API process (no cron job, no worker: no extra cost). A failed run is
    logged and tried again next time; it never stops the API. (`sleep` is for tests.)
    """
    while True:
        try:
            await cleanup_once()
        except Exception:
            logger.exception("Account cleanup failed; trying again in %ss", interval_seconds)
        await sleep(interval_seconds)
