from enum import StrEnum


class Goal(StrEnum):
    BUILD_MUSCLE = "build_muscle"
    STRENGTH = "strength"
    LOSE_FAT = "lose_fat"
    STAMINA = "stamina"
    STAY_ACTIVE = "stay_active"


class FitnessLevel(StrEnum):
    """Set from training history, never self-rating (ADR 0012).

    beginner: never, on and off, or under 6 months of steady training.
    some_experience: 6 months to 2 years. experienced: 2+ years, still progressing.
    """

    BEGINNER = "beginner"
    SOME_EXPERIENCE = "some_experience"
    EXPERIENCED = "experienced"


class Location(StrEnum):
    HOME = "home"
    GYM = "gym"


class ShoulderDay(StrEnum):
    """Push pull legs only: which day trains shoulders (KB section 5, ADR 0012)."""

    PUSH = "push"
    LEGS = "legs"


class Obstacle(StrEnum):
    """Answers to "What's made it hard before?". Changes tips, reminders, quests; not the plan."""

    NO_TIME = "no_time"
    DONT_KNOW_WHAT_TO_DO = "dont_know_what_to_do"
    LOSE_MOTIVATION = "lose_motivation"
    GET_BORED = "get_bored"


class Equipment(StrEnum):
    """Kit an exercise needs (ADR 0010).

    Home users own any mix of the first three. GYM means "only a gym has it" (machines,
    cables, barbells, benches, racks); the exact item is in the exercise's `also_needs`.
    Gym users have everything except bands.
    """

    DUMBBELLS = "dumbbells"
    RESISTANCE_BANDS = "resistance_bands"
    PULL_UP_BAR = "pull_up_bar"
    GYM = "gym"


class BodyLimit(StrEnum):
    KNEES = "knees"
    BACK = "back"
    SHOULDERS = "shoulders"


class RoutineKind(StrEnum):
    """The shape of a user's week (Knowledge Base section 4, ADR 0014)."""

    FULL_BODY = "full_body"
    UPPER_LOWER = "upper_lower"
    PUSH_PULL_LEGS = "push_pull_legs"
    UPPER_LOWER_PPL = "upper_lower_ppl"  # 5 days: mixes upper/lower with push pull legs
    BRO_SPLIT = "bro_split"
    STRENGTH_AND_CARDIO = "strength_and_cardio"  # lose fat, 4+ days
    CIRCUITS_AND_CARDIO = "circuits_and_cardio"  # improve stamina


class SessionKind(StrEnum):
    """One session in the queue. Letters (full body A/B/C, upper A/B...) rotate in stage 2."""

    FULL_BODY = "full_body"
    UPPER = "upper"
    LOWER = "lower"
    PUSH = "push"
    PULL = "pull"
    LEGS = "legs"
    BRO_CHEST = "bro_chest"
    BRO_BACK = "bro_back"
    BRO_LEGS = "bro_legs"
    BRO_SHOULDERS = "bro_shoulders"
    BRO_ARMS = "bro_arms"
    CIRCUIT = "circuit"
    HIIT = "hiit"
    STEADY_CARDIO = "steady_cardio"
    LONG_CARDIO = "long_cardio"
    EASY_CARDIO = "easy_cardio"
    MOBILITY = "mobility"


class WorkoutFormat(StrEnum):
    """How a session's exercises are done (KB section 9)."""

    STRAIGHT_SETS = "straight_sets"  # all sets of one exercise, then the next
    SUPERSETS = "supersets"  # pairs done back to back, sharing the rest
    FIRST_STRAIGHT_THEN_SUPERSETS = "first_straight_then_supersets"  # 30-minute sessions
    CIRCUIT = "circuit"  # every exercise in a row, then repeat the round
    INTERVALS = "intervals"  # HIIT: timed work and rest, repeated in rounds
    CONTINUOUS = "continuous"  # one steady activity: walk, cycle, jog
    FLOW = "flow"  # mobility: one gentle move after another


class WorkoutStatus(StrEnum):
    """Where a planned workout is in the queue (ADR 0017). The next one = first pending."""

    PENDING = "pending"
    DONE = "done"  # set by the sessions stage when the workout is finished
    SKIPPED = "skipped"  # "Skip" on the next workout: no penalty, the queue moves on
    # Too many "too hard" taps in a week: the rest of the build-up weeks make way for the
    # recovery week, which comes early as earned recovery (ADR 0019). Not a skip.
    REPLACED_BY_RECOVERY = "replaced_by_recovery"
    # Back after 14+ days with only the recovery week left: the break was the rest, so
    # the recovery week is dropped (ADR 0021). Not a skip, never shown as missed.
    REPLACED_BY_BREAK = "replaced_by_break"


class WorkoutPart(StrEnum):
    """Which part of a workout a planned exercise belongs to, in the order they're done."""

    WARM_UP = "warm_up"
    MAIN = "main"
    FINISHER = "finisher"
    COOL_DOWN = "cool_down"


