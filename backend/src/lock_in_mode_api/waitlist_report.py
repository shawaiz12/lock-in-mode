"""The waitlist report (ADR 0037), printed in the terminal:

    uv run python -m lock_in_mode_api.waitlist_report               # last 30 days
    uv run python -m lock_in_mode_api.waitlist_report --days 7
    uv run python -m lock_in_mode_api.waitlist_report --friends     # who each top one brought
    uv run python -m lock_in_mode_api.waitlist_report --csv list.csv  # everyone, for launch

It reads the database the settings point at (your .env), and only reads (the CSV is
written on your machine).

- On the list: everyone, and who joined in the last 7 days.
- By source: visits (one per browser per day), signups and the share of visitors who
  joined, per ?s= tag. Warm traffic (your bios) should join far more often than cold.
  Signups that came through a friend's link are counted on their own line.
- Where they train: the optional tap.
- The front of the line: the top `waitlist_top_spots`, who get the app before everyone else.
  Check them by hand before inviting (--friends lists who each one brought): a run of
  made-up emails is easy to spot.
"""

import argparse
import asyncio
import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Result, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core.config import settings
from lock_in_mode_api.models import WaitlistSignup, WaitlistVisit
from lock_in_mode_api.services import waitlist

NO_SOURCE = "(no tag)"
VIA_FRIEND = "(a friend's link)"


@dataclass(frozen=True)
class SourceRow:
    source: str
    visits: int | None  # None: not a page source (friends' links count as their own row)
    signups: int

    @property
    def rate(self) -> float | None:
        return self.signups / self.visits if self.visits else None


@dataclass(frozen=True)
class Front:
    position: int
    email: str
    friends: int
    joined_at: datetime
    friend_emails: tuple[str, ...]


@dataclass(frozen=True)
class Report:
    days: int
    on_list: int
    last_7_days: int
    sources: list[SourceRow]
    trains_at: dict[str, int]
    via_friend_share: float | None
    front: list[Front]


def _pairs(rows: Result[str, Any]) -> dict[str, int]:
    """Two-column rows → {first: second}. (dict(result) doesn't work: a Result has
    .keys(), the column names, so dict() mistakes it for a mapping.)"""
    return {key: int(value) for key, value in rows}


async def _sources(session: AsyncSession, since: datetime) -> list[SourceRow]:
    # "" for no tag, as in waitlist_visits. literal_column: one SQL expression, so GROUP BY
    # matches the SELECT (two bound '' parameters wouldn't).
    tag = func.coalesce(WaitlistSignup.source, literal_column("''")).label("tag")
    visits = _pairs(
        await session.execute(
            select(WaitlistVisit.source, func.sum(WaitlistVisit.visits))
            .where(WaitlistVisit.day >= since.date())
            .group_by(WaitlistVisit.source)
        )
    )
    signups = _pairs(
        await session.execute(
            select(tag, func.count())
            .where(WaitlistSignup.joined_at >= since, WaitlistSignup.referred_by_id.is_(None))
            .group_by(tag)
        )
    )
    via_friend = int(
        await session.scalar(
            select(func.count()).where(
                WaitlistSignup.joined_at >= since, WaitlistSignup.referred_by_id.is_not(None)
            )
        )
        or 0
    )
    rows = [
        SourceRow(source or NO_SOURCE, int(visits.get(source, 0)), int(signups.get(source, 0)))
        for source in sorted(set(visits) | set(signups), key=lambda s: (s == "", s))
    ]
    rows.sort(key=lambda r: -(r.visits or 0))
    if via_friend:
        rows.append(SourceRow(VIA_FRIEND, None, via_friend))
    return rows


async def _front(session: AsyncSession, limit: int) -> list[Front]:
    top = await waitlist.top(session, limit)
    ids = [signup.id for signup, _, _ in top]
    brought: dict[object, list[str]] = {i: [] for i in ids}
    rows = await session.execute(
        select(WaitlistSignup.referred_by_id, WaitlistSignup.email)
        .where(WaitlistSignup.referred_by_id.in_(ids))
        .order_by(WaitlistSignup.joined_at)
    )
    for referrer, email in rows:
        brought[referrer].append(email)
    return [
        Front(position, signup.email, friends, signup.joined_at, tuple(brought[signup.id]))
        for signup, position, friends in top
    ]


