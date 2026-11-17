"""Rules for the exercise seed file (ADRs 0009, 0010). Pure Python: no database needed."""

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
        "movement_slot": "horizontal_push",
        "exercise_type": "compound",
        "primary_muscle": "chest",
        "targets": ["chest_mid"],
        "difficulty": 2,
        "effectiveness": 3,
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
        "    movement_slot: brace\n"
        "    exercise_type: isolation\n"
        "    primary_muscle: core\n"
        "    targets: [deep_core]\n"
        "    difficulty: 1\n"
        "    effectiveness: 3\n"
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

    push_up = library.by_slug["push-up"]
    assert push_up.equipment == []
    assert push_up.impact == "none"
    assert push_up.home_only is False


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
        ("movement_slot", "pushing"),
        ("exercise_type", "cardio-ish"),
        ("primary_muscle", "arms"),
        ("secondary_muscles", ["legs"]),
        ("targets", ["inner_biceps"]),
        ("equipment", ["chair"]),
        ("impact", "huge"),
        ("not_suitable_for", ["wrists"]),
    ],
)
def test_values_outside_the_enums_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        _library(_exercise("push-up", **{field: value}))


@pytest.mark.parametrize("field", ["difficulty", "effectiveness"])
@pytest.mark.parametrize("value", [0, 6])
def test_ratings_must_be_1_to_5(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match=field):
        _library(_exercise("push-up", **{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("steps", ["One.", "Two."]),  # brief: 3-5 steps
        ("steps", ["1.", "2.", "3.", "4.", "5.", "6."]),
        ("cues", ["Only one."]),  # brief: 2-3 cues
        ("cues", ["1.", "2.", "3.", "4."]),
    ],
)
def test_list_lengths_follow_the_brief(field: str, value: list[str]) -> None:
    with pytest.raises(ValidationError, match=field):
        _library(_exercise("push-up", **{field: value}))


def test_blank_text_is_rejected() -> None:
    with pytest.raises(ValidationError, match="common_mistake"):
        _library(_exercise("push-up", common_mistake="   "))


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("secondary_muscles", ["triceps", "triceps"]),
        ("targets", ["chest_mid", "chest_mid"]),
        ("equipment", ["dumbbells", "dumbbells"]),
        ("not_suitable_for", ["knees", "knees"]),
        ("alternatives", ["dip", "dip"]),
    ],
)
def test_duplicates_in_a_list_are_rejected(field: str, values: list[str]) -> None:

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


# --- muscles, heads and equipment agree (ADR 0010) -------------------------------


def test_target_in_a_secondary_muscle_is_allowed() -> None:
    library = _library(
        _exercise(
            "push-up", secondary_muscles=["triceps"], targets=["chest_mid", "triceps_lateral"]
        )
    )

    assert "triceps_lateral" in library.by_slug["push-up"].targets


def test_target_outside_the_trained_muscles_is_rejected() -> None:
    # A push-up tagged with a biceps head would make the head-coverage check lie.
    with pytest.raises(ValidationError, match="biceps_long belongs to biceps"):
        _library(_exercise("push-up", targets=["chest_mid", "biceps_long"]))


def test_strength_exercise_needs_a_primary_muscle() -> None:
    with pytest.raises(ValidationError, match="primary_muscle is required"):
        _library(_exercise("push-up", primary_muscle=None))


def test_strength_exercise_needs_a_target() -> None:
    with pytest.raises(ValidationError, match="at least one target"):
        _library(_exercise("push-up", targets=[]))


def test_primary_muscle_cannot_also_be_secondary() -> None:
    # It would be counted 1.5 times in the weekly set count.
    with pytest.raises(ValidationError, match="also listed as secondary"):
        _library(_exercise("push-up", secondary_muscles=["chest"]))


def _cardio(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "category": "cardio",
        "movement_slot": "conditioning",
        "exercise_type": "cardio",
        "primary_muscle": None,
        "targets": [],
    }
    fields.update(overrides)
    return _exercise("march-in-place", **fields)


def _stretch(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "category": "mobility",
        "movement_slot": "cool_down",
        "exercise_type": "mobility",
        "primary_muscle": "hamstrings",
        "targets": [],
        "effectiveness": None,
    }
    fields.update(overrides)
    return _exercise("hamstring-stretch", **fields)


def test_cardio_has_no_muscles() -> None:
    library = _library(_cardio())

    assert library.by_slug["march-in-place"].primary_muscle is None


@pytest.mark.parametrize(
    "overrides",
    [{"primary_muscle": "quads"}, {"secondary_muscles": ["calves"]}, {"targets": ["soleus"]}],
)
def test_cardio_with_muscles_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="cardio moves have no muscles"):
        _library(_cardio(**overrides))


def test_stretch_names_the_muscle_it_stretches() -> None:
    # The cool-down picks stretches for the muscles trained that day (ADR 0011).
    library = _library(_stretch())

    assert library.by_slug["hamstring-stretch"].primary_muscle == "hamstrings"


def test_stretch_can_have_no_muscle() -> None:
    library = _library(_stretch(primary_muscle=None, movement_slot="warm_up"))

    assert library.by_slug["hamstring-stretch"].primary_muscle is None


def test_stretch_with_head_targets_is_rejected() -> None:
    with pytest.raises(ValidationError, match="mobility moves have no head targets"):
        _library(_stretch(targets=["hamstrings_hip"]))


def test_effectiveness_is_required_except_for_mobility() -> None:
    with pytest.raises(ValidationError, match="effectiveness is required"):
        _library(_exercise("push-up", effectiveness=None))


def test_mobility_can_be_unrated() -> None:
    library = _library(
        _exercise(
            "cat-cow",
            category="mobility",
            movement_slot="warm_up",
            exercise_type="mobility",
            primary_muscle=None,
            targets=[],
            effectiveness=None,
        )
    )

    assert library.by_slug["cat-cow"].effectiveness is None


def test_home_only_exercise_cannot_need_gym_equipment() -> None:
    with pytest.raises(ValidationError, match="home-only exercise can't need gym"):
        _library(_exercise("table-row", home_only=True, equipment=["gym"]))


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


def test_harder_variant_with_the_same_difficulty_is_allowed() -> None:
    # Difficulty only goes 1-5 and some ladders have 7 rungs, so neighbours can share it.
    library = _library(
        _exercise("push-up", difficulty=3, harder="close-grip-push-up"),
        _exercise("close-grip-push-up", difficulty=3),
    )

    assert library.by_slug["push-up"].harder == "close-grip-push-up"


def test_harder_variant_with_a_lower_difficulty_is_rejected() -> None:
    # Also catches a link written the wrong way round (harder pointing to an easier one).
    with pytest.raises(ValidationError, match="same or a higher difficulty"):
        _library(
            _exercise("push-up", difficulty=2, harder="knee-push-up"),
            _exercise("knee-push-up", difficulty=1),
        )


def test_harder_variant_must_fill_the_same_movement_slot() -> None:
    # Push-up -> pike push-up is harder, but it's a different job (vertical push).
    with pytest.raises(ValidationError, match="same movement slot"):
        _library(
            _exercise("push-up", difficulty=2, harder="pike-push-up"),
            _exercise("pike-push-up", movement_slot="vertical_push", difficulty=3),
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
