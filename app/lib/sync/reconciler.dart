import 'package:drift/drift.dart';

import '../data/db/database.dart';

/// Writes pulled server rows into the local mirror.
///
/// The rule that matters: a pulled row overwrites the local one UNLESS that row
/// still has an unsent local change. Without that guard the UI visibly snaps
/// back to a stale value mid-push, which is the offline-sync bug users describe
/// as "it lost my edit".
class Reconciler {
  Reconciler(this._db);

  final AppDatabase _db;

  Future<Set<String>> _pendingIds() async {
    final rows = await _db.select(_db.outboxEntries).get();
    return rows.map((row) => row.entityId).toSet();
  }

  Future<int> apply(Map<String, dynamic> changes) async {
    final pending = await _pendingIds();
    var applied = 0;

    for (final entry in changes.entries) {
      final rows =
          (entry.value as List?)?.cast<Map<String, dynamic>>() ?? const [];
      for (final row in rows) {
        final id = row['id'] as String?;
        if (id == null || pending.contains(id)) continue;
        if (await _applyRow(entry.key, row)) applied++;
      }
    }
    return applied;
  }

  Future<bool> _applyRow(String entity, Map<String, dynamic> row) async {
    switch (entity) {
      case 'habits':
        await _db
            .into(_db.habits)
            .insertOnConflictUpdate(
              HabitsCompanion.insert(
                id: row['id'] as String,
                key: row['key'] as String,
                name: row['name'] as String,
                icon: Value(row['icon'] as String? ?? ''),
                color: Value(row['color'] as String? ?? ''),
                componentMode: Value(
                  row['component_mode'] as String? ?? 'NONE',
                ),
                requiresProject: Value(
                  row['requires_project'] as bool? ?? false,
                ),
                allowsProject: Value(row['allows_project'] as bool? ?? false),
                sortOrder: Value(row['sort_order'] as int? ?? 0),
                archivedAt: Value(_time(row['archived_at'])),
                rowVersion: Value(row['row_version'] as int?),
                deletedAt: Value(_time(row['deleted_at'])),
              ),
            );
        return true;

      case 'habit_components':
        await _db
            .into(_db.habitComponents)
            .insertOnConflictUpdate(
              HabitComponentsCompanion.insert(
                id: row['id'] as String,
                habitId: row['habit'] as String,
                key: row['key'] as String,
                label: row['label'] as String,
                sortOrder: Value(row['sort_order'] as int? ?? 0),
                isActive: Value(row['is_active'] as bool? ?? true),
                rowVersion: Value(row['row_version'] as int?),
                deletedAt: Value(_time(row['deleted_at'])),
              ),
            );
        return true;

      case 'habit_logs':
        await _db
            .into(_db.habitLogs)
            .insertOnConflictUpdate(
              HabitLogsCompanion.insert(
                id: row['id'] as String,
                habitId: row['habit'] as String,
                slotKey: row['slot_key'] as String,
                habitDay: row['habit_day'] as String,
                occurredAt: _time(row['occurred_at'])!,
                componentId: Value(row['component'] as String?),
                projectId: Value(row['project'] as String?),
                value: Value(_number(row['value'])),
                unit: Value(row['unit'] as String? ?? ''),
                durationSeconds: Value(row['duration_seconds'] as int?),
                note: Value(row['note'] as String? ?? ''),
                status: Value(row['status'] as String? ?? 'UNKNOWN'),
                isPending: const Value(false),
                rowVersion: Value(row['row_version'] as int?),
                deletedAt: Value(_time(row['deleted_at'])),
              ),
            );
        return true;

      case 'projects':
        await _db
            .into(_db.projects)
            .insertOnConflictUpdate(
              ProjectsCompanion.insert(
                id: row['id'] as String,
                name: row['name'] as String,
                color: Value(row['color'] as String? ?? ''),
                icon: Value(row['icon'] as String? ?? ''),
                sortOrder: Value(row['sort_order'] as int? ?? 0),
                archivedAt: Value(_time(row['archived_at'])),
                rowVersion: Value(row['row_version'] as int?),
                deletedAt: Value(_time(row['deleted_at'])),
              ),
            );
        return true;

      case 'tags':
        await _db
            .into(_db.tags)
            .insertOnConflictUpdate(
              TagsCompanion.insert(
                id: row['id'] as String,
                name: row['name'] as String,
                color: Value(row['color'] as String? ?? ''),
                rowVersion: Value(row['row_version'] as int?),
                deletedAt: Value(_time(row['deleted_at'])),
              ),
            );
        return true;

      case 'tasks':
        await _db
            .into(_db.tasks)
            .insertOnConflictUpdate(
              TasksCompanion.insert(
                id: row['id'] as String,
                title: row['title'] as String,
                projectId: Value(row['project'] as String?),
                parentId: Value(row['parent'] as String?),
                notes: Value(row['notes'] as String? ?? ''),
                priority: Value(row['priority'] as int? ?? 0),
                dueAt: Value(_time(row['due_at'])),
                scheduledFor: Value(row['scheduled_for'] as String?),
                completedAt: Value(_time(row['completed_at'])),
                recurrence: Value(row['recurrence'] as String? ?? ''),
                sortOrder: Value(row['sort_order'] as int? ?? 0),
                isPending: const Value(false),
                rowVersion: Value(row['row_version'] as int?),
                deletedAt: Value(_time(row['deleted_at'])),
              ),
            );
        return true;

      default:
        // Entities the client does not mirror -- locations, prayer times,
        // schedule versions, slots. The cursor still advances past them, which
        // is correct: the client consumes the agenda they produce, not the
        // inputs themselves.
        return false;
    }
  }

  /// Record a row a push overwrote that had moved on the server.
  ///
  /// Last-write-wins still applies. This exists so "my edit vanished" is an
  /// answerable question rather than a mystery.
  Future<void> recordConflict(
    String entity,
    String entityId,
    String overwritten,
  ) {
    return _db
        .into(_db.conflictLog)
        .insert(
          ConflictLogCompanion.insert(
            entity: entity,
            entityId: entityId,
            overwritten: overwritten,
            detectedAt: DateTime.now().toUtc(),
          ),
        );
  }
}

DateTime? _time(Object? value) =>
    value == null ? null : DateTime.parse(value as String).toUtc();

double? _number(Object? value) {
  if (value == null) return null;
  if (value is num) return value.toDouble();
  return double.tryParse(value.toString());
}
