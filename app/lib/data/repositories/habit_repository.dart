import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';

import '../../sync/outbox.dart';
import '../../sync/sync_engine.dart';
import '../db/database.dart';

/// Writes habit logs locally and queues them for adjudication.
///
/// The local row appears immediately so a tick made on a train looks ticked;
/// the server later decides on-time versus late and the echoed row replaces
/// this one, keeping that judgment in exactly one place.
class HabitRepository {
  HabitRepository(this._db, this._outbox);

  final AppDatabase _db;
  final Outbox _outbox;
  static const _uuid = Uuid();

  Future<String> logOccurrence(
    Map<String, dynamic> occurrence, {
    String? componentKey,
    double? value,
    String? projectId,
    int? durationSeconds,
    String note = '',
  }) async {
    final logId = _uuid.v7();
    final habit = (occurrence['habit'] as Map).cast<String, dynamic>();
    final slot = (occurrence['slot'] as Map).cast<String, dynamic>();
    final occurredAt = DateTime.now().toUtc();

    await _db
        .into(_db.habitLogs)
        .insert(
          HabitLogsCompanion.insert(
            id: logId,
            habitId: habit['id'] as String,
            slotKey: slot['key'] as String,
            habitDay: occurrence['habit_day'] as String,
            occurredAt: occurredAt,
            projectId: Value(projectId),
            value: Value(value),
            durationSeconds: Value(durationSeconds),
            note: Value(note),
            // Deliberately not guessed locally. The server owns the on-time
            // verdict; showing PENDING is honest until it says otherwise.
            status: const Value('PENDING'),
            isPending: const Value(true),
          ),
        );

    await _outbox.enqueue(
      entity: SyncEngine.habitLogIntent,
      op: 'upsert',
      entityId: logId,
      payload: {
        'occurrence_id': occurrence['id'],
        'occurred_at': occurredAt.toIso8601String(),
        'component': ?componentKey,
        if (value != null) 'value': value.toString(),
        'project': ?projectId,
        'duration_seconds': ?durationSeconds,
        if (note.isNotEmpty) 'note': note,
        'client_ts': occurredAt.toIso8601String(),
      },
    );
    return logId;
  }

  /// Undo a log. Tombstones locally and queues the delete.
  Future<void> undo(String logId) async {
    await (_db.update(_db.habitLogs)..where((t) => t.id.equals(logId))).write(
      HabitLogsCompanion(deletedAt: Value(DateTime.now().toUtc())),
    );
    await _outbox.enqueue(
      entity: 'habit_logs',
      op: 'delete',
      entityId: logId,
      payload: const {},
    );
  }
}
