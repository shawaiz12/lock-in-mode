"""The waitlist (ADR 0037): joining, your spot in line, leaving, counting visits.

The line, worked out on every read (nothing stored can go stale):

    1. more friends joined with your link → ahead
    2. same number of friends → whoever joined first is ahead

So one friend moves you ahead of everyone with none. Friends are counted only while they
are on the list: someone who leaves stops counting for whoever brought them.
"""

import re
import secrets
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, Select, delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.security import hash_refresh_token
from lock_in_mode_api.models import WaitlistSignup, WaitlistVisit
from lock_in_mode_api.models.enums import TrainsAt
from lock_in_mode_api.models.waitlist import CODE_ALPHABET, CODE_LENGTH, SOURCE_PATTERN

_CODE = re.compile(f"^[{CODE_ALPHABET}]{{{CODE_LENGTH}}}$")
_SOURCE = re.compile(SOURCE_PATTERN)
# A brand-new code clashing with an existing one is about 1 in 10^11 per signup; three
# tries make a failure practically impossible without hiding a real bug in a loop.
_CODE_TRIES = 3


class NotOnWaitlistError(Exception):
    """No one has this code or key."""


@dataclass(frozen=True)
class Spot:
    referral_code: str
    position: int
    friends_joined: int
    on_list: int

    @property
    def in_top(self) -> bool:
        return self.position <= settings.waitlist_top_spots


@dataclass(frozen=True)
class Joined:
    spot: Spot
    already_on_list: bool
    key: str | None  # only for a new signup: shown to them once, stored as a hash


def clean_code(raw: str | None) -> str | None:
    """A link code as pasted ("ab12cd34 ", "AB12CD34") → "AB12CD34", or None if it can't
    be one. Nothing else reaches the database."""
    if raw is None:
        return None
    code = raw.strip().upper()
    return code if _CODE.match(code) else None


def clean_source(raw: str | None) -> str | None:
    """?s=TikTok → "tiktok". Anything that isn't a short plain tag is dropped."""
    if raw is None:
        return None
    source = raw.strip().lower()
    return source if _SOURCE.match(source) else None


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _friends() -> ColumnElement[int]:
    """How many people on the list joined with this signup's link."""
    friend = aliased(WaitlistSignup)
    return (
        select(func.count())
        .where(friend.referred_by_id == WaitlistSignup.id)
        .correlate(WaitlistSignup)
        .scalar_subquery()
    )


def _line() -> Select[Any]:
    """Everyone with their spot: (code, position, friends, everyone on the list)."""
    friends = _friends().label("friends")
    counted = select(
        WaitlistSignup.referral_code, WaitlistSignup.joined_at, WaitlistSignup.id, friends
    ).subquery()
    position = (
        func.row_number()
        .over(order_by=(counted.c.friends.desc(), counted.c.joined_at, counted.c.id))
        .label("position")
    )
    return select(
        counted.c.referral_code,
        position,
        counted.c.friends,
        func.count().over().label("on_list"),
    )


async def spot(session: AsyncSession, code: str) -> Spot:
    line = _line().subquery()
    row = (await session.execute(select(line).where(line.c.referral_code == code))).one_or_none()
    if row is None:
        raise NotOnWaitlistError
    return Spot(
        referral_code=row.referral_code,
        position=int(row.position),
        friends_joined=int(row.friends),
        on_list=int(row.on_list),
    )


async def top(session: AsyncSession, limit: int) -> list[tuple[WaitlistSignup, int, int]]:
    """The front of the line, for the report: (signup, position, friends)."""
    line = _line().subquery()
    rows = await session.execute(
        select(WaitlistSignup, line.c.position, line.c.friends)
        .join(line, line.c.referral_code == WaitlistSignup.referral_code)
        .order_by(line.c.position)
        .limit(limit)
    )
    return [(signup, int(position), int(friends)) for signup, position, friends in rows]


async def join(
    session: AsyncSession,
    email: str,
    trains_at: TrainsAt | None,
    ref: str | None,
    source: str | None,
) -> Joined:
    """Put someone on the list, or find them if they're on it already.

    Already on it: their spot, no key, nothing changed (not even "where do you train"),
    so typing someone else's email can't rewrite their answers or who brought them.
    """
    referrer = None
    if (code := clean_code(ref)) is not None:
        referrer = await session.scalar(
            select(WaitlistSignup.id).where(WaitlistSignup.referral_code == code)
        )
    for _ in range(_CODE_TRIES):
        key = secrets.token_urlsafe(32)
        referral_code = new_code()
        new_id = await session.scalar(
            insert(WaitlistSignup)
            .values(
                email=email,
                referral_code=referral_code,
                key_hash=hash_refresh_token(key),
                referred_by_id=referrer,
                trains_at=trains_at,
                source=clean_source(source),
            )
            # Any unique column: the email (already on the list) or, very rarely, a code.
            .on_conflict_do_nothing()
            .returning(WaitlistSignup.id)
        )
        if new_id is not None:
            await session.commit()
            return Joined(await spot(session, referral_code), already_on_list=False, key=key)
        existing = await session.scalar(
            select(WaitlistSignup.referral_code).where(WaitlistSignup.email == email)
        )
        if existing is not None:
            return Joined(await spot(session, existing), already_on_list=True, key=None)
    raise RuntimeError("Couldn't find a free waitlist code")  # pragma: no cover


async def leave(session: AsyncSession, key: str) -> None:
    """Off the list for good: the row is deleted, and their friends stop counting for
    them (the friends stay on the list)."""
    removed = await session.scalar(
        delete(WaitlistSignup)
        .where(WaitlistSignup.key_hash == hash_refresh_token(key))
        .returning(WaitlistSignup.id)
    )
    if removed is None:
        raise NotOnWaitlistError
    await session.commit()


async def count_visit(session: AsyncSession, source: str | None) -> None:
    """One more page view today (UTC) for this source. The page sends it once per
    browser per day, so it's close to "people who opened the page"."""
    today: ColumnElement[date] = literal_column("(now() AT TIME ZONE 'UTC')::date")
    stmt = insert(WaitlistVisit).values(day=today, source=clean_source(source) or "", visits=1)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[WaitlistVisit.day, WaitlistVisit.source],
            set_={"visits": WaitlistVisit.visits + 1},
        )
    )
    await session.commit()


async def on_list(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(WaitlistSignup)) or 0)


def shown_count(total: int) -> int | None:
    """The count the page may show: the real number, from `waitlist_count_shown_from`."""
    return total if total >= settings.waitlist_count_shown_from else None
