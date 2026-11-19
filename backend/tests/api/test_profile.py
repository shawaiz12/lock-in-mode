"""Onboarding endpoints: profile, safety screen and name (ADR 0012).

Every test signs in as a guest: onboarding must work without an account.
"""

from typing import Any, get_args

import pytest
from httpx import AsyncClient, Response

from lock_in_mode_api.models.profile import SESSION_MINUTES
from lock_in_mode_api.schemas.profile import SessionMinutes

ME = "/api/v1/me"
PROFILE = "/api/v1/me/profile"
SAFETY = "/api/v1/me/safety-screen"

ALL_NO = {
    "heart_condition": False,
    "chest_pain_when_active": False,
    "pregnant": False,
    "recent_surgery_or_injury": False,
}


def _answers(**overrides: Any) -> dict[str, Any]:
    """A valid set of onboarding answers; tests change one thing at a time."""
    answers: dict[str, Any] = {
        "goal": "lose_fat",
        "level": "beginner",
        "location": "home",
        "equipment": [],
        "limits": ["knees"],
        "days_per_week": 3,
        "minutes_per_session": 20,
    }
    answers.update(overrides)
    return answers


@pytest.fixture
async def guest(client: AsyncClient) -> dict[str, str]:
    """Auth headers for a brand-new guest."""
    response = await client.post("/api/v1/auth/guest")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _put(client: AsyncClient, headers: dict[str, str], **overrides: Any) -> Response:
    return await client.put(PROFILE, json=_answers(**overrides), headers=headers)


def _invalid_fields(response: Response) -> list[str]:
    assert response.status_code == 422
    return [error["field"] for error in response.json()["errors"]]


def test_session_minutes_match_the_database_rule() -> None:
    assert get_args(SessionMinutes.__value__) == SESSION_MINUTES


# --- GET / PUT /me/profile ----------------------------------------------------------


