"""The waitlist API (ADR 0037): joining, the line, leaving, the count, visits, limits."""

import re

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.core.config import settings
from lock_in_mode_api.core.security import hash_refresh_token
from lock_in_mode_api.models import WaitlistSignup, WaitlistVisit
from lock_in_mode_api.models.enums import TrainsAt
from lock_in_mode_api.services import waitlist as service

URL = "/api/v1/waitlist"


async def _join(client: AsyncClient, email: str, **extra: object) -> dict[str, object]:
    response = await client.post(URL, json={"email": email, **extra})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


async def _spot(client: AsyncClient, code: object) -> dict[str, object]:
    response = await client.get(f"{URL}/{code}")
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def _row(db: AsyncSession, email: str) -> WaitlistSignup:
    row = await db.scalar(select(WaitlistSignup).where(WaitlistSignup.email == email))
    assert row is not None
    return row


# --- joining ---------------------------------------------------------------------------


async def test_joining_gives_a_spot_a_link_code_and_a_private_key(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    body = await _join(client, "  Ali@Gmail.COM ", trains_at="gym", source="TikTok")

    assert body["position"] == 1
    assert body["on_list"] == 1
    assert body["friends_joined"] == 0
    assert body["already_on_list"] is False
    assert body["in_top"] is True
    assert body["top_spots"] == settings.waitlist_top_spots
    assert re.fullmatch(r"[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{8}", str(body["referral_code"]))
    row = await _row(db_session, "ali@gmail.com")  # trimmed and lower-cased
    assert row.trains_at is TrainsAt.GYM
    assert row.source == "tiktok"
    assert row.referral_code == body["referral_code"]
    # Only the key's hash is stored, never the key.
    assert row.key_hash == hash_refresh_token(str(body["key"]))
    assert row.key_hash != body["key"]


async def test_the_same_email_again_gets_its_spot_without_a_key_and_changes_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await _join(client, "sara@gmail.com", trains_at="home")
    other = await _join(client, "other@gmail.com")

    response = await client.post(
        URL, json={"email": "SARA@gmail.com", "trains_at": "gym", "ref": other["referral_code"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["already_on_list"] is True
    assert body["key"] is None
    assert body["referral_code"] == first["referral_code"]
    row = await _row(db_session, "sara@gmail.com")
    assert row.trains_at is TrainsAt.HOME  # not rewritten by whoever typed the email
    assert row.referred_by_id is None
    assert (await _spot(client, other["referral_code"]))["friends_joined"] == 0


async def test_trains_at_is_optional(client: AsyncClient, db_session: AsyncSession) -> None:
    await _join(client, "no-answer@gmail.com")

    assert (await _row(db_session, "no-answer@gmail.com")).trains_at is None


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email"},
        {"email": ""},
        {},
        {"email": "a@b.co", "trains_at": "moon"},
        {"email": "a@b.co", "position": 1},  # nothing extra can be sent
    ],
)
async def test_bad_signups_are_validation_errors(
    client: AsyncClient, db_session: AsyncSession, body: dict[str, object]
) -> None:
    response = await client.post(URL, json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert await service.on_list(db_session) == 0


async def test_an_unknown_or_odd_friend_code_is_ignored(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _join(client, "a@gmail.com", ref="ZZZZZZZZ")
    await _join(client, "b@gmail.com", ref="<script>")

    assert (await _row(db_session, "a@gmail.com")).referred_by_id is None
    assert (await _row(db_session, "b@gmail.com")).referred_by_id is None


@pytest.mark.parametrize("source", ["Instagram Bio!", "x" * 40, "../etc", ""])
async def test_a_source_that_isnt_a_plain_tag_is_dropped(
    client: AsyncClient, db_session: AsyncSession, source: str
) -> None:
    await _join(client, "s@gmail.com", source=source)

    assert (await _row(db_session, "s@gmail.com")).source is None


# --- the line --------------------------------------------------------------------------


async def test_a_friend_joining_with_your_link_moves_you_ahead(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    first = await _join(client, "first@gmail.com")
    second = await _join(client, "second@gmail.com")
    third = await _join(client, "third@gmail.com")
    assert [
        (await _spot(client, x["referral_code"]))["position"] for x in (first, second, third)
    ] == [
        1,
        2,
        3,
    ]

    # The code works in any case, as typed from a screenshot.
    friend = await _join(client, "friend@gmail.com", ref=str(third["referral_code"]).lower())

    assert (await _row(db_session, "friend@gmail.com")).referred_by_id == (
        await _row(db_session, "third@gmail.com")
    ).id
    third_now = await _spot(client, third["referral_code"])
    assert third_now["position"] == 1
    assert third_now["friends_joined"] == 1
    assert third_now["on_list"] == 4
    # Same friends (none): whoever joined first is ahead.
    assert (await _spot(client, first["referral_code"]))["position"] == 2
    assert (await _spot(client, second["referral_code"]))["position"] == 3
    assert (await _spot(client, friend["referral_code"]))["position"] == 4


async def test_more_friends_beat_fewer_and_ties_go_to_who_joined_first(
    client: AsyncClient,
) -> None:
    a = await _join(client, "a@gmail.com")
    b = await _join(client, "b@gmail.com")
    for n in range(2):
        await _join(client, f"b-friend-{n}@gmail.com", ref=b["referral_code"])
    await _join(client, "a-friend@gmail.com", ref=a["referral_code"])
    c = await _join(client, "c@gmail.com")
    await _join(client, "c-friend@gmail.com", ref=c["referral_code"])

    assert (await _spot(client, b["referral_code"]))["position"] == 1  # 2 friends
    assert (await _spot(client, a["referral_code"]))["position"] == 2  # 1, joined before c
    assert (await _spot(client, c["referral_code"]))["position"] == 3  # 1


async def test_in_top_follows_the_top_spots_setting(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "waitlist_top_spots", 1)
    first = await _join(client, "first@gmail.com")
    second = await _join(client, "second@gmail.com")

    assert first["in_top"] is True
    assert second["in_top"] is False
    assert second["top_spots"] == 1


@pytest.mark.parametrize("code", ["ZZZZZZZZ", "short", "0OIL0OIL", "toolongcode1"])
async def test_a_code_nobody_has_is_not_found(client: AsyncClient, code: str) -> None:
    response = await client.get(f"{URL}/{code}")

    assert response.status_code == 404
    assert response.json()["code"] == "waitlist_entry_not_found"


# --- leaving ---------------------------------------------------------------------------


async def test_leaving_deletes_you_and_your_friends_stay_without_you(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    leaver = await _join(client, "leaver@gmail.com")
    friend = await _join(client, "friend@gmail.com", ref=leaver["referral_code"])
    stayer = await _join(client, "stayer@gmail.com")
    await _join(client, "stayer-friend@gmail.com", ref=stayer["referral_code"])

    response = await client.post(f"{URL}/leave", json={"key": leaver["key"]})

    assert response.status_code == 204
    assert (
        await db_session.scalar(
            select(WaitlistSignup).where(WaitlistSignup.email == "leaver@gmail.com")
        )
        is None
    )
    assert (await _row(db_session, "friend@gmail.com")).referred_by_id is None
    assert (await client.get(f"{URL}/{leaver['referral_code']}")).status_code == 404
    assert (await _spot(client, friend["referral_code"]))["on_list"] == 3
    # Leaving again, or with a made-up key: not found, nothing else touched.
    again = await client.post(f"{URL}/leave", json={"key": leaver["key"]})
    assert again.status_code == 404
    assert again.json()["code"] == "waitlist_entry_not_found"
    assert await service.on_list(db_session) == 3


async def test_the_link_code_is_not_the_key(client: AsyncClient, db_session: AsyncSession) -> None:
    """Anyone with your share link knows your code: it must never remove you."""
    me = await _join(client, "me@gmail.com")

    response = await client.post(f"{URL}/leave", json={"key": str(me["referral_code"]) * 3})

    assert response.status_code == 404
    assert await service.on_list(db_session) == 1


async def test_a_friend_who_leaves_stops_counting(client: AsyncClient) -> None:
    me = await _join(client, "me@gmail.com")
    friend = await _join(client, "friend@gmail.com", ref=me["referral_code"])
    assert (await _spot(client, me["referral_code"]))["friends_joined"] == 1

    await client.post(f"{URL}/leave", json={"key": friend["key"]})

    assert (await _spot(client, me["referral_code"]))["friends_joined"] == 0


# --- the count -------------------------------------------------------------------------


async def test_the_count_stays_hidden_until_the_list_is_big_enough(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "waitlist_count_shown_from", 2)
    await _join(client, "one@gmail.com")
    hidden = (await client.get(f"{URL}/count")).json()
    await _join(client, "two@gmail.com")
    shown = (await client.get(f"{URL}/count")).json()

    assert hidden["count"] is None
    assert shown["count"] == 2  # the real number, never padded
    assert shown["founding_discount_percent"] == settings.waitlist_founding_discount_percent
    assert shown["top_spots"] == settings.waitlist_top_spots


# --- visits ----------------------------------------------------------------------------


async def test_visits_are_counted_per_day_and_source(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    for source in ("TikTok", "tiktok", None, "not a tag!"):
        response = await client.post(f"{URL}/visits", json={"source": source})
        assert response.status_code == 204
    await client.post(f"{URL}/visits", json={})

    rows = {
        source: n
        for source, n in await db_session.execute(
            select(WaitlistVisit.source, WaitlistVisit.visits)
        )
    }
    assert rows == {"tiktok": 2, "": 3}


# --- limits ----------------------------------------------------------------------------


async def test_joins_per_ip_per_hour_are_limited(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "waitlist_joins_per_ip_per_hour", 2)
    await _join(client, "one@gmail.com")
    await _join(client, "two@gmail.com")

    response = await client.post(URL, json={"email": "three@gmail.com"})

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert int(response.headers["Retry-After"]) > 0
    assert await service.on_list(db_session) == 2


async def test_joins_per_minute_are_limited(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "auth_rate_limit_per_minute", 1)
    await _join(client, "one@gmail.com")

    response = await client.post(URL, json={"email": "two@gmail.com"})

    assert response.status_code == 429


# --- the rules, without HTTP -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [("ab23cd45", "AB23CD45"), (" AB23CD45 ", "AB23CD45"), ("AB23CD4", None), ("AB23CD40", None)],
)
def test_clean_code(raw: str, clean: str | None) -> None:
    assert service.clean_code(raw) == clean


def test_new_codes_have_the_right_shape() -> None:
    codes = {service.new_code() for _ in range(200)}

    assert len(codes) == 200
    assert all(service.clean_code(code) == code for code in codes)


def test_shown_count_needs_the_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "waitlist_count_shown_from", 100)

    assert service.shown_count(99) is None
    assert service.shown_count(100) == 100
