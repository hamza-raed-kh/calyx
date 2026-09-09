from django.db import models


class CalcMethod(models.TextChoices):
    MUSLIM_WORLD_LEAGUE = "MUSLIM_WORLD_LEAGUE", "Muslim World League"
    EGYPTIAN = "EGYPTIAN", "Egyptian General Authority"
    KARACHI = "KARACHI", "University of Islamic Sciences, Karachi"
    UMM_AL_QURA = "UMM_AL_QURA", "Umm al-Qura, Makkah"
    DUBAI = "DUBAI", "Dubai"
    MOON_SIGHTING_COMMITTEE = "MOON_SIGHTING_COMMITTEE", "Moonsighting Committee"
    NORTH_AMERICA = "NORTH_AMERICA", "ISNA, North America"
    KUWAIT = "KUWAIT", "Kuwait"
    QATAR = "QATAR", "Qatar"
    SINGAPORE = "SINGAPORE", "Singapore"
    UOIF = "UOIF", "Union des Organisations Islamiques de France"


class Madhab(models.TextChoices):
    SHAFI = "SHAFI", "Standard (Shafi'i, Maliki, Hanbali)"
    HANAFI = "HANAFI", "Hanafi"


class HighLatitudeRule(models.TextChoices):
    MIDDLE_OF_THE_NIGHT = "MIDDLE_OF_THE_NIGHT", "Middle of the night"
    SEVENTH_OF_THE_NIGHT = "SEVENTH_OF_THE_NIGHT", "Seventh of the night"
    TWILIGHT_ANGLE = "TWILIGHT_ANGLE", "Twilight angle"


class PrayerKey(models.TextChoices):
    FAJR = "FAJR", "Fajr"
    DHUHR = "DHUHR", "Dhuhr"
    ASR = "ASR", "Asr"
    MAGHRIB = "MAGHRIB", "Maghrib"
    ISHA = "ISHA", "Isha"


class SlotAnchor(models.TextChoices):
    ALL_DAY = "ALL_DAY", "All day"
    FIXED_TIME = "FIXED_TIME", "Fixed local time"
    PRAYER = "PRAYER", "Anchored to a prayer time"


class WindowEndRule(models.TextChoices):
    NEXT_PRAYER = "NEXT_PRAYER", "Until the next prayer"
    SUNRISE = "SUNRISE", "Until sunrise"
    ISLAMIC_MIDNIGHT = "ISLAMIC_MIDNIGHT", "Until Islamic midnight"
    FIXED_MINUTES = "FIXED_MINUTES", "For a fixed number of minutes"


class Frequency(models.TextChoices):
    DAILY = "DAILY", "Every eligible day"
    TIMES_PER_WEEK = "TIMES_PER_WEEK", "N times per week"


class RolloverMode(models.TextChoices):
    INHERIT = "INHERIT", "Use the app-wide rollover"
    FIXED = "FIXED", "Fixed local time"
    FAJR = "FAJR", "Fajr to Fajr"


class ComponentMode(models.TextChoices):
    NONE = "NONE", "No components"
    ANY_OF = "ANY_OF", "Any one component satisfies"


class LogStatus(models.TextChoices):
    ON_TIME = "ON_TIME", "On time"
    LATE = "LATE", "Late"
    EARLY = "EARLY", "Before the window opened"
    UNKNOWN = "UNKNOWN", "Time not recorded"


class EntryMode(models.TextChoices):
    LIVE = "LIVE", "Logged as it happened"
    BACKFILL = "BACKFILL", "Filled in afterwards"
    IMPORT = "IMPORT", "Imported"


class Requirement(models.TextChoices):
    REQUIRED = "REQUIRED", "Required today"
    TOWARD_PERIOD = "TOWARD_PERIOD", "Counts toward a period target"
    UNAVAILABLE = "UNAVAILABLE", "Cannot be computed"
