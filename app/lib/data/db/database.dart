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

/// Small key/value store for local-only facts: the install's client id, the
/// last seen schema version, UI preferences that never sync.
class AppMeta extends Table {
  TextColumn get key => text()();
  TextColumn get value => text()();

  @override
  Set<Column> get primaryKey => {key};
}

@DriftDatabase(
  tables: [OutboxEntries, DeadLetters, ConflictLog, SyncStates, AppMeta],
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