class PlanEndReason(StrEnum):
    """Why a plan stopped being the current one (ADR 0017)."""

    FINISHED = "finished"  # every workout done or skipped, and the next block was started
    ANSWERS_CHANGED = "answers_changed"  # the profile or safety screen changed the plan


class ComebackEndReason(StrEnum):
    """Why a comeback after a break stopped easing workouts (ADR 0021)."""

    DONE = "done"  # all its eased workouts were trained
    OPTED_OUT = "opted_out"  # "I kept training elsewhere"
    NEW_BREAK = "new_break"  # another break of 14+ days started a new comeback


class Feedback(StrEnum):
    """The one tap after a workout (brief 3.2). Skipped = no answer, never "just right"."""

    TOO_EASY = "too_easy"
    JUST_RIGHT = "just_right"
    TOO_HARD = "too_hard"


class SwapReason(StrEnum):
    """Why an exercise was swapped (ADR 0020)."""

    HURTS = "hurts"  # "This hurts, swap it": gone for good, until they bring it back
    ANOTHER = "another"  # "Show another": a different pick for today only


class BodyArea(StrEnum):
    """Where a swapped-out exercise hurt (optional, ADR 0020). The first three match
    BodyLimit, so the app can offer to add that limit to the profile."""

    KNEES = "knees"
    BACK = "back"
    SHOULDERS = "shoulders"
    OTHER = "other"


class ProgressChange(StrEnum):
    """What progression changed for one exercise after a workout (ADR 0019)."""

    # Up
    HEAVIER = "heavier"  # suggested weight up one step; reps start at the bottom again
    EXTRA_SET = "extra_set"  # one more set (or a set given back after a step back)
    LONGER_HOLD = "longer_hold"  # holds: +5 s, up to 60 s
    HARDER_MOVE = "harder_move"  # the next rung of the ladder (home, bodyweight)
    MORE_REPS = "more_reps"  # one "too easy": aim 2 reps higher next time
    # Back
    LIGHTER = "lighter"  # about 10% lighter
    FEWER_SETS = "fewer_sets"  # an extra set taken away, or one set fewer
    SHORTER_HOLD = "shorter_hold"  # holds: -10 s
    EASIER_MOVE = "easier_move"  # one rung down the ladder


class Caution(StrEnum):
    """Why an exercise may not suit this user (ADR 0013). Shown as a warning, not hidden.

    The first three match BodyLimit. The plan generator never picks a cautioned exercise.
    """

    KNEES = "knees"
    BACK = "back"
    SHOULDERS = "shoulders"
    LOW_INTENSITY = "low_intensity"  # too intense after a "yes" on the safety screen
    NOT_QUIET = "not_quiet"  # jumping: not for the quiet, small-space track


class ExerciseCategory(StrEnum):
    PUSH = "push"
    PULL = "pull"
    LEGS = "legs"
    CORE = "core"
    CARDIO = "cardio"
    MOBILITY = "mobility"


class MuscleGroup(StrEnum):
    """Muscle groups the engine counts weekly sets for (knowledge base, section 3)."""

    CHEST = "chest"
    BACK = "back"
    SHOULDERS = "shoulders"
    TRAPS = "traps"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    FOREARMS = "forearms"
    QUADS = "quads"
    HAMSTRINGS = "hamstrings"
    GLUTES = "glutes"
    ADDUCTORS = "adductors"
    CALVES = "calves"
    CORE = "core"


class MuscleHead(StrEnum):
    """The part of a muscle an exercise emphasises (knowledge base, section 5).

    No exercise isolates one head; a target means "most of the work goes here".
    """

    CHEST_UPPER = "chest_upper"
    CHEST_MID = "chest_mid"
    CHEST_LOWER = "chest_lower"
    DELT_FRONT = "delt_front"
    DELT_SIDE = "delt_side"
    DELT_REAR = "delt_rear"
    BICEPS_LONG = "biceps_long"  # outer head
    BICEPS_SHORT = "biceps_short"  # inner head
    BRACHIALIS = "brachialis"
    TRICEPS_LONG = "triceps_long"
    TRICEPS_LATERAL = "triceps_lateral"
    TRICEPS_MEDIAL = "triceps_medial"
    LATS = "lats"
    MID_BACK = "mid_back"  # rhomboids and middle traps
    SPINAL_ERECTORS = "spinal_erectors"
    UPPER_TRAPS = "upper_traps"
    LOWER_TRAPS = "lower_traps"
    QUADS_VASTUS = "quads_vastus"
    RECTUS_FEMORIS = "rectus_femoris"
    HAMSTRINGS_HIP = "hamstrings_hip"  # worked by hinging
    HAMSTRINGS_KNEE = "hamstrings_knee"  # worked by curling
    GLUTE_MAX = "glute_max"
    GLUTE_MED = "glute_med"
    GASTROCNEMIUS = "gastrocnemius"  # upper calf, straight knee
    SOLEUS = "soleus"  # lower calf, bent knee
    UPPER_ABS = "upper_abs"
    LOWER_ABS = "lower_abs"
    OBLIQUES = "obliques"
    DEEP_CORE = "deep_core"
    FOREARM_FLEXORS = "forearm_flexors"
    FOREARM_EXTENSORS = "forearm_extensors"
    BRACHIORADIALIS = "brachioradialis"
    ADDUCTORS = "adductors"


