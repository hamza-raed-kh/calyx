import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';

import '../../sync/outbox.dart';
import '../db/database.dart';

class TaskRepository {
  TaskRepository(this._db, this._outbox);

  final AppDatabase _db;
  final Outbox _outbox;
  static const _uuid = Uuid();

  Future<String> create({
    required String title,
    String? projectId,
    DateTime? dueAt,
    int priority = 0,
  }) async {
    final id = _uuid.v7();
    await _db
        .into(_db.tasks)
        .insert(
          TasksCompanion.insert(
            id: id,
            title: title,
            projectId: Value(projectId),
            dueAt: Value(dueAt),
            priority: Value(priority),
            isPending: const Value(true),
          ),
        );
    await _outbox.enqueue(
      entity: 'tasks',
      op: 'upsert',
      entityId: id,
      payload: {
        'title': title,
        'project': projectId,
        'due_at': dueAt?.toIso8601String(),
        'priority': priority,
      },
    );
    return id;
  }

  /// Set completion to a value; never toggle.
  ///
  /// A retried toggle undoes itself, which is precisely the corruption an
  /// offline queue invites. A retried set-value is a no-op.
  Future<void> setComplete(Task task, {required bool complete}) async {
    final completedAt = complete ? DateTime.now().toUtc() : null;
    await (_db.update(_db.tasks)..where((t) => t.id.equals(task.id))).write(
      TasksCompanion(
        completedAt: Value(completedAt),
        isPending: const Value(true),
      ),
    );
    await _outbox.enqueue(
      entity: 'tasks',
      op: 'upsert',
      entityId: task.id,
      baseRowVersion: task.rowVersion,
      payload: {
        'title': task.title,
        'completed_at': completedAt?.toIso8601String(),
      },
    );
  }

  Future<void> delete(Task task) async {
    await (_db.update(_db.tasks)..where((t) => t.id.equals(task.id))).write(
      TasksCompanion(deletedAt: Value(DateTime.now().toUtc())),
    );
    await _outbox.enqueue(
      entity: 'tasks',
      op: 'delete',
      entityId: task.id,
      baseRowVersion: task.rowVersion,
      payload: const {},
    );
  }
}
