"""GET /me/muscles and GET /me/bests (ADR 0036): the muscle map and the "new bests" tile
on Home."""

from datetime import date

from pydantic import BaseModel, Field

from lock_in_mode_api.models.enums import MuscleGroup, MuscleHead


class MuscleHeadRead(BaseModel):
    head: MuscleHead
    sets: int = Field(description="Ticked sets this week that targeted this head.")
    next_up: bool = Field(description="The next workout targets this head.")


class MuscleGroupRead(BaseModel):
    group: MuscleGroup
    sets: int = Field(
        description="Ticked sets this week that targeted any head of this group (a set "
        "counts once per group). 0 = not trained yet this week."
    )
    next_up: bool = Field(description="The next workout trains this group.")
    heads: list[MuscleHeadRead] = Field(description="Every head of the group, 0 sets included.")


class MusclesRead(BaseModel):
    """ "Muscles this week": every muscle group, always all of them, in a fixed order.
    Only the main part and finishers count (not warm-ups or cool-downs), from workouts
    finished this week (Monday to Sunday on the phone's calendar, like `GET /me/week`)."""

    week_start: date = Field(description="Monday of this week, on the user's calendar.")
    groups: list[MuscleGroupRead]
    next_workout: str | None = Field(
        description='The next workout\'s title ("Pull"), or null: no plan, or the block '
        "is complete."
    )


class BestsRead(BaseModel):
    """The "new bests" tile: every new best ever made, counted the way each finish screen
    counts them. Never goes down."""

    total: int
