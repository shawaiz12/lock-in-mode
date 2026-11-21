"""Session templates: each session is a list of movement slots (KB section 5, ADR 0015).

A slot is a job ("horizontal push"), not an exercise. The builder fills it with the
exercise that suits the user. Slots are in priority order: when time is short the builder
drops from the bottom, and never drops the first three.
"""

from dataclasses import dataclass

from lock_in_mode_api.models.enums import MovementSlot, MuscleHead, SessionKind, ShoulderDay

M = MovementSlot
H = MuscleHead
S = SessionKind


@dataclass(frozen=True)
class Slot:
    movement: MovementSlot
    prefer: MuscleHead | None = None  # emphasis, e.g. incline press -> upper chest
    optional: bool = False  # "(if time)": added only when the session has room
    light: bool = False  # bro split's "second light touch": 2 sets
    fallback: MovementSlot | None = None  # used when nothing fits the slot
    keep: int | None = None  # drop priority when time is short: lower is kept longer.
    # None = the slot's position. Lets the order we *do* exercises differ from the order
    # we *drop* them (push day keeps triceps over a chest fly; KB worked example 3).

    @property
    def main(self) -> bool:
        """Big multi-joint lifts rotate between 2 picks; smaller moves between 3 (ADR 0014)."""
        return self.movement in MAIN_MOVEMENTS


type Template = tuple[Slot, ...]

MAIN_MOVEMENTS = frozenset(
    {
        M.SQUAT,
        M.SINGLE_LEG,
        M.HINGE,
        M.HORIZONTAL_PUSH,
        M.VERTICAL_PUSH,
        M.HORIZONTAL_PULL,
        M.VERTICAL_PULL,
    }
)

# No pull-up bar, bands or gym: the vertical pull becomes a second row (KB section 5).
VERTICAL_PULL = Slot(M.VERTICAL_PULL, H.LATS, fallback=M.HORIZONTAL_PULL)
CHEST_PRESS = Slot(M.HORIZONTAL_PUSH, H.CHEST_MID)
INCLINE_PRESS = Slot(M.HORIZONTAL_PUSH, H.CHEST_UPPER)

FULL_BODY: dict[str, Template] = {
    "A": (
        Slot(M.SQUAT),
        CHEST_PRESS,
        Slot(M.HORIZONTAL_PULL),
        Slot(M.HINGE),
        Slot(M.BRACE),
        Slot(M.VERTICAL_PUSH, optional=True),
        Slot(M.BICEPS, optional=True),
    ),
    "B": (
        Slot(M.HINGE),
        Slot(M.VERTICAL_PUSH),
        VERTICAL_PULL,
        Slot(M.SINGLE_LEG),
        Slot(M.SIDE_AND_ROTATION),
        Slot(M.TRICEPS, optional=True),
        Slot(M.CALVES, optional=True),
    ),
    "C": (
        Slot(M.SINGLE_LEG),
        CHEST_PRESS,
        Slot(M.HORIZONTAL_PULL),
        Slot(M.BRIDGE),
        Slot(M.LATERAL_RAISE),
        Slot(M.BRACE),
    ),
}

UPPER: dict[str, Template] = {
    "A": (
        CHEST_PRESS,
        Slot(M.HORIZONTAL_PULL),
        Slot(M.VERTICAL_PUSH),
        VERTICAL_PULL,
        Slot(M.LATERAL_RAISE),
        Slot(M.TRICEPS),
        Slot(M.BICEPS),
    ),
    "B": (
        VERTICAL_PULL,
        Slot(M.VERTICAL_PUSH),
        Slot(M.HORIZONTAL_PULL),
        INCLINE_PRESS,
        Slot(M.REAR_DELT),
        Slot(M.BICEPS),
        Slot(M.TRICEPS),
    ),
}

LOWER: dict[str, Template] = {
    "A": (
        Slot(M.SQUAT),
        Slot(M.HINGE),
        Slot(M.SINGLE_LEG),
        Slot(M.LEG_CURL),
        Slot(M.CALVES),
        Slot(M.BRACE),
    ),
    "B": (
        Slot(M.HINGE),
        Slot(M.SQUAT),
        Slot(M.BRIDGE),
        Slot(M.LEG_EXTENSION),
        Slot(M.CALVES),
        Slot(M.AB_CURL),
    ),
}

CHEST_WORK = (
    CHEST_PRESS,
    INCLINE_PRESS,
    Slot(M.CHEST_FLY, H.CHEST_LOWER),
)
SHOULDER_WORK = (
    Slot(M.VERTICAL_PUSH),
    Slot(M.LATERAL_RAISE),
    Slot(M.REAR_DELT),
)
LEG_WORK = (
    Slot(M.SQUAT),
    Slot(M.HINGE),
    Slot(M.SINGLE_LEG),
    Slot(M.LEG_CURL),
)

