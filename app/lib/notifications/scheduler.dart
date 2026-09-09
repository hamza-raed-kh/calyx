import 'dart:convert';

import '../data/db/database.dart';

/// One thing to remind about.
class Reminder {
  const Reminder({
    required this.id,
    required this.title,
    required this.body,
    required this.at,
  });

  /// Deterministic, so cancelling is precise and rescheduling cannot duplicate.
  final int id;
  final String title;
  final String body;
  final DateTime at;
}

/// How well reminders can actually work on this platform.
enum ReminderCapability {
  /// Exact alarms, surviving reboot and app closure.
  exact,

  /// Scheduled, but the OS may delay them by up to ~15 minutes.
  inexact,

  /// Only while the app is running.
  foregroundOnly,

  /// Not available at all.
  none,
}

class ReminderStatus {
  const ReminderStatus({
    required this.capability,
    this.scheduled = 0,
    this.detail = '',
  });

  final ReminderCapability capability;
  final int scheduled;
  final String detail;

  String get summary => switch (capability) {
    ReminderCapability.exact => 'Exact reminders ($scheduled scheduled)',
    ReminderCapability.inexact =>
      'Approximate reminders ($scheduled scheduled) — may be up to 15 minutes late',
    ReminderCapability.foregroundOnly => 'Reminders only while the app is open',
    ReminderCapability.none => 'Reminders are not available on this platform',
  };
}

abstract class NotificationScheduler {
  Future<void> initialise();

  /// Replace the whole scheduled window. Cancel-and-reschedule rather than
  /// diffing: it is far easier to reason about, and the window is small.
  Future<ReminderStatus> reschedule(List<Reminder> reminders);

  Future<ReminderStatus> status();

  Future<void> cancelAll();
}

/// Builds the reminder list from cached agenda days.
///
/// A rolling seven days, not thirty. Android caps pending alarms; a settings
/// change takes effect within a day instead of a month; and moving cities does
/// not leave four weeks of wrong alarms pinned to the system.
List<Reminder> remindersFrom(
  List<AgendaDay> days, {
  DateTime? now,
  int horizonDays = 7,
}) {
  final from = now ?? DateTime.now();
  final until = from.add(Duration(days: horizonDays));
  final out = <Reminder>[];

  for (final day in days) {
    final payload = jsonDecode(day.payload) as Map<String, dynamic>;
    final rows = ((payload['occurrences'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();

    for (final row in rows) {
      if ((row['progress'] as Map?)?['satisfied'] == true) continue;

      final habit = (row['habit'] as Map).cast<String, dynamic>();
      final slot = (row['slot'] as Map).cast<String, dynamic>();

      for (final entry in [
        ('notify_at', '${slot['label']}'),
        ('remind_before_end', 'Closing soon: ${slot['label']}'),
      ]) {
        final key = entry.$1 == 'notify_at' ? 'notify_at' : 'remind_at';
        final raw = row[key] as String?;
        if (raw == null) continue;

        final at = DateTime.parse(raw).toLocal();
        if (at.isBefore(from) || at.isAfter(until)) continue;

        out.add(
          Reminder(
            id: _idFor('${row['id']}:$key'),
            title: habit['name'] as String? ?? 'Reminder',
            body: entry.$2,
            at: at,
          ),
        );
      }
    }
  }

  out.sort((a, b) => a.at.compareTo(b.at));
  return out;
}

/// Stable 31-bit id derived from the occurrence, so the same reminder always
/// gets the same slot and cancellation is exact.
int _idFor(String key) {
  var hash = 0;
  for (final unit in key.codeUnits) {
    hash = (hash * 31 + unit) & 0x7fffffff;
  }
  return hash;
}
