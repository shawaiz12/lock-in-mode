"""Funnel events through the API (ADR 0025): each of the 11 events is recorded once, by
the action itself, with only its fixed details; nothing for an action that failed; the
"Share usage data" switch stops them and erases the past ones. Real library.
"""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Event, SetLog, User, WorkoutSession
from lock_in_mode_api.models.enums import EventName
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.services import plans as plan_service

type MakeIdToken = Callable[..., str]
type Headers = dict[str, str]
type Json = dict[str, Any]

ME = "/api/v1/me"
PLANS = "/api/v1/plans"
CURRENT = "/api/v1/plans/current"
SESSIONS = "/api/v1/sessions"
APPLE_NONCE = "raw-nonce-from-the-app"  # must match tests/api/conftest.py
ALL_NO = {
    "heart_condition": False,
    "chest_pain_when_active": False,
    "pregnant": False,
    "recent_surgery_or_injury": False,
}
HOME: Json = {
    "goal": "build_muscle",
    "level": "beginner",
    "location": "home",
    "days_per_week": 3,
    "minutes_per_session": 30,
}
MARKS = {"push-up": {"reps": 15}, "bodyweight-squat": {"reps": 25}, "plank": {"seconds": 45}}


@pytest.fixture
async def library(db_session: AsyncSession) -> None:
    await load_exercises(db_session, load_library())


async def _guest(client: AsyncClient) -> Headers:
    response = await client.post("/api/v1/auth/guest")
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _events(db: AsyncSession, name: EventName | None = None) -> list[Event]:
    query = select(Event).order_by(Event.at, Event.id)
    if name is not None:
        query = query.where(Event.name == name)
    return list((await db.scalars(query.execution_options(populate_existing=True))).all())


async def _names(db: AsyncSession) -> list[str]:
    return [e.name.value for e in await _events(db)]


async def _onboard(client: AsyncClient, headers: Headers, answers: Json = HOME) -> None:
    assert (await client.put(f"{ME}/profile", json=answers, headers=headers)).is_success
    assert (await client.post(f"{ME}/safety-screen", json=ALL_NO, headers=headers)).is_success


async def _plan(client: AsyncClient, headers: Headers, answers: Json = HOME) -> None:
    await _onboard(client, headers, answers)
    response = await client.post(PLANS, headers=headers)
    assert response.status_code == 201, response.text


async def _current(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(CURRENT, headers=headers)).json())


async def _next(client: AsyncClient, headers: Headers) -> Json:
    return dict((await client.get(f"{CURRENT}/next", headers=headers)).json())


async def _do(
    client: AsyncClient,
    headers: Headers,
    sets: dict[str, Json] | None = None,
    feedback: str | None = None,
) -> Json:
    """Do the next workout: one set of the first main exercise, or the given sets."""
    workout = await _next(client, headers)
    response = await client.post(SESSIONS, json={"workout_id": workout["id"]}, headers=headers)
    assert response.status_code == 201, response.text
    session_id = response.json()["id"]
    rows = [r for r in workout["main"] if not r["swapped_out"]]
    if sets is None:
        ticks = [(rows[0], {"seconds": 20} if rows[0]["seconds"] else {"reps": 10})]
    else:
        ticks = [(r, sets[r["exercise"]["slug"]]) for r in rows if r["exercise"]["slug"] in sets]
    for row, values in ticks:
        url = f"{SESSIONS}/{session_id}/sets/{row['id']}/1"
        assert (await client.put(url, json=values, headers=headers)).status_code == 200
    body = {} if feedback is None else {"feedback": feedback}
    result = await client.post(f"{SESSIONS}/{session_id}/finish", json=body, headers=headers)
    assert result.status_code == 200, result.text
    return workout


async def _skip_rest(client: AsyncClient, headers: Headers) -> None:
    for workout in (await _current(client, headers))["workouts"]:
        if workout["status"] == "pending":
            response = await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=headers)
            assert response.status_code == 200, response.text
    assert (await _current(client, headers))["block_complete"] is True


async def _shift_back(db: AsyncSession, days: int) -> None:
    """Pretend everything trained so far happened `days` days earlier (a break)."""
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


# --- the journey ------------------------------------------------------------------------