async def test_new_user_has_no_profile_so_the_app_shows_onboarding(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    response = await client.get(PROFILE, headers=guest)

    assert response.status_code == 404
    assert response.json()["code"] == "profile_not_found"


async def test_profile_needs_a_token(client: AsyncClient) -> None:
    response = await client.get(PROFILE)

    assert response.status_code == 401


async def test_first_save_creates_the_profile(client: AsyncClient, guest: dict[str, str]) -> None:
    response = await _put(client, guest)

    assert response.status_code == 201
    body = response.json()
    assert body["goal"] == "lose_fat"
    assert body["limits"] == ["knees"]
    # Defaults for answers the app didn't send.
    assert body["shoulder_day"] == "push"
    assert body["prefers_bro_split"] is False
    assert body["obstacles"] == []
    # Not screened yet: the app must show the safety screen before workout 1.
    assert body["needs_low_intensity"] is False
    assert body["safety_screened_at"] is None
    assert (await client.get(PROFILE, headers=guest)).json() == body


async def test_saving_again_replaces_the_profile(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    first = (await _put(client, guest)).json()

    response = await _put(client, guest, goal="stamina", days_per_week=4)

    assert response.status_code == 200
    assert response.json()["goal"] == "stamina"
    assert response.json()["days_per_week"] == 4
    assert response.json()["created_at"] == first["created_at"]


async def test_null_minutes_means_no_limit(client: AsyncClient, guest: dict[str, str]) -> None:
    response = await _put(client, guest, minutes_per_session=None)

    assert response.status_code == 201
    assert response.json()["minutes_per_session"] is None


async def test_minutes_must_be_sent_even_when_there_is_no_limit(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    answers = _answers()
    del answers["minutes_per_session"]

    response = await client.put(PROFILE, json=answers, headers=guest)

    assert _invalid_fields(response) == ["minutes_per_session"]


@pytest.mark.parametrize("minutes", [0, 15, 100])
async def test_unlisted_minutes_are_rejected(
    client: AsyncClient, guest: dict[str, str], minutes: int
) -> None:
    response = await _put(client, guest, minutes_per_session=minutes)

    assert _invalid_fields(response) == ["minutes_per_session"]


async def test_gym_users_cannot_list_home_equipment(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    response = await _put(client, guest, location="gym", equipment=["dumbbells"])

    assert _invalid_fields(response) == ["equipment"]


async def test_gym_is_not_home_equipment(client: AsyncClient, guest: dict[str, str]) -> None:
    response = await _put(client, guest, equipment=["gym"])

    assert _invalid_fields(response) == ["equipment"]


async def test_women_at_home_track_is_home_only(client: AsyncClient, guest: dict[str, str]) -> None:
    response = await _put(client, guest, location="gym", women_home_track=True)

    assert _invalid_fields(response) == ["women_home_track"]


async def test_duplicates_are_removed_and_lists_kept_in_a_fixed_order(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    response = await _put(
        client,
        guest,
        equipment=["pull_up_bar", "dumbbells", "pull_up_bar"],
        limits=["back", "knees", "back"],
        obstacles=["get_bored", "no_time", "get_bored"],
    )

    body = response.json()
    assert body["equipment"] == ["dumbbells", "pull_up_bar"]
    assert body["limits"] == ["knees", "back"]
    assert body["obstacles"] == ["no_time", "get_bored"]


async def test_the_safety_result_cannot_be_set_through_the_profile(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    response = await _put(client, guest, needs_low_intensity=False)

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "extra_forbidden"


async def test_bro_split_choice_is_offered_only_when_the_user_qualifies(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    qualifies = {
        "goal": "build_muscle",
        "level": "some_experience",
        "location": "gym",
        "days_per_week": 5,
        "minutes_per_session": 60,
    }
    assert (await _put(client, guest, **qualifies)).json()["bro_split_available"] is True

    # The preference is kept when they stop qualifying, just not offered (ADR 0012).
    stops_qualifying = {**qualifies, "days_per_week": 4, "prefers_bro_split": True}
    body = (await _put(client, guest, **stops_qualifying)).json()
    assert body["bro_split_available"] is False
    assert body["prefers_bro_split"] is True


# --- POST /me/safety-screen ---------------------------------------------------------


async def test_safety_screen_needs_a_profile_first(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    response = await client.post(SAFETY, json=ALL_NO, headers=guest)

    assert response.status_code == 404
    assert response.json()["code"] == "profile_not_found"


async def test_all_no_means_a_normal_plan(client: AsyncClient, guest: dict[str, str]) -> None:
    await _put(client, guest)

    response = await client.post(SAFETY, json=ALL_NO, headers=guest)

    assert response.status_code == 200
    assert response.json()["needs_low_intensity"] is False
    assert response.json()["safety_screened_at"] is not None


@pytest.mark.parametrize("question", list(ALL_NO))
async def test_any_yes_means_low_intensity(
    client: AsyncClient, guest: dict[str, str], question: str
) -> None:
    await _put(client, guest)

    response = await client.post(SAFETY, json={**ALL_NO, question: True}, headers=guest)

    assert response.json()["needs_low_intensity"] is True


async def test_retaking_with_all_no_turns_low_intensity_off(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    await _put(client, guest)
    await client.post(SAFETY, json={**ALL_NO, "recent_surgery_or_injury": True}, headers=guest)

    response = await client.post(SAFETY, json=ALL_NO, headers=guest)

    assert response.json()["needs_low_intensity"] is False


async def test_saving_the_profile_keeps_the_safety_result(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    await _put(client, guest)
    screened = (
        await client.post(SAFETY, json={**ALL_NO, "heart_condition": True}, headers=guest)
    ).json()

    body = (await _put(client, guest, goal="stay_active")).json()

    assert body["needs_low_intensity"] is True
    assert body["safety_screened_at"] == screened["safety_screened_at"]


async def test_every_safety_question_must_be_answered(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    await _put(client, guest)
    partial = {key: value for key, value in ALL_NO.items() if key != "pregnant"}

    response = await client.post(SAFETY, json=partial, headers=guest)

    assert _invalid_fields(response) == ["pregnant"]


# --- PATCH /me (name on the welcome screen) -----------------------------------------


async def test_name_is_saved_trimmed(client: AsyncClient, guest: dict[str, str]) -> None:
    response = await client.patch(ME, json={"display_name": "  Shawaiz "}, headers=guest)

    assert response.status_code == 200
    assert response.json()["display_name"] == "Shawaiz"
    assert (await client.get(ME, headers=guest)).json()["display_name"] == "Shawaiz"


async def test_null_clears_the_name(client: AsyncClient, guest: dict[str, str]) -> None:
    await client.patch(ME, json={"display_name": "Shawaiz"}, headers=guest)

    response = await client.patch(ME, json={"display_name": None}, headers=guest)

    assert response.json()["display_name"] is None


@pytest.mark.parametrize("name", ["   ", "x" * 51])
async def test_blank_or_too_long_names_are_rejected(
    client: AsyncClient, guest: dict[str, str], name: str
) -> None:
    response = await client.patch(ME, json={"display_name": name}, headers=guest)

    assert _invalid_fields(response) == ["display_name"]
