"""Rules for the exercise seed file (ADR 0009, fields from ADRs 0010 and 0011).

Two layers:
- `SeedExercise` checks one exercise on its own (types, allowed values, counts, and that
  its muscles, heads and equipment agree with each other).
- `SeedLibrary` checks how exercises point at each other (ADR 0003): references exist,
  ladders don't merge, no loops, and a harder variant is the same job at the same or a
  higher difficulty.

Nothing here touches the database, so these rules run in milliseconds in CI.
"""

from importlib.resources import files
from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from lock_in_mode_api.models.enums import (
    HEAD_GROUP,
    BodyLimit,
    Equipment,
    ExerciseCategory,
    ExerciseType,
    Impact,
    MovementSlot,
    MuscleGroup,
    MuscleHead,
)

# Lowercase words joined by single hyphens: "push-up", "decline-push-up".
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)]
PlainText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
DemoUrl = Annotated[str, StringConstraints(pattern=r"^https://\S+$", max_length=500)]

DEFAULT_SEED_FILE = "exercises.yaml"


class SeedExercise(BaseModel):
    """One exercise exactly as it is written in the YAML file."""

    # extra="forbid": a typo like `harderr:` is an error instead of being silently ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)

    slug: Slug
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    category: ExerciseCategory
    movement_slot: MovementSlot
    exercise_type: ExerciseType

    # Weekly set counting: a set counts 1 for the primary muscle, 0.5 for each secondary.
    primary_muscle: MuscleGroup | None = None
    secondary_muscles: list[MuscleGroup] = []
    targets: list[MuscleHead] = []  # heads this exercise emphasises

    equipment: list[Equipment] = []  # kit it needs; empty = none
    also_needs: PlainText | None = None  # e.g. "Chair", "Barbell, bench"; shown to the user
    home_only: bool = False  # a home trick (backpack row, table row): never shown at the gym

    difficulty: int = Field(ge=1, le=5)
    effectiveness: int | None = Field(default=None, ge=1, le=5)  # blank only for mobility
    impact: Impact = Impact.NONE
    not_suitable_for: list[BodyLimit] = []
    is_timed: bool = False

    steps: list[PlainText] = Field(min_length=3, max_length=5)
    cues: list[PlainText] = Field(min_length=2, max_length=3)
    common_mistake: PlainText
    demo_url: DemoUrl | None = None

    harder: Slug | None = None  # slug of the next exercise up the ladder
    alternatives: list[Slug] = []  # slugs; written once per pair, stored both ways

    @field_validator(
        "secondary_muscles", "targets", "equipment", "not_suitable_for", "alternatives"
    )
    @classmethod
    def no_duplicates(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("contains duplicates")
        return values

    @model_validator(mode="after")
    def does_not_point_at_itself(self) -> Self:
        if self.harder == self.slug:
            raise ValueError(f"{self.slug}: an exercise can't be its own harder variant")
        if self.slug in self.alternatives:
            raise ValueError(f"{self.slug}: an exercise can't be its own alternative")
        return self

    @model_validator(mode="after")
    def muscles_and_heads_agree(self) -> Self:
        if self.primary_muscle is not None and self.primary_muscle in self.secondary_muscles:
            raise ValueError(f"{self.slug}: primary muscle is also listed as secondary")
        if self.category == ExerciseCategory.CARDIO:
            # Cardio trains the heart and lungs; it never counts towards muscle sets.
            if self.primary_muscle is not None or self.secondary_muscles or self.targets:
                raise ValueError(f"{self.slug}: cardio moves have no muscles or targets")
            return self
        if self.category == ExerciseCategory.MOBILITY:
            # A stretch names the muscle it stretches, so the cool-down can pick stretches
            # for what was trained (ADR 0011). It has no head targets and counts no sets.
            if self.targets:
                raise ValueError(f"{self.slug}: mobility moves have no head targets")
            return self
        if self.primary_muscle is None:
            raise ValueError(f"{self.slug}: primary_muscle is required")
        if not self.targets:
            raise ValueError(f"{self.slug}: at least one target head is required")
        # Every head must belong to a muscle the exercise says it trains; otherwise the
        # head-coverage check and the weekly set count would disagree.
        trained = {self.primary_muscle, *self.secondary_muscles}
        for head in self.targets:
            if HEAD_GROUP[head] not in trained:
                raise ValueError(
                    f"{self.slug}: target {head} belongs to {HEAD_GROUP[head]}, "
                    "which is not its primary or a secondary muscle"
                )
        return self

    @model_validator(mode="after")
    def effectiveness_is_rated(self) -> Self:
        if self.category != ExerciseCategory.MOBILITY and self.effectiveness is None:
            raise ValueError(f"{self.slug}: effectiveness is required (only mobility is unrated)")
        return self

    @model_validator(mode="after")
    def home_only_needs_no_gym(self) -> Self:
        if self.home_only and Equipment.GYM in self.equipment:
            raise ValueError(f"{self.slug}: a home-only exercise can't need gym equipment")
        return self


class SeedLibrary(BaseModel):
    """The whole file. Checks the rules that need more than one exercise to see."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exercises: list[SeedExercise] = Field(min_length=1)

    @property
    def by_slug(self) -> dict[str, SeedExercise]:
        return {exercise.slug: exercise for exercise in self.exercises}

    def alternative_pairs(self) -> set[tuple[str, str]]:
        """Every (exercise, alternative) pair in both directions, as the table stores them."""
        pairs: set[tuple[str, str]] = set()
        for exercise in self.exercises:
            for other in exercise.alternatives:
                pairs.add((exercise.slug, other))
                pairs.add((other, exercise.slug))
        return pairs

    # The checks run in this order, so each one can rely on the ones before it.
    @model_validator(mode="after")
    def check_library(self) -> Self:
        self._check_unique_slugs_and_names()
        self._check_references_exist()
        self._check_ladders_do_not_merge()
        self._check_no_loops()
        self._check_harder_is_harder()
        return self

    def _check_unique_slugs_and_names(self) -> None:
        seen_slugs: set[str] = set()
        seen_names: set[str] = set()
        for exercise in self.exercises:
            if exercise.slug in seen_slugs:
                raise ValueError(f"duplicate slug: {exercise.slug}")
            if exercise.name.casefold() in seen_names:
                raise ValueError(f"duplicate name: {exercise.name}")
            seen_slugs.add(exercise.slug)
            seen_names.add(exercise.name.casefold())

    def _check_references_exist(self) -> None:
        known = self.by_slug
        for exercise in self.exercises:
            if exercise.harder is not None and exercise.harder not in known:
                raise ValueError(f"{exercise.slug}: harder variant {exercise.harder!r} not found")
            for other in exercise.alternatives:
                if other not in known:
                    raise ValueError(f"{exercise.slug}: alternative {other!r} not found")

    def _check_ladders_do_not_merge(self) -> None:
        # Mirrors UNIQUE(harder_variant_id): every exercise has at most one easier version.
        easier_of: dict[str, str] = {}
        for exercise in self.exercises:
            if exercise.harder is None:
                continue
            if exercise.harder in easier_of:
                raise ValueError(
                    f"{exercise.harder} is the harder variant of both "
                    f"{easier_of[exercise.harder]} and {exercise.slug}; "
                    "link one of them as an alternative instead (ADR 0003)"
                )
            easier_of[exercise.harder] = exercise.slug

    def _check_no_loops(self) -> None:
        # Each exercise has at most one harder variant, so from any start there is exactly
        # one path to follow. If the path comes back to an exercise it already visited,
        # it's a loop, and the plan generator would climb forever. Neighbours may share a
        # difficulty (ADR 0010), so difficulty alone can't rule loops out: this check can.
        known = self.by_slug
        for start in self.exercises:
            visited = [start.slug]
            current = start.harder
            while current is not None:
                if current in visited:
                    loop = " -> ".join([*visited[visited.index(current) :], current])
                    raise ValueError(f"variant ladder loops: {loop}")
                visited.append(current)
                current = known[current].harder

    def _check_harder_is_harder(self) -> None:
        known = self.by_slug
        for exercise in self.exercises:
            if exercise.harder is None:
                continue
            harder = known[exercise.harder]
            if harder.movement_slot != exercise.movement_slot:
                raise ValueError(
                    f"{exercise.slug} ({exercise.movement_slot}) -> "
                    f"{harder.slug} ({harder.movement_slot}): "
                    "a harder variant must fill the same movement slot"
                )
            if harder.difficulty < exercise.difficulty:
                raise ValueError(
                    f"{exercise.slug} (difficulty {exercise.difficulty}) -> {harder.slug} "
                    f"(difficulty {harder.difficulty}): "
                    "a harder variant needs the same or a higher difficulty"
                )


def load_library(path: Path | None = None) -> SeedLibrary:
    """Read and validate a seed file. Defaults to the file that ships with the package."""
    if path is None:
        source = files("lock_in_mode_api.seed") / DEFAULT_SEED_FILE
        text = source.read_text(encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    # safe_load builds only plain data; yaml.load could build arbitrary Python objects.
    return SeedLibrary.model_validate(yaml.safe_load(text))
