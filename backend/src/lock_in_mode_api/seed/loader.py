"""Put the seed file into the database (ADR 0009). Safe to run any number of times.

- Rows are matched by `slug`, never by id, so reloading never creates duplicates.
- New exercises are inserted, changed ones updated, unchanged ones left alone.
- Ladder links are set in a second pass, once every exercise has an id.
- Alternatives are stored in both directions.
- Nothing is deleted. An exercise that is in the database but no longer in the file is
  reported (later, plans and logged sets will point at it) and unlinked from ladders.

The function owns its transaction: everything is committed together, or nothing is.
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lock_in_mode_api.models import Exercise, exercise_alternatives
from lock_in_mode_api.seed.schema import SeedExercise, SeedLibrary

# Seed fields that map 1:1 onto columns. `harder` and `alternatives` are links, handled
# separately once every row has an id.
COLUMNS = (
    "name",
    "category",
    "movement_slot",
    "exercise_type",
    "primary_muscle",
    "secondary_muscles",
    "targets",
    "equipment",
    "also_needs",
    "home_only",
    "difficulty",
    "effectiveness",
    "impact",
    "not_suitable_for",
    "is_timed",
    "steps",
    "cues",
    "common_mistake",
    "demo_url",
)


@dataclass
class SeedReport:
    inserted: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    links_changed: int = 0
    not_in_file: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"inserted: {len(self.inserted)}, updated: {len(self.updated)}, "
            f"unchanged: {self.unchanged}, ladder links changed: {self.links_changed}"
        ]
        if self.not_in_file:
            lines.append(
                "in the database but not in the seed file (kept, unlinked): "
                + ", ".join(self.not_in_file)
            )
        return "\n".join(lines)


def _column_values(seed: SeedExercise) -> dict[str, Any]:
    """The seed exercise as plain column values (enum members become their text)."""
    values = seed.model_dump(include=set(COLUMNS), mode="json")
    return {name: values[name] for name in COLUMNS}


async def load_exercises(session: AsyncSession, library: SeedLibrary) -> SeedReport:
    report = SeedReport()
    existing = {e.slug: e for e in await session.scalars(select(Exercise))}

    # Pass 1: every exercise exists with the right content (no links yet).
    for seed in library.exercises:
        values = _column_values(seed)
        row = existing.get(seed.slug)
        if row is None:
            row = Exercise(slug=seed.slug, **values)
            session.add(row)
            existing[seed.slug] = row
            report.inserted.append(seed.slug)
        elif any(getattr(row, name) != value for name, value in values.items()):
            for name, value in values.items():
                setattr(row, name, value)
            report.updated.append(seed.slug)
        else:
            report.unchanged += 1
    await session.flush()  # new rows get their ids

    # Pass 2: ladder links. Clear every link that changes first, then set the new ones,
    # so moving a link never trips UNIQUE(harder_variant_id) halfway through.
    wanted = {slug: None for slug in existing} | {
        seed.slug: existing[seed.harder].id if seed.harder else None for seed in library.exercises
    }
    changing = [
        slug for slug, target in wanted.items() if existing[slug].harder_variant_id != target
    ]
    if changing:
        changing_ids = [existing[slug].id for slug in changing]
        await session.execute(
            update(Exercise).where(Exercise.id.in_(changing_ids)).values(harder_variant_id=None)
        )
        for slug in changing:
            if wanted[slug] is not None:
                await session.execute(
                    update(Exercise)
                    .where(Exercise.id == existing[slug].id)
                    .values(harder_variant_id=wanted[slug])
                )
        report.links_changed = len(changing)

    # Pass 3: alternatives for the exercises in the file, replaced as a whole.
    file_ids = [existing[seed.slug].id for seed in library.exercises]
    await session.execute(
        delete(exercise_alternatives).where(exercise_alternatives.c.exercise_id.in_(file_ids))
    )
    pairs = [
        {"exercise_id": existing[a].id, "alternative_id": existing[b].id}
        for a, b in sorted(library.alternative_pairs())
    ]
    if pairs:
        await session.execute(insert(exercise_alternatives), pairs)

    in_file = {seed.slug for seed in library.exercises}
    report.not_in_file = sorted(slug for slug in existing if slug not in in_file)

    await session.commit()
    return report
