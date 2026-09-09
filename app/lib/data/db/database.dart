import 'package:drift/drift.dart';

import 'connection/connection.dart';
import 'persistence.dart';

part 'database.g.dart';

/// Durable queue of local mutations awaiting push.
///
/// `seq` is the client-local ordering the push endpoint replays in. `mutationId`
/// is the server-side idempotency key, so a retry after a network failure of
/// unknown outcome is free.
class OutboxEntries extends Table {
  IntColumn get seq => integer().autoIncrement()();
  TextColumn get mutationId => text().unique()();
  TextColumn get entity => text()();
  TextColumn get op => text()();
  TextColumn get entityId => text()();
  TextColumn get payload => text()();
  DateTimeColumn get clientTs => dateTime()();
  IntColumn get baseRowVersion => integer().nullable()();
  IntColumn get attempts => integer().withDefault(const Constant(0))();
  TextColumn get lastError => text().nullable()();
}

/// Mutations the server rejected as permanently invalid.
///
/// Exists from day one on purpose: a poison mutation that retries forever is
/// the most likely way an offline sync engine breaks, and the failure is
/// invisible without somewhere to put the casualty.
class DeadLetters extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get mutationId => text()();
  TextColumn get entity => text()();
  TextColumn get payload => text()();
  TextColumn get reason => text()();
  DateTimeColumn get rejectedAt => dateTime()();
}

/// Rows a push overwrote that had changed on the server since we last read them.
///
/// Last-write-wins still applies -- this is not a merge queue. It exists so
/// "my edit vanished" is an answerable question rather than a mystery.
class ConflictLog extends Table {
  IntColumn get id => integer().autoIncrement()();
  TextColumn get entity => text()();
  TextColumn get entityId => text()();
  TextColumn get overwritten => text()();
  DateTimeColumn get detectedAt => dateTime()();
}

/// Single row. Holds the sync cursor.
class SyncStates extends Table {
  IntColumn get id => integer().withDefault(const Constant(1))();
  IntColumn get cursor => integer().withDefault(const Constant(0))();
  DateTimeColumn get lastPullAt => dateTime().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

// --- mirrored server entities ------------------------------------------------
// Only what the UI actually renders or mutates offline. Locations, prayer times,
// schedule versions and slots are deliberately NOT mirrored: the client consumes
// the agenda those produce rather than re-deriving it, so holding the inputs
// locally would buy nothing and invite a second, divergent implementation.

mixin Synced on Table {
  TextColumn get id => text()();
  IntColumn get rowVersion => integer().nullable()();
  DateTimeColumn get deletedAt => dateTime().nullable()();

  @override
  Set<Column> get primaryKey => {id};
}

class Habits extends Table with Synced {
  TextColumn get key => text()();
  TextColumn get name => text()();
  TextColumn get icon => text().withDefault(const Constant(''))();
  TextColumn get color => text().withDefault(const Constant(''))();
  TextColumn get componentMode => text().withDefault(const Constant('NONE'))();
  BoolColumn get requiresProject =>
      boolean().withDefault(const Constant(false))();
  BoolColumn get allowsProject =>
      boolean().withDefault(const Constant(false))();
  IntColumn get sortOrder => integer().withDefault(const Constant(0))();
  DateTimeColumn get archivedAt => dateTime().nullable()();
}

class HabitComponents extends Table with Synced {
  TextColumn get habitId => text()();
  TextColumn get key => text()();
  TextColumn get label => text()();
  IntColumn get sortOrder => integer().withDefault(const Constant(0))();
  BoolColumn get isActive => boolean().withDefault(const Constant(true))();
}

class HabitLogs extends Table with Synced {
  TextColumn get habitId => text()();
  TextColumn get slotKey => text()();
  TextColumn get habitDay => text()();
  DateTimeColumn get occurredAt => dateTime()();
  TextColumn get componentId => text().nullable()();
  TextColumn get projectId => text().nullable()();
  RealColumn get value => real().nullable()();
  TextColumn get unit => text().withDefault(const Constant(''))();
  IntColumn get durationSeconds => integer().nullable()();
  TextColumn get note => text().withDefault(const Constant(''))();
  TextColumn get status => text().withDefault(const Constant('UNKNOWN'))();

  /// True until the server has echoed it back. Drives the "pending" affordance.
  BoolColumn get isPending => boolean().withDefault(const Constant(false))();
}

class Projects extends Table with Synced {
  TextColumn get name => text()();
  TextColumn get color => text().withDefault(const Constant(''))();
  TextColumn get icon => text().withDefault(const Constant(''))();
  IntColumn get sortOrder => integer().withDefault(const Constant(0))();
  DateTimeColumn get archivedAt => dateTime().nullable()();
}

class Tags extends Table with Synced {
  TextColumn get name => text()();
  TextColumn get color => text().withDefault(const Constant(''))();
}

class Tasks extends Table with Synced {
  TextColumn get projectId => text().nullable()();
  TextColumn get parentId => text().nullable()();
  TextColumn get title => text()();
  TextColumn get notes => text().withDefault(const Constant(''))();
  IntColumn get priority => integer().withDefault(const Constant(0))();
  DateTimeColumn get dueAt => dateTime().nullable()();
  TextColumn get scheduledFor => text().nullable()();
  DateTimeColumn get completedAt => dateTime().nullable()();
  TextColumn get recurrence => text().withDefault(const Constant(''))();
  IntColumn get sortOrder => integer().withDefault(const Constant(0))();
  BoolColumn get isPending => boolean().withDefault(const Constant(false))();
}

/// Server-expanded occurrences for one habit-day, cached verbatim.
///
/// Stored as the raw payload rather than shredded into columns: the client is a
/// consumer of the generator's output, and reshaping it here would be the first
/// step toward reimplementing it.
class AgendaDays extends Table {
  TextColumn get day => text()();
  TextColumn get payload => text()();
  DateTimeColumn get fetchedAt => dateTime()();

  @override
  Set<Column> get primaryKey => {day};
}

/// Small key/value store for local-only facts: the install's client id, the
/// last seen schema version, UI preferences that never sync.
class AppMeta extends Table {
  TextColumn get key => text()();
  TextColumn get value => text()();

  @override
  Set<Column> get primaryKey => {key};
}

@DriftDatabase(
  tables: [
    OutboxEntries,
    DeadLetters,
    ConflictLog,
    SyncStates,
    AppMeta,
    Habits,
    HabitComponents,
    HabitLogs,
    Projects,
    Tags,
    Tasks,
    AgendaDays,
  ],
)
class AppDatabase extends _$AppDatabase {
  AppDatabase(super.e);

  @override
  int get schemaVersion => 1;

  Future<String?> meta(String key) async {
    final row = await (select(
      appMeta,
    )..where((t) => t.key.equals(key))).getSingleOrNull();
    return row?.value;
  }

  Future<void> setMeta(String key, String value) => into(
    appMeta,
  ).insertOnConflictUpdate(AppMetaCompanion.insert(key: key, value: value));
}

/// Opens the database and reports how durable this platform actually is.
Future<(AppDatabase, PersistenceReport)> openAppDatabase() async {
  final opened = await openDatabase();
  return (AppDatabase(opened.executor), opened.report);
}
