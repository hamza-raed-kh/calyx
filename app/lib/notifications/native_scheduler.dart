import 'dart:io';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import 'scheduler.dart';

/// Android and Linux desktop.
class NativeScheduler implements NotificationScheduler {
  final _plugin = FlutterLocalNotificationsPlugin();
  bool _ready = false;
  int _scheduled = 0;

  static const _channel = AndroidNotificationDetails(
    'habits',
    'Habits and prayers',
    channelDescription: 'Reminders for prayer windows and habits',
    importance: Importance.high,
    priority: Priority.high,
  );

  @override
  Future<void> initialise() async {
    if (_ready) return;

    tzdata.initializeTimeZones();
    final name = await FlutterTimezone.getLocalTimezone();
    tz.setLocalLocation(tz.getLocation(name.identifier));

    await _plugin.initialize(
      settings: const InitializationSettings(
        android: AndroidInitializationSettings('@mipmap/ic_launcher'),
        linux: LinuxInitializationSettings(defaultActionName: 'Open'),
      ),
    );

    if (Platform.isAndroid) {
      final android = _plugin
          .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin
          >();
      await android?.requestNotificationsPermission();
    }
    _ready = true;
  }

  @override
  Future<ReminderStatus> reschedule(List<Reminder> reminders) async {
    await initialise();

    if (Platform.isLinux) {
      // zonedSchedule throws UnimplementedError on Linux -- the plugin made
      // this an explicit failure rather than a silent no-op. Scheduling would
      // need something outside Flutter (a systemd user timer), which is not
      // worth it for the "sitting at my desk" surface.
      return const ReminderStatus(
        capability: ReminderCapability.foregroundOnly,
        detail: 'Linux scheduling is not supported by the plugin.',
      );
    }

    await _plugin.cancelAll();

    // Checked before EVERY pass, not once at install: on Android 14+ exact
    // alarms are denied by default for apps that are not clocks or calendars,
    // and the grant can disappear after a backup-and-restore transfer.
    final android = _plugin
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >();
    final exact = await android?.canScheduleExactNotifications() ?? false;

    final mode = exact
        ? AndroidScheduleMode.exactAllowWhileIdle
        : AndroidScheduleMode.inexactAllowWhileIdle;

    var count = 0;
    for (final reminder in reminders) {
      await _plugin.zonedSchedule(
        id: reminder.id,
        title: reminder.title,
        body: reminder.body,
        // An explicit TZDateTime, never DateTime.now().add(): the latter breaks
        // across a DST transition, which for prayer reminders is exactly when
        // being wrong matters.
        scheduledDate: tz.TZDateTime.from(reminder.at, tz.local),
        notificationDetails: const NotificationDetails(android: _channel),
        androidScheduleMode: mode,
      );
      count++;
    }
    _scheduled = count;

    return ReminderStatus(
      // Degrade visibly. Silently scheduling nothing is what everyone ships and
      // nobody notices until a prayer has been missed for a week.
      capability: exact ? ReminderCapability.exact : ReminderCapability.inexact,
      scheduled: count,
      detail: exact ? '' : 'Grant "Alarms & reminders" for on-time reminders.',
    );
  }

  @override
  Future<ReminderStatus> status() async {
    if (Platform.isLinux) {
      return ReminderStatus(
        capability: ReminderCapability.foregroundOnly,
        scheduled: _scheduled,
      );
    }
    final android = _plugin
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >();
    final exact = await android?.canScheduleExactNotifications() ?? false;
    return ReminderStatus(
      capability: exact ? ReminderCapability.exact : ReminderCapability.inexact,
      scheduled: _scheduled,
    );
  }

  @override
  Future<void> cancelAll() async {
    await _plugin.cancelAll();
    _scheduled = 0;
  }

  /// Route the user to the system screen that grants exact alarms.
  Future<void> requestExactAlarms() async {
    final android = _plugin
        .resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin
        >();
    await android?.requestExactAlarmsPermission();
  }
}

NotificationScheduler createScheduler() => NativeScheduler();
