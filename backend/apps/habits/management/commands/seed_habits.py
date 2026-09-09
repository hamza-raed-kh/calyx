"""Seed the owner's real habits.

Idempotent: safe to re-run. Existing habits are left alone rather than
duplicated, so this can be used to add newly-defined habits later.
"""

from datetime import time

from django.core.management.base import BaseCommand
from django.db import transaction
from psycopg.types.range import Range

from apps.habits.enums import (
    ComponentMode,
    Frequency,
    PrayerKey,
    RolloverMode,
    SlotAnchor,
    WindowEndRule,
)
from apps.habits.models import (
    AppSettings,
    Habit,
    HabitComponent,
    HabitScheduleVersion,
    HabitSlot,
    Location,
    LocationPeriod,
)

# Fajr ends at SUNRISE, not at Dhuhr: "until the next prayer" would score an
# 11am Fajr as on time. Isha ends at Islamic midnight, the preferred limit.
PRAYERS = [
    ("fajr", "Fajr", PrayerKey.FAJR, WindowEndRule.SUNRISE),
    ("dhuhr", "Dhuhr", PrayerKey.DHUHR, WindowEndRule.NEXT_PRAYER),
    ("asr", "Asr", PrayerKey.ASR, WindowEndRule.NEXT_PRAYER),
    ("maghrib", "Maghrib", PrayerKey.MAGHRIB, WindowEndRule.NEXT_PRAYER),
    ("isha", "Isha", PrayerKey.ISHA, WindowEndRule.ISLAMIC_MIDNIGHT),
]


class Command(BaseCommand):
    help = "Create the owner's habits, location and app settings. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--latitude", type=float, required=True)
        parser.add_argument("--longitude", type=float, required=True)
        parser.add_argument("--timezone", default="Asia/Riyadh")
        parser.add_argument("--location-name", default="Home")
        parser.add_argument("--method", default="UMM_AL_QURA")
        parser.add_argument("--madhab", default="SHAFI")
        parser.add_argument("--rollover", default="03:00")

    @transaction.atomic
    def handle(self, *args, **options):
        settings = AppSettings.get()
        settings.timezone = options["timezone"]
        settings.day_rollover = time.fromisoformat(options["rollover"])
        settings.save()
        self.stdout.write(f"settings: rollover {settings.day_rollover} in {settings.timezone}")

        location, created = Location.objects.get_or_create(
            name=options["location_name"],
            defaults={
                "latitude": options["latitude"],
                "longitude": options["longitude"],
                "timezone": options["timezone"],
                "calc_method": options["method"],
                "madhab": options["madhab"],
            },
        )
        if created:
            LocationPeriod.objects.create(location=location, period=Range(None, None, "[)"))
        self.stdout.write(f"location: {location.name} ({'created' if created else 'existing'})")

        self._prayers()
        self._any_of("quran", "Quran", [("read", "Read"), ("listen", "Listen")], order=1)
        self._any_of(
            "chess", "Chess", [("chesscom", "chess.com"), ("duolingo", "Duolingo")], order=2
        )
        self._simple("transactions", "Log transactions", order=3)
        self._simple("reading", "Read a book", order=4, target=20, unit="pages")
        self._simple("walk", "Go for a walk", order=5, target=30, unit="minutes")
        self._weekly("piano", "Practise piano", times=3, order=6)
        self._teeth()
        self._work_session()
        self._simple("gaming", "Gaming session", order=9)

        self.stdout.write(self.style.SUCCESS("seeded"))

    # --- builders -----------------------------------------------------------

    def _habit(self, key, name, *, order, **kwargs) -> tuple[Habit, bool]:
        habit, created = Habit.objects.get_or_create(
            key=key, defaults={"name": name, "sort_order": order, **kwargs}
        )
        if created:
            self.stdout.write(f"  + {key}")
        return habit, created

    def _version(self, habit, **kwargs) -> HabitScheduleVersion:
        return HabitScheduleVersion.objects.create(
            habit=habit, valid=Range(None, None, "[)"), **kwargs
        )

    def _prayers(self):
        habit, created = self._habit("prayer", "Prayer", order=0)
        if not created:
            return
        # Fajr-anchored: the day runs Fajr to Fajr, so the five prayers land
        # inside it exactly once each by construction rather than by rule.
        version = self._version(habit, rollover_mode=RolloverMode.FAJR)
        for order, (key, label, prayer, end_rule) in enumerate(PRAYERS):
            HabitSlot.objects.create(
                schedule_version=version,
                key=key,
                label=label,
                sort_order=order,
                anchor=SlotAnchor.PRAYER,
                prayer_key=prayer,
                window_end_rule=end_rule,
                notify_offset_minutes=0,
                remind_before_end_minutes=20,
            )

    def _any_of(self, key, name, components, *, order):
        habit, created = self._habit(key, name, order=order, component_mode=ComponentMode.ANY_OF)
        if not created:
            return
        HabitSlot.objects.create(schedule_version=self._version(habit), key="default", label=name)
        for index, (component_key, label) in enumerate(components):
            HabitComponent.objects.create(
                habit=habit, key=component_key, label=label, sort_order=index
            )

    def _simple(self, key, name, *, order, target=None, unit=""):
        habit, created = self._habit(key, name, order=order)
        if not created:
            return
        HabitSlot.objects.create(
            schedule_version=self._version(habit),
            key="default",
            label=name,
            target_value=target,
            target_unit=unit,
        )

    def _weekly(self, key, name, *, times, order):
        habit, created = self._habit(key, name, order=order)
        if not created:
            return
        version = self._version(habit, frequency=Frequency.TIMES_PER_WEEK, times_per_week=times)
        HabitSlot.objects.create(schedule_version=version, key="default", label=name)

    def _teeth(self):
        habit, created = self._habit("teeth", "Brush teeth", order=7)
        if not created:
            return
        version = self._version(habit)
        HabitSlot.objects.create(
            schedule_version=version,
            key="morning",
            label="Morning",
            sort_order=0,
            anchor=SlotAnchor.FIXED_TIME,
            window_start_local=time(5, 0),
            window_end_local=time(12, 0),
        )
        HabitSlot.objects.create(
            schedule_version=version,
            key="evening",
            label="Evening",
            sort_order=1,
            anchor=SlotAnchor.FIXED_TIME,
            window_start_local=time(19, 0),
            window_end_local=time(3, 0),
            window_end_day_offset=1,
        )

    def _work_session(self):
        habit, created = self._habit(
            "work", "Work session", order=8, requires_project=True, allows_project=True
        )
        if not created:
            return
        HabitSlot.objects.create(
            schedule_version=self._version(habit),
            key="default",
            label="Work session",
            target_unit="minutes",
        )
