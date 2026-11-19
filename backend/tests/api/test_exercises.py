"""Exercise library endpoints (ADR 0013), against the real seed file."""

from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, Profile, exercise_alternatives
from lock_in_mode_api.seed.loader import load_exercises
from lock_in_mode_api.seed.schema import load_library
from lock_in_mode_api.training.exercise_rules import can_do

EXERCISES = "/api/v1/exercises"
LIBRARY_SIZE = 257


@pytest.fixture
async def library(db_session: AsyncSession) -> list[Exercise]:
    """The whole seed file, loaded into this test's (rolled back) database."""
    await load_exercises(db_session, load_library())
    return list(await db_session.scalars(select(Exercise)))


@pytest.fixture
async def guest(client: AsyncClient) -> dict[str, str]:
    response = await client.post("/api/v1/auth/guest")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _onboard(client: AsyncClient, headers: dict[str, str], **answers: Any) -> None:
    body = {
        "goal": "build_muscle",
        "level": "beginner",
        "location": "home",
        "days_per_week": 3,
        "minutes_per_session": 30,
        **answers,
    }
    response = await client.put("/api/v1/me/profile", json=body, headers=headers)
    assert response.status_code in (200, 201)


async def _all_pages(
    client: AsyncClient, headers: dict[str, str], **params: Any
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        body = (
            await client.get(EXERCISES, params={**params, "page": page}, headers=headers)
        ).json()
        items += body["items"]
        if page * body["page_size"] >= body["total"]:
            return items
        page += 1


async def _slug_id(session: AsyncSession, slug: str) -> str:
    return str(await session.scalar(select(Exercise.id).where(Exercise.slug == slug)))


# --- listing and pages ---------------------------------------------------------------


async def test_library_needs_a_token(client: AsyncClient) -> None:
    assert (await client.get(EXERCISES)).status_code == 401


@pytest.mark.usefixtures("library")
async def test_first_page_has_50_sorted_by_name(client: AsyncClient, guest: dict[str, str]) -> None:
    body = (await client.get(EXERCISES, headers=guest)).json()

    assert body["total"] == LIBRARY_SIZE
    assert body["page"] == 1
    assert len(body["items"]) == 50
    names = [item["name"] for item in body["items"]]
    assert names == sorted(names)


@pytest.mark.usefixtures("library")
async def test_pages_cover_the_library_once(client: AsyncClient, guest: dict[str, str]) -> None:
    slugs = [item["slug"] for item in await _all_pages(client, guest)]

    assert len(slugs) == LIBRARY_SIZE
    assert len(set(slugs)) == LIBRARY_SIZE  # no repeats across pages


@pytest.mark.usefixtures("library")
async def test_a_page_past_the_end_is_empty(client: AsyncClient, guest: dict[str, str]) -> None:
    body = (await client.get(EXERCISES, params={"page": 99}, headers=guest)).json()

    assert body["items"] == []
    assert body["total"] == LIBRARY_SIZE


@pytest.mark.parametrize(
    "params", [{"page_size": 101}, {"page": 0}, {"max_difficulty": 6}, {"catgory": "push"}]
)
async def test_bad_or_misspelt_parameters_are_rejected(
    client: AsyncClient, guest: dict[str, str], params: dict[str, Any]
) -> None:
    response = await client.get(EXERCISES, params=params, headers=guest)

    assert response.status_code == 422


async def test_filters_combine(
    client: AsyncClient, guest: dict[str, str], library: list[Exercise]
) -> None:
    items = await _all_pages(client, guest, category="pull", muscle="biceps", max_difficulty=2)

    expected = {
        e.slug
        for e in library
        if e.category == "pull"
        and (e.primary_muscle == "biceps" or "biceps" in e.secondary_muscles)
        and e.difficulty <= 2
    }
    assert expected  # the filter isn't trivially empty
    assert {item["slug"] for item in items} == expected


# --- for_me --------------------------------------------------------------------------


@pytest.mark.usefixtures("library")
async def test_for_me_needs_a_profile(client: AsyncClient, guest: dict[str, str]) -> None:
    response = await client.get(EXERCISES, params={"for_me": True}, headers=guest)

    assert response.status_code == 404
    assert response.json()["code"] == "profile_not_found"


@pytest.mark.parametrize(
    "setup",
    [
        {"location": "gym"},
        {"location": "home"},
        {"location": "home", "equipment": ["resistance_bands", "pull_up_bar"]},
        {"location": "home", "equipment": ["dumbbells"]},
    ],
)
async def test_for_me_in_the_database_matches_the_python_rule(
    client: AsyncClient,
    guest: dict[str, str],
    db_session: AsyncSession,
    library: list[Exercise],
    setup: dict[str, Any],
) -> None:
    # The list filters in SQL (for correct pages); the plan generator will use can_do().
    # They must never disagree.
    await _onboard(client, guest, **setup)
    profile = await db_session.scalar(select(Profile))
    assert profile is not None

    items = await _all_pages(client, guest, for_me=True)

    assert {item["slug"] for item in items} == {e.slug for e in library if can_do(e, profile)}


async def test_gym_users_never_see_bands_or_home_tricks(
    client: AsyncClient, guest: dict[str, str], library: list[Exercise]
) -> None:
    await _onboard(client, guest, location="gym")

    slugs = {item["slug"] for item in await _all_pages(client, guest, for_me=True)}

    home_tricks = {e.slug for e in library if e.home_only}
    band_moves = {e.slug for e in library if "resistance_bands" in e.equipment}
    assert "backpack-curl" in home_tricks  # the test checks something real
    assert band_moves
    assert slugs.isdisjoint(home_tricks | band_moves)


# --- cautions (shown, not hidden) ----------------------------------------------------


@pytest.mark.usefixtures("library")
async def test_no_profile_means_no_cautions(client: AsyncClient, guest: dict[str, str]) -> None:
    items = await _all_pages(client, guest)

    assert all(item["cautions"] == [] for item in items)


async def test_moves_bad_for_their_knees_are_listed_with_a_warning(
    client: AsyncClient, guest: dict[str, str], library: list[Exercise]
) -> None:
    await _onboard(client, guest, limits=["knees"])

    items = {item["slug"]: item for item in await _all_pages(client, guest)}

    knee_unsafe = {e.slug for e in library if "knees" in e.not_suitable_for}
    assert "pistol-squat" in knee_unsafe
    assert {slug for slug, item in items.items() if "knees" in item["cautions"]} == knee_unsafe
    assert len(items) == LIBRARY_SIZE  # nothing hidden


async def test_a_yes_on_the_safety_screen_flags_jumping(
    client: AsyncClient, guest: dict[str, str], library: list[Exercise]
) -> None:
    await _onboard(client, guest)
    answers = {
        "heart_condition": True,
        "chest_pain_when_active": False,
        "pregnant": False,
        "recent_surgery_or_injury": False,
    }
    await client.post("/api/v1/me/safety-screen", json=answers, headers=guest)

    items = await _all_pages(client, guest)

    flagged = {item["slug"] for item in items if "low_intensity" in item["cautions"]}
    assert flagged == {e.slug for e in library if e.impact in ("medium", "high")}
    assert flagged


# --- data saver (ETag / 304) ---------------------------------------------------------


async def _get(client: AsyncClient, headers: dict[str, str], etag: str | None = None) -> Response:
    extra = {"If-None-Match": etag} if etag else {}
    return await client.get(EXERCISES, headers={**headers, **extra})


@pytest.mark.usefixtures("library")
async def test_unchanged_list_is_a_304_with_no_body(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    first = await _get(client, guest)
    assert first.headers["Cache-Control"] == "private, no-cache"
    etag = first.headers["ETag"]

    again = await _get(client, guest, etag)

    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["ETag"] == etag


@pytest.mark.usefixtures("library")
async def test_weak_and_listed_etags_also_match(client: AsyncClient, guest: dict[str, str]) -> None:
    etag = (await _get(client, guest)).headers["ETag"]

    assert (await _get(client, guest, f'"old", W/{etag}')).status_code == 304


@pytest.mark.usefixtures("library")
async def test_a_change_that_affects_the_list_sends_it_again(
    client: AsyncClient, guest: dict[str, str]
) -> None:
    await _onboard(client, guest)
    etag = (await _get(client, guest)).headers["ETag"]

    await _onboard(client, guest, limits=["knees"])  # cautions change
    response = await _get(client, guest, etag)

    assert response.status_code == 200
    assert response.headers["ETag"] != etag


# --- one exercise --------------------------------------------------------------------


async def test_detail_shows_steps_and_the_ladder(
    client: AsyncClient, guest: dict[str, str], db_session: AsyncSession, library: list[Exercise]
) -> None:
    push_up_id = await _slug_id(db_session, "push-up")

    response = await client.get(f"{EXERCISES}/{push_up_id}", headers=guest)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Push-up"
    assert body["steps"]
    assert body["easier"]["slug"] == "knee-push-up"
    assert body["harder"]["slug"] == "close-grip-push-up"
    assert "ETag" in response.headers


async def test_detail_lists_alternatives(
    client: AsyncClient, guest: dict[str, str], db_session: AsyncSession, library: list[Exercise]
) -> None:
    push_up_id = await _slug_id(db_session, "push-up")
    incline_id = await _slug_id(db_session, "incline-push-up")
    await db_session.execute(
        insert(exercise_alternatives).values(exercise_id=push_up_id, alternative_id=incline_id)
    )

    body = (await client.get(f"{EXERCISES}/{push_up_id}", headers=guest)).json()

    assert [alt["slug"] for alt in body["alternatives"]] == ["incline-push-up"]


async def test_unknown_exercise_is_not_found(client: AsyncClient, guest: dict[str, str]) -> None:
    response = await client.get(f"{EXERCISES}/00000000-0000-0000-0000-000000000000", headers=guest)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
