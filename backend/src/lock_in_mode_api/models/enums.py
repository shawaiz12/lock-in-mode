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


class BodyLimit(StrEnum):
    KNEES = "knees"
    BACK = "back"
    SHOULDERS = "shoulders"