async def test_a_guests_first_day(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    assert await _names(db_session) == ["signed_up"]

    await _onboard(client, headers)
    # Retaking the safety screen isn't onboarding again.
    assert (await client.post(f"{ME}/safety-screen", json=ALL_NO, headers=headers)).is_success
    assert (await client.post(PLANS, headers=headers)).status_code == 201
    workout = await _do(client, headers, feedback="just_right")

    signed_up, onboarding, plan, started, finished = await _events(db_session)
    assert signed_up.props == {"method": "guest"}
    assert (onboarding.name, onboarding.props) == (
        EventName.ONBOARDING_DONE,
        {
            "goal": "build_muscle",
            "level": "beginner",
            "location": "home",
            "days_per_week": 3,
            "minutes_per_session": 30,
        },
    )
    assert (plan.name, plan.props) == (
        EventName.PLAN_STARTED,
        {"block": 1, "level": "beginner", "reason": "first"},
    )
    assert (started.name, started.props) == (
        EventName.WORKOUT_STARTED,
        {"number": 1, "kind": workout["kind"]},
    )
    assert (finished.name, finished.props) == (
        EventName.WORKOUT_FINISHED,
        {"number": 1, "kind": workout["kind"], "feedback": "just_right", "comeback": False},
    )
    user = await db_session.scalar(select(User))
    assert user is not None
    assert {e.user_id for e in await _events(db_session)} == {user.id}


async def test_workouts_are_numbered_and_skipped_ones_dont_count(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers)
    upcoming = await _next(client, headers)
    await client.post(f"/api/v1/workouts/{upcoming['id']}/skip", headers=headers)
    await _do(client, headers)

    finished = await _events(db_session, EventName.WORKOUT_FINISHED)
    assert [e.props["number"] for e in finished] == [1, 2]
    assert finished[1].props["feedback"] is None
    started = await _events(db_session, EventName.WORKOUT_STARTED)
    assert [e.props["number"] for e in started] == [1, 2]


async def test_a_block_completes_once_then_the_next_one_starts(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers)
    await _skip_rest(client, headers)  # the last workout skipped: complete

    [complete] = await _events(db_session, EventName.BLOCK_COMPLETE)
    assert complete.props == {"block": 1, "level_up_offered": False}
    # Seeing it complete again records nothing new.
    user_id = complete.user_id
    await plan_service.note_block_complete(db_session, user_id)
    assert len(await _events(db_session, EventName.BLOCK_COMPLETE)) == 1

    assert (await client.post(PLANS, headers=headers)).status_code == 201

    plans = await _events(db_session, EventName.PLAN_STARTED)
    assert [p.props for p in plans] == [
        {"block": 1, "level": "beginner", "reason": "first"},
        {"block": 2, "level": "beginner", "reason": "next_block"},
    ]


async def test_finishing_the_last_workout_completes_the_block(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    workouts = (await _current(client, headers))["workouts"]
    for workout in workouts[:-1]:
        await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=headers)
    assert await _events(db_session, EventName.BLOCK_COMPLETE) == []

    await _do(client, headers)

    [complete] = await _events(db_session, EventName.BLOCK_COMPLETE)
    assert complete.props["block"] == 1


async def test_a_break_that_replaces_the_recovery_week_completes_the_block_on_return(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    """Found by the sweep: the block ends by time alone (ADR 0021), with no finish or skip
    to record it. It's recorded when the next block starts."""
    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers)
    for workout in (await _current(client, headers))["workouts"]:
        if workout["status"] == "pending" and not workout["recovery"]:
            await client.post(f"/api/v1/workouts/{workout['id']}/skip", headers=headers)
    assert await _events(db_session, EventName.BLOCK_COMPLETE) == []
    await _shift_back(db_session, days=20)
    assert (await _current(client, headers))["block_complete"] is True

    assert (await client.post(PLANS, headers=headers)).status_code == 201

    [complete] = await _events(db_session, EventName.BLOCK_COMPLETE)
    assert complete.props == {"block": 1, "level_up_offered": False}
    assert (await _events(db_session, EventName.PLAN_STARTED))[-1].props["block"] == 2


async def test_level_up_offered_at_block_complete_and_accepted(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers, MARKS)  # the strength test, all three marks hit
    await _skip_rest(client, headers)

    [complete] = await _events(db_session, EventName.BLOCK_COMPLETE)
    assert complete.props == {"block": 1, "level_up_offered": True}

    response = await client.post(PLANS, json={"level_up": True}, headers=headers)
    assert response.status_code == 201, response.text

    [accepted] = await _events(db_session, EventName.LEVEL_UP_ACCEPTED)
    assert accepted.props == {"from": "beginner", "to": "some_experience"}
    plan = (await _events(db_session, EventName.PLAN_STARTED))[-1]
    assert plan.props == {"block": 2, "level": "some_experience", "reason": "next_block"}


async def test_changed_answers_start_a_plan_only_once_it_was_used(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    # Untouched plan rebuilt (onboarding's last screen): the same block, no new start.
    changed = HOME | {"days_per_week": 4}
    assert (await client.put(f"{ME}/profile", json=changed, headers=headers)).is_success
    assert len(await _events(db_session, EventName.PLAN_STARTED)) == 1

    await _do(client, headers)
    again = changed | {"days_per_week": 2}
    assert (await client.put(f"{ME}/profile", json=again, headers=headers)).is_success

    plans = await _events(db_session, EventName.PLAN_STARTED)
    assert [p.props["reason"] for p in plans] == ["first", "answers_changed"]
    assert plans[-1].props["block"] == 2


async def test_a_comeback_after_a_break(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers)
    await _shift_back(db_session, days=20)

    await _do(client, headers)

    [comeback] = await _events(db_session, EventName.COMEBACK_STARTED)
    assert comeback.props == {"away_days": 20, "weeks": 1}
    finished = await _events(db_session, EventName.WORKOUT_FINISHED)
    assert [e.props["comeback"] for e in finished] == [False, True]


# --- accounts ---------------------------------------------------------------------------


async def test_google_and_apple_sign_ups_once_each(
    client: AsyncClient,
    db_session: AsyncSession,
    google_id_token: MakeIdToken,
    apple_id_token: MakeIdToken,
) -> None:
    for _ in range(2):  # the second sign-in is the same account: no new sign-up
        r = await client.post("/api/v1/auth/google", json={"id_token": google_id_token("g")})
        assert r.status_code == 200
    body = {"id_token": apple_id_token("a"), "nonce": APPLE_NONCE}
    assert (await client.post("/api/v1/auth/apple", json=body)).status_code == 200

    signups = await _events(db_session, EventName.SIGNED_UP)
    assert sorted(e.props["method"] for e in signups) == ["apple", "google"]


async def test_linking_a_guest_once(
    client: AsyncClient,
    db_session: AsyncSession,
    google_id_token: MakeIdToken,
    apple_id_token: MakeIdToken,
) -> None:
    headers = await _guest(client)
    link = await client.post(
        f"{ME}/link/google", json={"id_token": google_id_token("g")}, headers=headers
    )
    assert link.status_code == 200
    # A second provider on an account that's already saved isn't a new link.
    link = await client.post(
        f"{ME}/link/apple",
        json={"id_token": apple_id_token("a"), "nonce": APPLE_NONCE},
        headers=headers,
    )
    assert link.status_code == 200

    [linked] = await _events(db_session, EventName.ACCOUNT_LINKED)
    assert linked.props == {"provider": "google"}


async def test_a_failed_link_leaves_no_event(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    taken = await client.post("/api/v1/auth/google", json={"id_token": google_id_token("g")})
    assert taken.status_code == 200
    headers = await _guest(client)

    link = await client.post(
        f"{ME}/link/google", json={"id_token": google_id_token("g")}, headers=headers
    )

    assert link.status_code == 409
    assert await _events(db_session, EventName.ACCOUNT_LINKED) == []
    guest = await db_session.scalar(
        select(User).where(User.is_guest).execution_options(populate_existing=True)
    )
    assert guest is not None  # still a guest


async def test_a_deletion_asked_and_cancelled(
    client: AsyncClient, db_session: AsyncSession, google_id_token: MakeIdToken
) -> None:
    tokens = (
        await client.post("/api/v1/auth/google", json={"id_token": google_id_token("g")})
    ).json()
    await client.delete(ME, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    await client.post("/api/v1/auth/google", json={"id_token": google_id_token("g")})

    assert await _names(db_session) == ["signed_up", "deletion_requested", "deletion_cancelled"]


async def test_a_guest_deleting_leaves_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _guest(client)
    assert (await client.delete(ME, headers=headers)).status_code == 204
    assert await _events(db_session) == []


# --- "Share usage data" -----------------------------------------------------------------


async def test_switching_off_erases_the_past_and_records_nothing_new(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    other = await _guest(client)  # someone else's events stay
    headers = await _guest(client)
    await _onboard(client, headers)

    response = await client.patch(ME, json={"share_usage_data": False}, headers=headers)

    assert response.status_code == 200
    assert response.json()["share_usage_data"] is False
    assert len(await _events(db_session)) == 1  # only the other guest's sign-up
    assert (await client.post(PLANS, headers=headers)).status_code == 201
    await _do(client, headers)
    assert len(await _events(db_session)) == 1
    assert (await client.get(ME, headers=other)).json()["share_usage_data"] is True

    # Back on: recorded again from now.
    await client.patch(ME, json={"share_usage_data": True}, headers=headers)
    await _do(client, headers)
    # Its XP (ADR 0035) reached Lock In level 2: recorded too, now that sharing is on.
    assert await _names(db_session) == [
        "signed_up",
        "workout_started",
        "workout_finished",
        "level_up",
    ]
    assert (await _events(db_session, EventName.WORKOUT_FINISHED))[0].props["number"] == 2
    assert (await _events(db_session, EventName.LEVEL_UP))[0].props == {"level": 2}


async def test_patch_me_changes_only_what_is_sent(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await _guest(client)
    await client.patch(ME, json={"display_name": "Shawaiz"}, headers=headers)

    off = await client.patch(ME, json={"share_usage_data": False}, headers=headers)
    assert (off.json()["display_name"], off.json()["share_usage_data"]) == ("Shawaiz", False)
    named = await client.patch(ME, json={"display_name": "Shaw"}, headers=headers)
    assert (named.json()["display_name"], named.json()["share_usage_data"]) == ("Shaw", False)
    nothing = await client.patch(ME, json={}, headers=headers)
    assert (nothing.json()["display_name"], nothing.json()["share_usage_data"]) == ("Shaw", False)


@pytest.mark.parametrize(
    "body", [{"share_usage_data": None}, {"share_usage_data": "maybe"}, {"tracking": False}]
)
async def test_patch_me_refuses_nonsense(client: AsyncClient, body: Json) -> None:
    headers = await _guest(client)
    assert (await client.patch(ME, json=body, headers=headers)).status_code == 422
    assert (await client.get(ME, headers=headers)).json()["share_usage_data"] is True


async def test_no_health_answers_or_free_text_in_any_event(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    """Every detail key any event can carry (ADR 0025's table), and nothing else."""
    headers = await _guest(client)
    await _plan(client, headers)
    await _do(client, headers, feedback="too_hard")
    await _do(client, headers)
    await _do(client, headers)  # workout 3: sign_in_offered (ADR 0026)
    await _skip_rest(client, headers)
    await client.post(PLANS, headers=headers)
    assert len(await _events(db_session, EventName.SIGN_IN_OFFERED)) == 1

    allowed = {
        "method", "provider", "goal", "level", "location", "days_per_week",
        "minutes_per_session", "block", "reason", "number", "kind", "feedback", "comeback",
        "level_up_offered", "from", "to", "away_days", "weeks", "milestone",
    }  # fmt: skip
    keys = {key for e in await _events(db_session) for key in e.props}
    assert keys <= allowed
    assert all(
        isinstance(v, (str, int, bool, type(None)))
        for e in await _events(db_session)
        for v in e.props.values()
    )


async def test_signing_the_pact_is_recorded_once(
    client: AsyncClient, db_session: AsyncSession, library: None
) -> None:
    headers = await _guest(client)
    await _onboard(client, headers)

    for _ in range(2):
        assert (await client.post(f"{ME}/pact", headers=headers)).status_code == 200

    [signed] = await _events(db_session, EventName.PACT_SIGNED)
    assert signed.props == {}
