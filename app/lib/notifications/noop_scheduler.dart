import 'scheduler.dart';

/// Web.
///
/// flutter_local_notifications has no web implementation, and Web Push would
/// require reaching public FCM or Mozilla endpoints -- which contradicts a
/// deployment that is deliberately not on the public internet. In-app banners
/// only; Android is the notification surface.
class NoopScheduler implements NotificationScheduler {
  @override
  Future<void> initialise() async {}

  @override
  Future<ReminderStatus> reschedule(List<Reminder> reminders) async => status();

  @override
  Future<ReminderStatus> status() async => const ReminderStatus(
    capability: ReminderCapability.none,
    detail: 'Web notifications would require an external push service.',
  );

  @override
  Future<void> cancelAll() async {}
}

NotificationScheduler createScheduler() => NoopScheduler();