# Push pull legs. Big muscle first, helper after: chest, then shoulders, then triceps.
# `keep` makes short sessions lose the fly and rear delt before the helper muscle's first
# exercise, so every muscle of the day still gets trained.
PUSH: dict[ShoulderDay, Template] = {
    ShoulderDay.PUSH: (
        CHEST_PRESS,
        INCLINE_PRESS,
        Slot(M.CHEST_FLY, H.CHEST_LOWER, keep=5),
        Slot(M.VERTICAL_PUSH, keep=2),
        Slot(M.LATERAL_RAISE, keep=3),
        Slot(M.REAR_DELT, keep=6),
        Slot(M.TRICEPS, H.TRICEPS_LATERAL, keep=4),
        Slot(M.TRICEPS, H.TRICEPS_LONG, keep=7),
    ),
    ShoulderDay.LEGS: (
        CHEST_PRESS,
        INCLINE_PRESS,
        Slot(M.CHEST_FLY, H.CHEST_LOWER, keep=4),
        Slot(M.TRICEPS, H.TRICEPS_LATERAL, keep=2),
        Slot(M.TRICEPS, H.TRICEPS_LONG, keep=3),
        Slot(M.TRICEPS, H.TRICEPS_MEDIAL, keep=5),
    ),
}
PULL: Template = (
    VERTICAL_PULL,
    Slot(M.HORIZONTAL_PULL, H.MID_BACK),
    Slot(M.HORIZONTAL_PULL, keep=4),  # a second row, other grip or angle
    Slot(M.TRAPS, H.UPPER_TRAPS, keep=5),
    Slot(M.REAR_DELT, H.LOWER_TRAPS, keep=3),
    Slot(M.LOWER_BACK, fallback=M.HINGE, keep=6),
    Slot(M.BICEPS, H.BICEPS_LONG, keep=2),
    Slot(M.BICEPS, H.BICEPS_SHORT, keep=7),
)
LEGS: dict[ShoulderDay, Template] = {
    ShoulderDay.PUSH: (
        *LEG_WORK,
        Slot(M.LEG_EXTENSION, keep=5),
        Slot(M.CALVES, keep=6),
        Slot(M.BRACE, keep=4),
    ),
    ShoulderDay.LEGS: (
        Slot(M.SQUAT),
        Slot(M.HINGE),
        Slot(M.SINGLE_LEG),
        Slot(M.LEG_CURL, keep=6),
        Slot(M.VERTICAL_PUSH, keep=3),
        Slot(M.LATERAL_RAISE, keep=4),
        Slot(M.REAR_DELT, keep=5),
        Slot(M.CALVES, keep=7),
    ),
}

# Bro split: main work, then a light second touch of another muscle (KB section 5).
BRO: dict[SessionKind, Template] = {
    S.BRO_CHEST: (
        *CHEST_WORK,
        Slot(M.HORIZONTAL_PUSH),
        Slot(M.REAR_DELT, light=True),
    ),
    S.BRO_BACK: (
        VERTICAL_PULL,
        Slot(M.HORIZONTAL_PULL, H.MID_BACK),
        Slot(M.HORIZONTAL_PULL),
        Slot(M.TRAPS, H.UPPER_TRAPS),
        Slot(M.REAR_DELT, H.LOWER_TRAPS),
        Slot(M.LOWER_BACK, fallback=M.HINGE),
        Slot(M.LATERAL_RAISE, light=True),
    ),
    S.BRO_LEGS: (
        *LEG_WORK,
        Slot(M.LEG_EXTENSION),
        Slot(M.CALVES),
        Slot(M.BRACE, light=True),
    ),
    S.BRO_SHOULDERS: (
        *SHOULDER_WORK,
        Slot(M.LATERAL_RAISE),
        Slot(M.CHEST_FLY, light=True),
    ),
    S.BRO_ARMS: (
        Slot(M.BICEPS, H.BICEPS_LONG),
        Slot(M.TRICEPS, H.TRICEPS_LONG),
        Slot(M.BICEPS, H.BICEPS_SHORT),
        Slot(M.TRICEPS, H.TRICEPS_LATERAL),
        Slot(M.BRACE),
        Slot(M.SIDE_AND_ROTATION),
        Slot(M.HORIZONTAL_PULL, light=True),
    ),
}

# Stamina: full-body circuits (KB section 5 and worked example 5).
CIRCUIT: dict[str, Template] = {
    "A": (
        Slot(M.SQUAT),
        CHEST_PRESS,
        Slot(M.HORIZONTAL_PULL),
        Slot(M.HINGE),
        Slot(M.BRACE),
    ),
    "B": (
        Slot(M.SINGLE_LEG),
        Slot(M.VERTICAL_PUSH),
        VERTICAL_PULL,
        Slot(M.BRIDGE),
        Slot(M.SIDE_AND_ROTATION),
    ),
}

LETTERED: dict[SessionKind, dict[str, Template]] = {
    S.FULL_BODY: FULL_BODY,
    S.UPPER: UPPER,
    S.LOWER: LOWER,
    S.CIRCUIT: CIRCUIT,
}

STRENGTH_KINDS = frozenset(LETTERED) | {S.PUSH, S.PULL, S.LEGS} | frozenset(BRO)


def template(kind: SessionKind, letter: str, shoulder_day: ShoulderDay) -> Template:
    """The slots for one strength session. Cardio and mobility sessions have no template."""
    if kind in LETTERED:
        return LETTERED[kind][letter]
    if kind == S.PUSH:
        return PUSH[shoulder_day]
    if kind == S.PULL:
        return PULL
    if kind == S.LEGS:
        return LEGS[shoulder_day]
    if kind in BRO:
        return BRO[kind]
    raise ValueError(f"{kind.value} has no strength template")
