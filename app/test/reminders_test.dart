import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:calyx/data/db/database.dart';
import 'package:calyx/notifications/scheduler.dart';

AgendaDay day(String date, List<Map<String, dynamic>> occurrences) {
  return AgendaDay(
    day: date,
    payload: jsonEncode({'habit_day': date, 'occurrences': occurrences}),
    fetchedAt: DateTime.utc(2026, 9, 9),
  );
}

Map<String, dynamic> occurrence({
  required String id,
  String? notifyAt,
  String? remindAt,
  bool satisfied = false,
}) {
  return {
    'id': id,
    'habit': {'id': 'h1', 'key': 'prayer', 'name': 'Prayer'},
    'slot': {'key': 'fajr', 'label': 'Fajr'},
    'notify_at': notifyAt,
    'remind_at': remindAt,
    'progress': {'satisfied': satisfied},
  };
}

void main() {
  final now = DateTime(2026, 9, 9, 6);

  group('remindersFrom', () {
    test('builds one reminder per notify time', () {
      final reminders = remindersFrom([
        day('2026-09-09', [
          occurrence(
            id: 'prayer:fajr:2026-09-09',
            notifyAt: '2026-09-09T09:00:00Z',
          ),
        ]),
      ], now: now);

      expect(reminders, hasLength(1));
      expect(reminders.single.title, 'Prayer');
    });

    test('skips anything already satisfied', () {
      final reminders = remindersFrom([
        day('2026-09-09', [
          occurrence(
            id: 'prayer:fajr:2026-09-09',
            notifyAt: '2026-09-09T09:00:00Z',
            satisfied: true,
          ),
        ]),
      ], now: now);
      expect(reminders, isEmpty);
    });

    test('drops times in the past', () {
      final reminders = remindersFrom([
        day('2026-09-09', [
          occurrence(id: 'a', notifyAt: '2026-09-09T00:00:00Z'),
        ]),
      ], now: now);
      expect(reminders, isEmpty);
    });

    test('stops at the horizon rather than scheduling a month of alarms', () {
      final reminders = remindersFrom([
        day('2026-09-09', [
          occurrence(id: 'near', notifyAt: '2026-09-10T09:00:00Z'),
          occurrence(id: 'far', notifyAt: '2026-10-09T09:00:00Z'),
        ]),
      ], now: now);
      expect(reminders, hasLength(1));
    });

    test('ids are deterministic so rescheduling cannot duplicate', () {
      final input = [
        day('2026-09-09', [
          occurrence(
            id: 'prayer:fajr:2026-09-09',
            notifyAt: '2026-09-09T09:00:00Z',
          ),
        ]),
      ];
      final first = remindersFrom(input, now: now);
      final second = remindersFrom(input, now: now);
      expect(first.single.id, second.single.id);
    });

    test('a notify and a closing-soon reminder do not collide', () {
      final reminders = remindersFrom([
        day('2026-09-09', [
          occurrence(
            id: 'prayer:fajr:2026-09-09',
            notifyAt: '2026-09-09T09:00:00Z',
            remindAt: '2026-09-09T10:00:00Z',
          ),
        ]),
      ], now: now);

      expect(reminders, hasLength(2));
      expect(reminders.first.id, isNot(reminders.last.id));
      expect(reminders.last.body, contains('Closing soon'));
    });

    test('reminders come back in chronological order', () {
      final reminders = remindersFrom([
        day('2026-09-09', [
          occurrence(id: 'b', notifyAt: '2026-09-09T18:00:00Z'),
          occurrence(id: 'a', notifyAt: '2026-09-09T09:00:00Z'),
        ]),
      ], now: now);
      expect(reminders.first.at.isBefore(reminders.last.at), isTrue);
    });
  });
}
