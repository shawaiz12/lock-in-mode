"""XP and the Lock In level (ADR 0035)."""

from typing import Literal

from pydantic import BaseModel, Field

type XpSourceName = Literal["workout", "week", "best", "comeback", "bonus"]


class XpLevel(BaseModel):
    """'Lock In level 7 · 320 / 1,000 XP'. Never goes down."""

    total: int = Field(description="All XP ever earned.")
    level: int = Field(description="The Lock In level (not the training level).")
    xp_into: int = Field(description="XP since this level started.")
    xp_needed: int = Field(description="XP from this level's start to the next level.")


class XpItem(BaseModel):
    source: XpSourceName = Field(
        description="workout: the workout itself (100 × share of its sets) · week: the "
        "week was kept · best: new bests, 25 each, max 3 · comeback: first workout back "
        "after a break · bonus: the Locked-in bonus, the workout's XP once more."
    )
    amount: int


class XpGained(BaseModel):
    """What a finished workout earned, in the order to reveal it on the finish screen."""

    items: list[XpItem]
    gained: int = Field(description="The sum of `items`.")
    bonus: bool = Field(description="A Locked-in bonus came with it: celebrate it.")
    capped: bool = Field(
        description="Past this week's XP limit (days a week + 1): it still counts as "
        'training. Say "Rest counts too: you\'ve done your week."'
    )
    before: XpLevel
    after: XpLevel
