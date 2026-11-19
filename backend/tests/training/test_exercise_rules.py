"""Who can do which exercise, and when to warn (ADR 0010, ADR 0013). No database needed."""

from dataclasses import dataclass, field, replace

from lock_in_mode_api.models.enums import BodyLimit, Caution, Equipment, Impact, Location
from lock_in_mode_api.training.exercise_rules import GYM_KIT, can_do, cautions, user_kit


@dataclass(frozen=True)
class User:
    location: Location = Location.HOME
    equipment: list[str] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    needs_low_intensity: bool = False
    women_home_track: bool = False


@dataclass(frozen=True)
class Move:
    equipment: list[str] = field(default_factory=list)
    home_only: bool = False
    impact: Impact = Impact.NONE
    not_suitable_for: list[str] = field(default_factory=list)


GYM = User(location=Location.GYM)
HOME = User()


def test_gym_users_have_everything_except_bands() -> None:
    assert user_kit(Location.GYM, []) == GYM_KIT
    assert Equipment.RESISTANCE_BANDS not in GYM_KIT


def test_home_users_have_what_they_listed() -> None:
    assert user_kit(Location.HOME, ["dumbbells"]) == {Equipment.DUMBBELLS}


def test_bodyweight_moves_suit_everyone() -> None:
    assert can_do(Move(), HOME)
    assert can_do(Move(), GYM)


def test_every_needed_item_must_be_owned() -> None:
    band_assisted_pull_up = Move(equipment=["pull_up_bar", "resistance_bands"])

    assert not can_do(band_assisted_pull_up, replace(HOME, equipment=["pull_up_bar"]))
    assert can_do(
        band_assisted_pull_up, replace(HOME, equipment=["pull_up_bar", "resistance_bands"])
    )


def test_gym_users_never_get_bands_or_home_tricks() -> None:
    assert not can_do(Move(equipment=["resistance_bands"]), GYM)
    assert not can_do(Move(home_only=True), GYM)
    assert can_do(Move(home_only=True), HOME)


def test_home_users_never_get_gym_machines() -> None:
    assert not can_do(Move(equipment=["gym"]), replace(HOME, equipment=["dumbbells"]))


def test_no_cautions_for_a_user_without_limits() -> None:
    assert cautions(Move(impact=Impact.HIGH, not_suitable_for=["knees"]), HOME) == []


def test_a_body_limit_the_move_is_bad_for_is_a_caution() -> None:
    move = Move(not_suitable_for=[BodyLimit.KNEES, BodyLimit.BACK])
    user = replace(HOME, limits=[BodyLimit.KNEES, BodyLimit.SHOULDERS])

    assert cautions(move, user) == [Caution.KNEES]


def test_jumping_is_a_caution_for_low_intensity_and_the_quiet_track() -> None:
    user = replace(HOME, needs_low_intensity=True, women_home_track=True)

    assert cautions(Move(impact=Impact.MEDIUM), user) == [
        Caution.LOW_INTENSITY,
        Caution.NOT_QUIET,
    ]
    assert cautions(Move(impact=Impact.LOW), user) == []
