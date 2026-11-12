from enum import StrEnum


class Goal(StrEnum):
    STRENGTH = "strength"
    LOSE_FAT = "lose_fat"
    STAMINA = "stamina"
    STAY_ACTIVE = "stay_active"


class FitnessLevel(StrEnum):
    BEGINNER = "beginner"
    SOME_EXPERIENCE = "some_experience"
    EXPERIENCED = "experienced"


class Location(StrEnum):
    HOME = "home"
    GYM = "gym"


class Equipment(StrEnum):
    DUMBBELLS = "dumbbells"
    RESISTANCE_BANDS = "resistance_bands"
    PULL_UP_BAR = "pull_up_bar"
    BARBELL = "barbell"
    BENCH = "bench"
    CABLE_MACHINE = "cable_machine"
    KETTLEBELL = "kettlebell"


class BodyLimit(StrEnum):
    KNEES = "knees"
    BACK = "back"
    SHOULDERS = "shoulders"


class ExerciseCategory(StrEnum):
    PUSH = "push"
    PULL = "pull"
    LEGS = "legs"
    CORE = "core"
    CARDIO = "cardio"
    MOBILITY = "mobility"


class MuscleGroup(StrEnum):
    CHEST = "chest"
    BACK = "back"
    SHOULDERS = "shoulders"
    ARMS = "arms"
    CORE = "core"
    LEGS = "legs"
    GLUTES = "glutes"
    FULL_BODY = "full_body"