async def build_report(session: AsyncSession, days: int, now: datetime | None = None) -> Report:
    now = now or datetime.now().astimezone()
    since = now - timedelta(days=days)
    on_list = await waitlist.on_list(session)
    last_7 = int(
        await session.scalar(
            select(func.count()).where(WaitlistSignup.joined_at >= now - timedelta(days=7))
        )
        or 0
    )
    trains = {
        (place.value if place else "not answered"): int(n)
        for place, n in (
            await session.execute(
                select(WaitlistSignup.trains_at, func.count()).group_by(WaitlistSignup.trains_at)
            )
        )
    }
    via_friend = int(
        await session.scalar(select(func.count()).where(WaitlistSignup.referred_by_id.is_not(None)))
        or 0
    )
    return Report(
        days=days,
        on_list=on_list,
        last_7_days=last_7,
        sources=await _sources(session, since),
        trains_at=dict(sorted(trains.items(), key=lambda kv: -kv[1])),
        via_friend_share=via_friend / on_list if on_list else None,
        front=await _front(session, settings.waitlist_top_spots),
    )


def _pct(share: float | None) -> str:
    return "–" if share is None else f"{share:.0%}"


def render(report: Report, show_friends: bool = False) -> str:
    lines = [
        "Lock In Mode waitlist",
        f"On the list: {report.on_list}  (joined in the last 7 days: {report.last_7_days})",
        f"Joined through a friend's link: {_pct(report.via_friend_share)}",
        "",
        f"By source, last {report.days} days",
        f"  {'source':<20}{'visits':>8}{'joined':>8}{'rate':>7}",
    ]
    for row in report.sources:
        visits = "–" if row.visits is None else str(row.visits)
        lines.append(f"  {row.source:<20}{visits:>8}{row.signups:>8}{_pct(row.rate):>7}")
    if not report.sources:
        lines.append("  nothing yet")
    lines += ["", "Where they train"]
    lines += [f"  {place:<20}{n:>8}" for place, n in report.trains_at.items()] or ["  nobody yet"]
    lines += [
        "",
        f"The front of the line (top {settings.waitlist_top_spots} get early access)",
    ]
    for f in report.front:
        lines.append(f"  #{f.position:<4}{f.email:<40}{f.friends:>3} friends  {f.joined_at:%d %b}")
        if show_friends:
            lines += [f"         ↳ {email}" for email in f.friend_emails]
    if not report.front:
        lines.append("  nobody yet")
    return "\n".join(lines)


async def write_csv(session: AsyncSession, path: Path) -> int:
    """Everyone on the list, front of the line first. Returns how many rows."""
    everyone = await waitlist.top(session, limit=1_000_000)
    with path.open("w", newline="", encoding="utf-8") as file:
        out = csv.writer(file)
        out.writerow(["position", "email", "friends", "trains_at", "source", "joined_at"])
        for signup, position, friends in everyone:
            out.writerow(
                [
                    position,
                    signup.email,
                    friends,
                    signup.trains_at.value if signup.trains_at else "",
                    signup.source or "",
                    signup.joined_at.isoformat(),
                ]
            )
    return len(everyone)


async def _main(days: int, show_friends: bool, csv_path: Path | None) -> None:
    from lock_in_mode_api.core.db import SessionLocal, engine

    async with SessionLocal() as session:
        print(render(await build_report(session, days), show_friends))
        if csv_path is not None:
            count = await write_csv(session, csv_path)
            print(f"\nWrote {count} people to {csv_path}")
    await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Lock In Mode waitlist report (ADR 0037)")
    parser.add_argument("--days", type=int, default=30, help="days for the by-source table")
    parser.add_argument("--friends", action="store_true", help="list who each top person brought")
    parser.add_argument("--csv", type=Path, help="also write everyone to this CSV file")
    args = parser.parse_args(argv)
    asyncio.run(_main(args.days, args.friends, args.csv))


if __name__ == "__main__":
    main()
