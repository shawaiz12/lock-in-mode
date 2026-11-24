"""Deleting an account through the API (ADR 0024): guests erased at once, Google/Apple
accounts after 30 days and signed out everywhere, signing in cancels, a late cleanup can't
bring an account back, the leaving reason kept with no link to the person.

The 30 days are faked by moving `users.delete_after` back (`_due`). Inside a test the
database clock stands still (one transaction), so `now()` in the test equals the API's.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import Table, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import (
    AccountDeletionReason,
    Base,
    Comeback,
    RefreshToken,
    SetLog,
    User,
    WorkoutSession,
)
from lock_in_mode_api.models.enums import LeavingReason
from lock_in_mode_api.schemas.auth import TokenPair
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.services import account
from lock_in_mode_api.training.plan_types import is_weighted

type MakeIdToken = Callable[..., str]
type Headers = dict[str, str]
type Json = dict[str, Any]

ME = "/api/v1/me"
SESSIONS = "/api/v1/sessions"
CURRENT = "/api/v1/plans/current"
ALL_NO = {
    "heart_condition": False,
    "chest_pain_when_active": False,
    "pregnant": False,
    "recent_surgery_or_injury": False,
}
# Gym, 3 days of 45 minutes: strength workouts carry a finisher (intervals, ADR 0023).
GYM: Json = {
    "goal": "lose_fat",
    "level": "some_experience",
    "location": "gym",
    "days_per_week": 3,
    "minutes_per_session": 45,
}
LIBRARY = {e.slug: e for e in load_library().exercises}


def _auth(tokens: TokenPair) -> Headers:
    return {"Authorization": f"Bearer {tokens.access_token}"}


async def _guest(client: AsyncClient) -> TokenPair:
    response = await client.post("/api/v1/auth/guest")
    assert response.status_code == 201
    return TokenPair.model_validate(response.json())


async def _google(client: AsyncClient, id_token: str) -> TokenPair:
    response = await client.post("/api/v1/auth/google", json={"id_token": id_token})
    assert response.status_code == 200, response.text
    return TokenPair.model_validate(response.json())


async def _user_id(client: AsyncClient, tokens: TokenPair) -> str:
    response = await client.get(ME, headers=_auth(tokens))
    assert response.status_code == 200
    return str(response.json()["id"])


async def _delete(client: AsyncClient, tokens: TokenPair, reason: str | None = None) -> Any:
    params = {} if reason is None else {"reason": reason}
    return await client.delete(ME, headers=_auth(tokens), params=params)


async def _users(db: AsyncSession) -> list[User]:
    result = await db.scalars(select(User).execution_options(populate_existing=True))
    return list(result.all())


async def _reasons(db: AsyncSession) -> list[AccountDeletionReason]:
    return list((await db.scalars(select(AccountDeletionReason))).all())


async def _db_now(db: AsyncSession) -> datetime:
    now: datetime | None = await db.scalar(select(func.now()))
    assert now is not None
    return now


async def _due(db: AsyncSession) -> None:
    """Pretend the 30 days of every waiting account are over (by one second)."""
    await db.execute(
        update(User)
        .where(User.delete_after.is_not(None))
        .values(delete_after=func.now() - text("interval '1 second'"))
    )
    await db.flush()
    db.expire_all()


# --- a user with a row in every table that belongs to a user ----------------------------


def _user_tables() -> list[Table]:
    """Every table that leads to `users` through foreign keys (directly or not)."""
    reaches: set[str] = {"users"}
    changed = True
    while changed:
        changed = False
        for table in Base.metadata.sorted_tables:
            if table.name in reaches:
                continue
            if any(fk.column.table.name in reaches for fk in table.foreign_keys):
                reaches.add(table.name)
                changed = True
    return [t for t in Base.metadata.sorted_tables if t.name in reaches]


def test_the_user_tables_are_the_ones_we_expect() -> None:
    """A new user table must be added here AND to `_full_user`, so deletion is tested on it."""
    assert {t.name for t in _user_tables()} == {
        "users",
        "profiles",
        "refresh_tokens",
        "plans",
        "planned_workouts",
        "planned_exercises",
        "workout_sessions",
        "set_logs",
        "movement_rungs",
        "exercise_targets",
        "interval_steps",
        "swapped_out_exercises",
        "comebacks",
    }


def _values(row: Json) -> Json:
    """A set of this row at its top, with a weight where one fits."""
    values: Json = (
        {"seconds": row["seconds"]}
        if row["seconds"]
        else {"reps": row["reps_max"] or row["reps_min"] or 10}
    )
    if is_weighted(LIBRARY[row["exercise"]["slug"]]):
        values["weight_kg"] = row["weight_kg"] or 20.0
    return values


async def _train(client: AsyncClient, headers: Headers) -> Json:
    """Do the next workout: every set of the main block and the finisher."""
    workout = dict((await client.get(f"{CURRENT}/next", headers=headers)).json())
    started = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    assert started.status_code in (200, 201), started.text
    session_id = started.json()["id"]
    for row in workout["main"] + workout["finisher"]:
        if row["swapped_out"]:
            continue
        for n in range(1, row["sets"] + 1):
            url = f"{SESSIONS}/{session_id}/sets/{row['id']}/{n}"
            response = await client.put(url, json=_values(row), headers=headers)
            assert response.status_code == 200, response.text
    finished = await client.post(f"{SESSIONS}/{session_id}/finish", json={}, headers=headers)
    assert finished.status_code == 200, finished.text
    return workout


async def _away(db: AsyncSession, days: int) -> None:
    shift = timedelta(days=days)
    await db.execute(update(SetLog).values(logged_at=SetLog.logged_at - shift))
    await db.execute(
        update(WorkoutSession).values(
            started_at=WorkoutSession.started_at - shift,
            finished_at=WorkoutSession.finished_at - shift,
        )
    )
    await db.flush()
    db.expire_all()


async def _full_user(client: AsyncClient, db: AsyncSession, tokens: TokenPair) -> None:
    """Profile, plan, three trained workouts (targets, rungs, interval step), an exercise
    swapped out because it hurt, and a comeback after 20 days away with its workout."""
    headers = _auth(tokens)
    assert (await client.put(f"{ME}/profile", json=GYM, headers=headers)).is_success
    assert (await client.post(f"{ME}/safety-screen", json=ALL_NO, headers=headers)).is_success
    assert (await client.post("/api/v1/plans", headers=headers)).status_code == 201
    await _train(client, headers)  # the strength test: movement rungs
    await _train(client, headers)
    await _train(client, headers)

    workout = dict((await client.get(f"{CURRENT}/next", headers=headers)).json())
    row = workout["main"][0]
    swap = await client.post(
        f"/api/v1/workouts/{workout['id']}/exercises/{row['id']}/swap",
        json={"exercise_id": row["exercise"]["id"], "reason": "hurts"},
        headers=headers,
    )
    assert swap.status_code == 200, swap.text

    await _away(db, 20)
    workout = dict((await client.get(f"{CURRENT}/next", headers=headers)).json())
    started = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    assert started.status_code in (200, 201), started.text
    assert await db.scalar(select(func.count()).select_from(Comeback)) == 1

    for table in _user_tables():
        count = await db.scalar(select(func.count()).select_from(table))
        assert count, f"the test user has no row in {table.name}"


async def _rows_left(db: AsyncSession) -> dict[str, int]:
    left = {}
    for table in _user_tables():
        left[table.name] = await db.scalar(select(func.count()).select_from(table)) or 0
    return left


@pytest.fixture
async def library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


# --- guests ------------------------------------------------------------------------------


async def test_a_guest_is_erased_at_once_with_everything(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    tokens = await _guest(client)
    await _full_user(client, db_session, tokens)

    response = await _delete(client, tokens)

    assert response.status_code == 204
    assert response.content == b""
    assert await _rows_left(db_session) == {t.name: 0 for t in _user_tables()}
    assert await _reasons(db_session) == []  # no reason given, nothing kept
    # The exercise library is not the user's: untouched.
    assert len(LIBRARY) == await db_session.scalar(text("SELECT count(*) FROM exercises"))


async def test_a_guests_reason_is_kept_without_the_person(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tokens = await _guest(client)

    response = await _delete(client, tokens, "no_time")

    assert response.status_code == 204
    [kept] = await _reasons(db_session)
    assert kept.reason is LeavingReason.NO_TIME
    assert kept.was_guest is True
    assert kept.left_on == (await _db_now(db_session)).date()
    # Nothing in the table can point back to anyone.
    columns = set(AccountDeletionReason.__table__.columns.keys())
    assert columns == {"id", "reason", "was_guest", "left_on"}


async def test_a_deleted_guests_tokens_stop_working(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    tokens = await _guest(client)
    await _delete(client, tokens)

    assert (await client.get(ME, headers=_auth(tokens))).status_code == 401
    refresh = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens.refresh_token}
    )
    assert refresh.status_code == 401


# --- Google/Apple accounts: 30 days ------------------------------------------------------


async def test_a_linked_account_waits_30_days_and_is_signed_out_everywhere(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    phone = await _google(client, google_id_token("g-1"))
    tablet = await _google(client, google_id_token("g-1"))

    response = await _delete(client, phone, "too_hard")

    assert response.status_code == 202
    delete_after = datetime.fromisoformat(response.json()["delete_after"])
    assert delete_after == await _db_now(db_session) + timedelta(days=30)
    [user] = await _users(db_session)
    assert user.delete_after == delete_after
    assert user.deletion_reason is LeavingReason.TOO_HARD
    assert await _reasons(db_session) == []  # counted only once really gone
    # Signed out on every device at once: access tokens refused, refresh tokens revoked.
    for device in (phone, tablet):
        assert (await client.get(ME, headers=_auth(device))).status_code == 401
        assert (await client.get(CURRENT, headers=_auth(device))).status_code == 401
        body = {"refresh_token": device.refresh_token}
        assert (await client.post("/api/v1/auth/refresh", json=body)).status_code == 401
    revoked = await db_session.scalars(select(RefreshToken.revoked_at))
    assert all(at is not None for at in revoked)


async def test_signing_in_within_30_days_cancels_and_keeps_everything(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken, library: None
) -> None:
    tokens = await _google(client, google_id_token("g-1"))
    user_id = await _user_id(client, tokens)
    await _full_user(client, db_session, tokens)
    before = await _rows_left(db_session)
    await _delete(client, tokens, "privacy")

    again = await _google(client, google_id_token("g-1"))

    assert again.deletion_cancelled is True
    assert await _user_id(client, again) == user_id
    [user] = await _users(db_session)
    assert user.delete_after is None
    assert user.deletion_reason is None
    after = await _rows_left(db_session)
    assert after["refresh_tokens"] == before["refresh_tokens"] + 1  # the new sign-in
    assert {k: v for k, v in after.items() if k != "refresh_tokens"} == {
        k: v for k, v in before.items() if k != "refresh_tokens"
    }
    # Cancelling saves no reason, and the next sign-in has nothing to cancel.
    assert await _reasons(db_session) == []
    assert (await _google(client, google_id_token("g-1"))).deletion_cancelled is False


async def test_any_linked_provider_cancels(
    client: AsyncClient,
    db_session: AsyncSession,
    google_id_token: MakeIdToken,
    apple_id_token: MakeIdToken,
) -> None:
    tokens = await _google(client, google_id_token("g-1"))
    link = await client.post(
        f"{ME}/link/apple",
        json={"id_token": apple_id_token("a-1"), "nonce": "raw-nonce-from-the-app"},
        headers=_auth(tokens),
    )
    assert link.status_code == 200, link.text
    await _delete(client, tokens)

    response = await client.post(
        "/api/v1/auth/apple",
        json={"id_token": apple_id_token("a-1"), "nonce": "raw-nonce-from-the-app"},
    )

    assert response.status_code == 200
    assert response.json()["deletion_cancelled"] is True
    [user] = await _users(db_session)
    assert user.delete_after is None


async def test_after_30_days_sign_in_finds_a_new_account_even_without_the_cleanup(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken, library: None
) -> None:
    tokens = await _google(client, google_id_token("g-1"))
    old_id = await _user_id(client, tokens)
    await _full_user(client, db_session, tokens)
    await _delete(client, tokens, "switched_apps")
    await _due(db_session)  # 30 days later, and the hourly cleanup never ran
    # `_due` moves the clock of the request back, so "the day they asked" moves with it.
    asked_on = (await _db_now(db_session) - timedelta(days=30, seconds=1)).date()

    again = await _google(client, google_id_token("g-1"))

    assert again.deletion_cancelled is False
    new_id = await _user_id(client, again)
    assert new_id != old_id
    [user] = await _users(db_session)
    assert str(user.id) == new_id
    assert user.delete_after is None
    # The old account's data is all gone; the new one has only its sign-in.
    left = await _rows_left(db_session)
    assert left.pop("users") == 1
    assert left.pop("refresh_tokens") == 1
    assert set(left.values()) == {0}
    [kept] = await _reasons(db_session)
    assert (kept.reason, kept.was_guest, kept.left_on) == (
        LeavingReason.SWITCHED_APPS,
        False,
        asked_on,
    )


async def test_a_guest_can_link_an_account_whose_30_days_are_over(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    old = await _google(client, google_id_token("g-1"))
    old_id = await _user_id(client, old)
    await _delete(client, old)
    await _due(db_session)
    guest = await _guest(client)
    guest_id = await _user_id(client, guest)

    link = await client.post(
        f"{ME}/link/google", json={"id_token": google_id_token("g-1")}, headers=_auth(guest)
    )

    assert link.status_code == 200, link.text
    assert link.json()["id"] == guest_id
    assert {str(u.id) for u in await _users(db_session)} == {guest_id}
    assert old_id != guest_id


async def test_a_guest_cant_link_an_account_that_is_still_waiting(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    """Within the 30 days the account is still someone's: the usual 409, then the app
    offers to sign in (which cancels the deletion)."""
    old = await _google(client, google_id_token("g-1"))
    await _delete(client, old)
    guest = await _guest(client)

    link = await client.post(
        f"{ME}/link/google", json={"id_token": google_id_token("g-1")}, headers=_auth(guest)
    )

    assert link.status_code == 409
    assert len(await _users(db_session)) == 2


# --- the cleanup -------------------------------------------------------------------------


async def test_the_cleanup_erases_only_accounts_whose_days_are_over(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    for n in range(5):
        tokens = await _google(client, google_id_token(f"due-{n}"))
        await _delete(client, tokens, "injury" if n % 2 else None)
    await _due(db_session)
    waiting = await _google(client, google_id_token("waiting"))
    await _delete(client, waiting, "other")
    staying = await _google(client, google_id_token("staying"))

    erased = await account.purge_due(db_session, batch=2)  # three batches: 2 + 2 + 1

    assert erased == 5
    left = {u.google_sub: u for u in await _users(db_session)}
    assert set(left) == {"waiting", "staying"}
    assert left["waiting"].deletion_reason is LeavingReason.OTHER
    assert (await client.get(ME, headers=_auth(staying))).status_code == 200
    reasons = await _reasons(db_session)
    assert sorted(r.reason for r in reasons) == [LeavingReason.INJURY, LeavingReason.INJURY]
    assert all(r.was_guest is False for r in reasons)
    assert await account.purge_due(db_session) == 0


async def test_left_on_is_the_day_they_asked_not_the_day_it_was_erased(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    tokens = await _google(client, google_id_token("g-1"))
    await _delete(client, tokens, "no_time")
    # Asked 31 days ago at 23:30 UTC: erased today, counted on the day they asked.
    await db_session.execute(
        update(User).values(
            delete_after=func.date_trunc("day", func.now()) - text("interval '30 minutes'")
        )
    )

    assert await account.purge_due(db_session) == 1

    [kept] = await _reasons(db_session)
    today = (await _db_now(db_session)).date()
    assert kept.left_on == today - timedelta(days=31)
    assert isinstance(kept.left_on, date)


# --- requests ----------------------------------------------------------------------------


async def test_deleting_needs_a_signed_in_user(client: AsyncClient) -> None:
    assert (await client.delete(ME)).status_code == 401


@pytest.mark.parametrize("reason", ["bored", "", "TOO_HARD"])
async def test_an_unknown_reason_is_refused_and_nothing_is_deleted(
    client: AsyncClient, db_session: AsyncSession, reason: str
) -> None:
    tokens = await _guest(client)

    response = await _delete(client, tokens, reason)

    assert response.status_code == 422
    assert len(await _users(db_session)) == 1


@pytest.mark.parametrize("reason", [r.value for r in LeavingReason])
async def test_every_reason_is_accepted(
    client: AsyncClient, db_session: AsyncSession, reason: str
) -> None:
    tokens = await _guest(client)

    assert (await _delete(client, tokens, reason)).status_code == 204

    [kept] = await _reasons(db_session)
    assert kept.reason == reason


async def test_a_plain_sign_in_says_nothing_was_cancelled(
    client: AsyncClient, google_id_token: MakeIdToken
) -> None:
    assert (await _google(client, google_id_token("g-1"))).deletion_cancelled is False
    assert (await _guest(client)).deletion_cancelled is False


async def test_an_account_is_due_at_the_exact_moment_its_30_days_end(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    tokens = await _google(client, google_id_token("g-1"))
    await _delete(client, tokens)
    await db_session.execute(update(User).values(delete_after=func.now()))

    assert await account.purge_due(db_session) == 1
