"""Rules for the exercise seed file (ADR 0009). Pure Python: no database needed."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from lock_in_mode_api.seed.schema import SeedLibrary, load_library


def _exercise(slug: str, **overrides: object) -> dict[str, object]:
    """A valid exercise as it would come out of the YAML; tests change one field at a time."""
    fields: dict[str, object] = {
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "category": "push",
        "muscle_groups": ["chest"],
        "difficulty": 2,
        "steps": ["Step one.", "Step two.", "Step three."],
        "cues": ["Cue one.", "Cue two."],
        "common_mistake": "A mistake.",
    }
    fields.update(overrides)
    return fields


def _library(*exercises: dict[str, object]) -> SeedLibrary:
    return SeedLibrary.model_validate({"exercises": list(exercises)})


# --- the real file ------------------------------------------------------------


def test_the_shipped_seed_file_is_valid() -> None:
    # The most important test here: bad content fails CI before it reaches a database.
    library = load_library()

    assert len(library.exercises) >= 1


def test_load_library_reads_a_given_path(tmp_path: Path) -> None:
    seed_file = tmp_path / "exercises.yaml"
    seed_file.write_text(
        "exercises:\n"
        "  - slug: plank\n"
        "    name: Plank\n"
        "    category: core\n"
        "    muscle_groups: [core]\n"
        "    difficulty: 1\n"
        "    is_timed: true\n"
        "    steps: [One., Two., Three.]\n"
        "    cues: [One., Two.]\n"
        "    common_mistake: Hips too high.\n",
        encoding="utf-8",
    )

    library = load_library(seed_file)

    assert library.by_slug["plank"].is_timed is True


# --- one exercise on its own ----------------------------------------------------


def test_a_valid_exercise_passes() -> None:
    library = _library(_exercise("push-up"))

    assert library.by_slug["push-up"].equipment == []


def test_unknown_key_is_rejected() -> None:
    # A typo must not be silently ignored, or a ladder link would quietly disappear.
    with pytest.raises(ValidationError, match="harderr"):
        _library(_exercise("push-up", harderr="decline-push-up"))


@pytest.mark.parametrize(
    "slug", ["Push-Up", "push_up", "push--up", "-push-up", "push up", "a" * 61]
)
def test_badly_formed_slug_is_rejected(slug: str) -> None:
    with pytest.raises(ValidationError, match="slug"):
        _library(_exercise(slug))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("category", "arms"),
        ("muscle_groups", ["biceps"]),
        ("equipment", ["chair"]),
    ],
)
def test_values_outside_the_enums_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        _library(_exercise("push-up", **{field: value}))


@pytest.mark.parametrize("difficulty", [0, 6])
def test_difficulty_must_be_1_to_5(difficulty: int) -> None:
    with pytest.raises(ValidationError, match="difficulty"):
        _library(_exercise("push-up", difficulty=difficulty))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("steps", ["One.", "Two."]),  # brief: 3-5 steps
        ("steps", ["1.", "2.", "3.", "4.", "5.", "6."]),
        ("cues", ["Only one."]),  # brief: 2-3 cues
        ("cues", ["1.", "2.", "3.", "4."]),
        ("muscle_groups", []),
    ],
)
def test_list_lengths_follow_the_brief(field: str, value: list[str]) -> None:
    with pytest.raises(ValidationError, match=field):
        _library(_exercise("push-up", **{field: value}))


def test_blank_text_is_rejected() -> None:
    with pytest.raises(ValidationError, match="common_mistake"):
        _library(_exercise("push-up", common_mistake="   "))


@pytest.mark.parametrize("field", ["muscle_groups", "equipment", "alternatives"])
def test_duplicates_in_a_list_are_rejected(field: str) -> None:
    values = {
        "muscle_groups": ["chest", "chest"],
        "equipment": ["bench", "bench"],
        "alternatives": ["dip", "dip"],
    }[field]

    with pytest.raises(ValidationError, match="duplicates"):
        _library(_exercise("push-up", **{field: values}), _exercise("dip"))


def test_demo_url_must_be_https() -> None:
    with pytest.raises(ValidationError, match="demo_url"):
        _library(_exercise("push-up", demo_url="http://example.com/push-up.gif"))


def test_exercise_cannot_be_its_own_harder_variant() -> None:
    with pytest.raises(ValidationError, match="its own harder variant"):
        _library(_exercise("push-up", harder="push-up"))


def test_exercise_cannot_be_its_own_alternative() -> None:
    with pytest.raises(ValidationError, match="its own alternative"):
        _library(_exercise("push-up", alternatives=["push-up"]))


# --- the library as a whole -------------------------------------------------------


def test_duplicate_slug_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate slug: push-up"):
        _library(_exercise("push-up"), _exercise("push-up", name="Another Name"))


def test_duplicate_name_is_rejected_ignoring_case() -> None:
    with pytest.raises(ValidationError, match="duplicate name"):
        _library(_exercise("push-up", name="Push-Up"), _exercise("pushup", name="push-up"))


def test_harder_variant_must_exist() -> None:
    with pytest.raises(ValidationError, match="harder variant 'decline-push-up' not found"):
        _library(_exercise("push-up", harder="decline-push-up"))


def test_alternative_must_exist() -> None:
    with pytest.raises(ValidationError, match="alternative 'dip' not found"):
        _library(_exercise("push-up", alternatives=["dip"]))


def test_ladders_cannot_merge() -> None:
    # Mirrors UNIQUE(harder_variant_id): push-up can have only one easier version.
    with pytest.raises(ValidationError, match="harder variant of both"):
        _library(
            _exercise("knee-push-up", difficulty=1, harder="push-up"),
            _exercise("incline-push-up", difficulty=1, harder="push-up"),
            _exercise("push-up", difficulty=2),
        )


def test_ladder_loop_is_rejected() -> None:
    with pytest.raises(ValidationError, match="loops: a -> b -> c -> a"):
        _library(
            _exercise("a", harder="b"),
            _exercise("b", harder="c"),
            _exercise("c", harder="a"),
        )


def test_harder_variant_needs_a_higher_difficulty() -> None:
    # Also catches a link written the wrong way round (harder pointing to an easier one).
    with pytest.raises(ValidationError, match="needs a higher difficulty"):
        _library(
            _exercise("push-up", difficulty=2, harder="knee-push-up"),
            _exercise("knee-push-up", difficulty=1),
        )


def test_harder_variant_must_be_in_the_same_category() -> None:
    with pytest.raises(ValidationError, match="same category"):
        _library(
            _exercise("push-up", difficulty=2, harder="jump-squat"),
            _exercise("jump-squat", category="legs", difficulty=3),
        )


def test_a_valid_ladder_passes() -> None:
    library = _library(
        _exercise("knee-push-up", difficulty=1, harder="push-up"),
        _exercise("push-up", difficulty=2, harder="decline-push-up"),
        _exercise("decline-push-up", difficulty=3),
    )

    assert library.by_slug["push-up"].harder == "decline-push-up"


def test_alternative_pairs_are_stored_both_ways() -> None:
    library = _library(
        _exercise("knee-push-up", alternatives=["incline-push-up"]),
        _exercise("incline-push-up"),
    )

    assert library.alternative_pairs() == {
        ("knee-push-up", "incline-push-up"),
        ("incline-push-up", "knee-push-up"),
    }


def test_a_pair_written_twice_is_stored_once_per_direction() -> None:
    library = _library(
        _exercise("knee-push-up", alternatives=["incline-push-up"]),
        _exercise("incline-push-up", alternatives=["knee-push-up"]),
    )

    assert len(library.alternative_pairs()) == 2
