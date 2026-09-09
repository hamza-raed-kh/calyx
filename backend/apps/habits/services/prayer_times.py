"""Computes and materialises prayer times.

This is the one thing in the habit engine that IS materialised. Not because
recomputing is slow, but because the result is a user-visible judgment: whether
a log was on time. Computing it in one place, storing it, and syncing the stored
rows means the phone and the server can never disagree about what a window was.
"""

import logging
from datetime import date as date_cls
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from adhanpy.calculation.CalculationMethod import CalculationMethod
from adhanpy.calculation.CalculationParameters import CalculationParameters
from adhanpy.calculation.HighLatitudeRule import HighLatitudeRule as AdhanHighLatitudeRule
from adhanpy.calculation.Madhab import Madhab as AdhanMadhab
from adhanpy.PrayerTimes import PrayerTimes

from ..enums import HighLatitudeRule, Madhab, PrayerKey
from ..models import Location, PrayerTimeDay

logger = logging.getLogger(__name__)

ENGINE_VERSION = "adhanpy-1.0.5"

PRAYER_FIELDS = ("fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha")


def _params(location: Location) -> CalculationParameters:
    params = CalculationParameters(method=CalculationMethod[location.calc_method])
    params.madhab = AdhanMadhab.HANAFI if location.madhab == Madhab.HANAFI else AdhanMadhab.SHAFI
    params.high_latitude_rule = {
        HighLatitudeRule.MIDDLE_OF_THE_NIGHT: AdhanHighLatitudeRule.MIDDLE_OF_THE_NIGHT,
        HighLatitudeRule.SEVENTH_OF_THE_NIGHT: AdhanHighLatitudeRule.SEVENTH_OF_THE_NIGHT,
        HighLatitudeRule.TWILIGHT_ANGLE: AdhanHighLatitudeRule.TWILIGHT_ANGLE,
    }[location.high_latitude_rule]
    return params


def compute_day(location: Location, solar_date: date_cls) -> dict[str, datetime | None]:
    """Raw prayer times for one solar date, in UTC.

    Returns None for any prayer the solver could not produce. At high latitude
    Fajr and Isha genuinely do not exist on some dates, and the engine must
    degrade rather than raise.
    """
    tz = ZoneInfo(location.timezone)
    coordinates = (float(location.latitude), float(location.longitude))
    when = datetime(solar_date.year, solar_date.month, solar_date.day, 12, tzinfo=tz)

    try:
        times = PrayerTimes(
            coordinates, when, calculation_parameters=_params(location), time_zone=tz
        )
    except Exception:
        logger.warning(
            "prayer times unavailable for %s on %s", location.name, solar_date, exc_info=True
        )
        return dict.fromkeys(PRAYER_FIELDS)

    adjustments = location.adjustments or {}
    result: dict[str, datetime | None] = {}
    for field in PRAYER_FIELDS:
        value = getattr(times, field, None)
        if value is not None:
            offset = adjustments.get(field, 0)
            value = (value + timedelta(minutes=offset)).astimezone(ZoneInfo("UTC"))
        result[field] = value
    return result


def islamic_midnight(maghrib: datetime | None, next_fajr: datetime | None) -> datetime | None:
    """Midpoint between Maghrib and the following Fajr.

    The preferred limit for Isha in most fiqh, and a far more meaningful window
    end than "until the next prayer" -- which would make a 4am Isha on time.
    """
    if maghrib is None or next_fajr is None or next_fajr <= maghrib:
        return None
    return maghrib + (next_fajr - maghrib) / 2


def ensure_prayer_times(
    location: Location, start: date_cls, end: date_cls, *, force: bool = False
) -> int:
    """Materialise PrayerTimeDay rows for [start, end]. Returns rows written.

    Called both by a daily job maintaining a horizon and lazily by the agenda
    endpoint. Belt and braces on purpose: a cron that fails silently must not be
    able to make the app stop having a today.
    """
    if end < start:
        return 0

    fingerprint = location.params_hash()

    existing = {
        row.solar_date: row
        for row in PrayerTimeDay.objects.filter(
            location=location, solar_date__gte=start, solar_date__lte=end
        )
    }

    wanted = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    missing = [
        day
        for day in wanted
        if force
        or day not in existing
        or existing[day].params_hash != fingerprint
        or existing[day].engine_version != ENGINE_VERSION
    ]
    if not missing:
        return 0

    # Isha's window ends at Islamic midnight, which needs the NEXT day's Fajr,
    # so always compute one day beyond the range being written.
    computed = {day: compute_day(location, day) for day in missing}
    for day in missing:
        following = day + timedelta(days=1)
        if following not in computed:
            computed[following] = compute_day(location, following)

    written = 0
    for day in missing:
        times = computed[day]
        row = existing.get(day) or PrayerTimeDay(location=location, solar_date=day)
        row.fajr_at = times["fajr"]
        row.sunrise_at = times["sunrise"]
        row.dhuhr_at = times["dhuhr"]
        row.asr_at = times["asr"]
        row.maghrib_at = times["maghrib"]
        row.isha_at = times["isha"]
        row.islamic_midnight_at = islamic_midnight(
            times["maghrib"], computed[day + timedelta(days=1)]["fajr"]
        )
        row.params_hash = fingerprint
        row.engine_version = ENGINE_VERSION
        row.save()
        written += 1

    return written


def next_prayer_after(row: PrayerTimeDay, prayer: str, following: PrayerTimeDay | None):
    """The start of the prayer after `prayer`, crossing into the next day for Isha."""
    order = [PrayerKey.FAJR, PrayerKey.DHUHR, PrayerKey.ASR, PrayerKey.MAGHRIB, PrayerKey.ISHA]
    index = order.index(prayer)
    if index + 1 < len(order):
        return row.time_for(order[index + 1])
    return following.fajr_at if following is not None else None
