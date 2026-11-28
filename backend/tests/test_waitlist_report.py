"""The waitlist report (ADR 0037) on a small, hand-made list with known answers."""

import csv
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api import waitlist_report as report
from lock_in_mode_api.core.config import settings
from lock_in_mode_api.models import WaitlistSignup, WaitlistVisit
from lock_in_mode_api.models.enums import TrainsAt
from lock_in_mode_api.services import waitlist

NOW = datetime(2026, 12, 10, 12, 0, tzinfo=UTC)


async def _signup(
    db: AsyncSession,
    email: str,
    days_ago: float,
    *,
    source: str | None = None,
    trains_at: TrainsAt | None = None,
    by: WaitlistSignup | None = None,
) -> WaitlistSignup:
    row = WaitlistSignup(
        email=email,
        referral_code=waitlist.new_code(),
        key_hash=email.ljust(64, "x")[:64],
        source=source,
        trains_at=trains_at,
        referred_by_id=by.id if by else None,
        joined_at=NOW - timedelta(days=days_ago),
    )
    db.add(row)
    await db.flush()
    return row


@pytest.fixture
async def history(db_session: AsyncSession) -> None:
    ali = await _signup(db_session, "ali@gmail.com", 20, source="tiktok", trains_at=TrainsAt.GYM)
    await _signup(db_session, "sara@gmail.com", 10, source="tiktok", trains_at=TrainsAt.HOME)
    await _signup(db_session, "zed@gmail.com", 3, trains_at=TrainsAt.GYM)
    await _signup(db_session, "f1@gmail.com", 2, by=ali)
    await _signup(db_session, "f2@gmail.com", 1, source="tiktok", by=ali)  # a friend: not tiktok
    await _signup(db_session, "old@gmail.com", 60, source="instagram")  # outside 30 days
    db_session.add_all(
        [
            WaitlistVisit(day=date(2026, 12, 1), source="tiktok", visits=30),
            WaitlistVisit(day=date(2026, 12, 9), source="tiktok", visits=10),
            WaitlistVisit(day=date(2026, 12, 9), source="", visits=4),
            WaitlistVisit(day=date(2026, 10, 1), source="instagram", visits=99),  # too old
        ]
    )
    await db_session.flush()


@pytest.mark.usefixtures("history")
async def test_the_report_counts_the_list_and_the_sources(db_session: AsyncSession) -> None:
    built = await report.build_report(db_session, days=30, now=NOW)

    assert built.on_list == 6
    assert built.last_7_days == 3
    assert built.via_friend_share == pytest.approx(2 / 6)
    rows = {r.source: r for r in built.sources}
    assert (rows["tiktok"].visits, rows["tiktok"].signups) == (40, 2)
    assert rows["tiktok"].rate == pytest.approx(0.05)
    assert (rows[report.NO_SOURCE].visits, rows[report.NO_SOURCE].signups) == (4, 1)
    assert (rows[report.VIA_FRIEND].visits, rows[report.VIA_FRIEND].signups) == (None, 2)
    assert "instagram" not in rows
    assert built.trains_at == {"not answered": 3, "gym": 2, "home": 1}


@pytest.mark.usefixtures("history")
async def test_the_front_of_the_line_lists_who_each_one_brought(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "waitlist_top_spots", 3)

    built = await report.build_report(db_session, days=30, now=NOW)

    assert [(f.position, f.email, f.friends) for f in built.front] == [
        (1, "ali@gmail.com", 2),
        (2, "old@gmail.com", 0),
        (3, "sara@gmail.com", 0),
    ]
    assert built.front[0].friend_emails == ("f1@gmail.com", "f2@gmail.com")
    text = report.render(built, show_friends=True)
    assert "On the list: 6" in text
    assert "↳ f2@gmail.com" in text
    assert "↳" not in report.render(built)


async def test_an_empty_list_renders(db_session: AsyncSession) -> None:
    text = report.render(await report.build_report(db_session, days=30, now=NOW))

    assert "On the list: 0" in text
    assert "nothing yet" in text


@pytest.mark.usefixtures("history")
async def test_the_csv_has_everyone_front_first(db_session: AsyncSession, tmp_path: Path) -> None:
    path = tmp_path / "list.csv"

    assert await report.write_csv(db_session, path) == 6

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [r["email"] for r in rows][:2] == ["ali@gmail.com", "old@gmail.com"]
    assert rows[0]["friends"] == "2"
    assert rows[0]["trains_at"] == "gym"
    assert rows[0]["source"] == "tiktok"
