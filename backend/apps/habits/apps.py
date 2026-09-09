from django.apps import AppConfig


class HabitsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.habits"

    def ready(self) -> None:
        from apps.sync.registry import registry

        from . import models as m
        from . import serializers as s

        registry.register("app_settings", m.AppSettings, s.AppSettingsSerializer)
        registry.register("locations", m.Location, s.LocationSerializer)
        registry.register("location_periods", m.LocationPeriod, s.LocationPeriodSerializer)
        registry.register("prayer_times", m.PrayerTimeDay, s.PrayerTimeDaySerializer)
        registry.register("habits", m.Habit, s.HabitSerializer)
        registry.register("habit_schedules", m.HabitScheduleVersion, s.ScheduleVersionSerializer)
        registry.register("habit_slots", m.HabitSlot, s.HabitSlotSerializer)
        registry.register("habit_components", m.HabitComponent, s.HabitComponentSerializer)
        registry.register("habit_logs", m.HabitLog, s.HabitLogSerializer)