# Which muscle group each head belongs to. A test checks that every head is listed.
HEAD_GROUP: dict[MuscleHead, MuscleGroup] = {
    MuscleHead.CHEST_UPPER: MuscleGroup.CHEST,
    MuscleHead.CHEST_MID: MuscleGroup.CHEST,
    MuscleHead.CHEST_LOWER: MuscleGroup.CHEST,
    MuscleHead.DELT_FRONT: MuscleGroup.SHOULDERS,
    MuscleHead.DELT_SIDE: MuscleGroup.SHOULDERS,
    MuscleHead.DELT_REAR: MuscleGroup.SHOULDERS,
    MuscleHead.BICEPS_LONG: MuscleGroup.BICEPS,
    MuscleHead.BICEPS_SHORT: MuscleGroup.BICEPS,
    MuscleHead.BRACHIALIS: MuscleGroup.BICEPS,
    MuscleHead.TRICEPS_LONG: MuscleGroup.TRICEPS,
    MuscleHead.TRICEPS_LATERAL: MuscleGroup.TRICEPS,
    MuscleHead.TRICEPS_MEDIAL: MuscleGroup.TRICEPS,
    MuscleHead.LATS: MuscleGroup.BACK,
    MuscleHead.MID_BACK: MuscleGroup.BACK,
    MuscleHead.SPINAL_ERECTORS: MuscleGroup.BACK,
    MuscleHead.UPPER_TRAPS: MuscleGroup.TRAPS,
    MuscleHead.LOWER_TRAPS: MuscleGroup.TRAPS,
    MuscleHead.QUADS_VASTUS: MuscleGroup.QUADS,
    MuscleHead.RECTUS_FEMORIS: MuscleGroup.QUADS,
    MuscleHead.HAMSTRINGS_HIP: MuscleGroup.HAMSTRINGS,
    MuscleHead.HAMSTRINGS_KNEE: MuscleGroup.HAMSTRINGS,
    MuscleHead.GLUTE_MAX: MuscleGroup.GLUTES,
    MuscleHead.GLUTE_MED: MuscleGroup.GLUTES,
    MuscleHead.GASTROCNEMIUS: MuscleGroup.CALVES,
    MuscleHead.SOLEUS: MuscleGroup.CALVES,
    MuscleHead.UPPER_ABS: MuscleGroup.CORE,
    MuscleHead.LOWER_ABS: MuscleGroup.CORE,
    MuscleHead.OBLIQUES: MuscleGroup.CORE,
    MuscleHead.DEEP_CORE: MuscleGroup.CORE,
    MuscleHead.FOREARM_FLEXORS: MuscleGroup.FOREARMS,
    MuscleHead.FOREARM_EXTENSORS: MuscleGroup.FOREARMS,
    MuscleHead.BRACHIORADIALIS: MuscleGroup.FOREARMS,
    MuscleHead.ADDUCTORS: MuscleGroup.ADDUCTORS,
}


class MovementSlot(StrEnum):
    """A job in a workout template; different exercises fill it for different users."""

    # Legs
    SQUAT = "squat"
    SINGLE_LEG = "single_leg"
    HINGE = "hinge"
    BRIDGE = "bridge"
    LEG_CURL = "leg_curl"
    LEG_EXTENSION = "leg_extension"
    CALVES = "calves"
    ADDUCTORS = "adductors"
    # Push
    HORIZONTAL_PUSH = "horizontal_push"
    VERTICAL_PUSH = "vertical_push"
    CHEST_FLY = "chest_fly"
    LATERAL_RAISE = "lateral_raise"
    FRONT_RAISE = "front_raise"
    TRICEPS = "triceps"
    # Pull
    HORIZONTAL_PULL = "horizontal_pull"
    VERTICAL_PULL = "vertical_pull"
    REAR_DELT = "rear_delt"
    TRAPS = "traps"
    BICEPS = "biceps"
    FOREARMS = "forearms"
    # Core
    BRACE = "brace"
    AB_CURL = "ab_curl"
    SIDE_AND_ROTATION = "side_and_rotation"
    LOWER_BACK = "lower_back"
    CARRY = "carry"
    # Cardio and mobility
    CONDITIONING = "conditioning"
    WARM_UP = "warm_up"
    COOL_DOWN = "cool_down"


class ExerciseType(StrEnum):
    COMPOUND = "compound"  # several joints move: squat, row, press
    ISOLATION = "isolation"  # one joint moves: curl, lateral raise
    CARDIO = "cardio"
    MOBILITY = "mobility"


class Impact(StrEnum):
    """How much jumping / pounding. Drives the knee, low-intensity and women-at-home filters."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
