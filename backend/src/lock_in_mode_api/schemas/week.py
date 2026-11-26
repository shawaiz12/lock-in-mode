"""GET /me/week (ADR 0034): this week's ring and the weekly streak."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class WeekRead(BaseModel):
    """'This week: 2 of 3' and '5-week streak'. Weeks run Monday to Sunday in the phone's
    time zone (`PATCH /me` `time_zone`); a trained workout = finished with a ticked set."""

    week_start: date = Field(description="Monday of this week, on the user's calendar.")
    done: int = Field(description="Workouts trained this week.")
    planned: int | None = Field(description="Workouts planned a week (the profile's days).")
    keep_at: int = Field(description="Workouts that keep a week in the streak (2).")
    kept: bool = Field(description="This week already counts for the streak.")
    streak: int = Field(description="Kept weeks in a row; this week joins once kept.")
    best_streak: int
    freezes: int = Field(
        description="Freezes held (0-2): one earned per 4 kept weeks; a missed week uses one."
    )
    last_week: Literal["kept", "frozen", "missed"] | None = Field(
        description='How last week ended ("frozen": a freeze saved it). null: no weeks yet.'
    )
