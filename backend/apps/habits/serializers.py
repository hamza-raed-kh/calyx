from rest_framework import serializers

from apps.sync.serializers import SyncableSerializer

from . import models as m


class DateRangeField(serializers.Field):
    """psycopg DateRange as a JSON object, since the client needs both bounds."""

    def to_representation(self, value):
        return {
            "lower": value.lower.isoformat() if value.lower else None,
            "upper": value.upper.isoformat() if value.upper else None,
        }

    def to_internal_value(self, data):
        from datetime import date

        from psycopg.types.range import Range

        if not isinstance(data, dict):
            raise serializers.ValidationError("expected an object with lower/upper")
        lower = date.fromisoformat(data["lower"]) if data.get("lower") else None
        upper = date.fromisoformat(data["upper"]) if data.get("upper") else None
        return Range(lower, upper, "[)")


class AppSettingsSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = m.AppSettings
        fields = [
            *SyncableSerializer.Meta.fields,
            "timezone",
            "day_rollover",
            "backfill_days",
            "week_starts_on",
            "prefetch_horizon_days",
        ]


class LocationSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = m.Location
        fields = [
            *SyncableSerializer.Meta.fields,
            "name",
            "latitude",
            "longitude",
            "timezone",
            "elevation_m",
            "calc_method",
            "madhab",
            "high_latitude_rule",
            "adjustments",
        ]


class LocationPeriodSerializer(SyncableSerializer):
    period = DateRangeField()

    class Meta(SyncableSerializer.Meta):
        model = m.LocationPeriod
        fields = [*SyncableSerializer.Meta.fields, "location", "period", "note"]


class PrayerTimeDaySerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = m.PrayerTimeDay
        fields = [
            *SyncableSerializer.Meta.fields,
            "location",
            "solar_date",
            "fajr_at",
            "sunrise_at",
            "dhuhr_at",
            "asr_at",
            "maghrib_at",
            "isha_at",
            "islamic_midnight_at",
            "params_hash",
            "engine_version",
        ]


class HabitSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = m.Habit
        fields = [
            *SyncableSerializer.Meta.fields,
            "key",
            "name",
            "icon",
            "color",
            "component_mode",
            "requires_project",
            "allows_project",
            "sort_order",
            "notes",
            "archived_at",
        ]


class ScheduleVersionSerializer(SyncableSerializer):
    valid = DateRangeField()

    class Meta(SyncableSerializer.Meta):
        model = m.HabitScheduleVersion
        fields = [
            *SyncableSerializer.Meta.fields,
            "habit",
            "valid",
            "frequency",
            "times_per_week",
            "week_starts_on",
            "days_of_week",
            "rollover_mode",
            "rollover_time",
            "change_reason",
        ]


class HabitSlotSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = m.HabitSlot
        fields = [
            *SyncableSerializer.Meta.fields,
            "schedule_version",
            "key",
            "label",
            "sort_order",
            "anchor",
            "window_start_local",
            "window_end_local",
            "window_end_day_offset",
            "prayer_key",
            "window_end_rule",
            "window_end_minutes",
            "target_value",
            "target_unit",
            "notify_offset_minutes",
            "remind_before_end_minutes",
        ]


class HabitComponentSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = m.HabitComponent
        fields = [
            *SyncableSerializer.Meta.fields,
            "habit",
            "key",
            "label",
            "sort_order",
            "is_active",
            "archived_at",
        ]


class HabitLogSerializer(SyncableSerializer):
    class Meta(SyncableSerializer.Meta):
        model = m.HabitLog
        fields = [
            *SyncableSerializer.Meta.fields,
            "habit",
            "slot_key",
            "habit_day",
            "occurred_at",
            "component",
            "project",
            "value",
            "unit",
            "duration_seconds",
            "note",
            "status",
            "window_start_at",
            "window_end_at",
            "schedule_version",
            "location",
            "entry_mode",
        ]
