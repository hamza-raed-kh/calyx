import 'dart:convert';

// Full drift import for the expression operators (& on Expression<bool>).
// Safe here: this file declares no widgets, so drift's Column/Table cannot
// clash with Flutter's.
import 'package:drift/drift.dart';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

import '../data/api/api_client.dart';
import '../data/api/runtime_config.dart';
import '../data/db/database.dart';
import '../data/db/persistence.dart';
import '../data/repositories/habit_repository.dart';
import '../data/repositories/task_repository.dart';
import '../notifications/platform_scheduler.dart';
import '../notifications/scheduler.dart';
import '../sync/outbox.dart';
import '../sync/sync_engine.dart';

/// Opened once at startup. Everything else hangs off this.
final databaseProvider = FutureProvider<(AppDatabase, PersistenceReport)>((
  ref,
) async {
  final opened = await openAppDatabase();
  ref.onDispose(() => opened.$1.close());
  return opened;
});

final dbProvider = Provider<AppDatabase>((ref) {
  return ref.watch(databaseProvider).requireValue.$1;
});

final persistenceProvider = Provider<PersistenceReport>((ref) {
  return ref.watch(databaseProvider).requireValue.$2;
});

/// Stable per install. Identifies this device to the push endpoint.
final clientIdProvider = FutureProvider<String>((ref) async {
  final db = ref.watch(dbProvider);
  final existing = await db.meta('client_id');
  if (existing != null) return existing;
  final generated = const Uuid().v7();
  await db.setMeta('client_id', generated);
  return generated;
});

/// Where the API lives, and the token to reach it.
///
/// Kept in the local database rather than compiled in: the same web build is
/// served from the API's own origin, while the Android and Linux builds have to
/// be pointed at the tailnet host by hand.
final apiConfigProvider = FutureProvider<ApiConfig>((ref) async {
  final db = ref.watch(dbProvider);
  // The address is deployment configuration, never a user setting. On web it
  // comes from the container serving the app, so one image works for any
  // hostname; elsewhere it is baked in at build time. Either way nobody is
  // asked to type a URL.
  final resolved = await runtimeApiBaseUrl();
  return ApiConfig(
    baseUrl: resolved ?? kDefaultApiBase,
    token: await db.meta('api_token'),
  );
});

final apiClientProvider = Provider<ApiClient>((ref) {
  // requireValue, not a fallback. Falling back to the compile-time default
  // while the real config resolves sends the first calls -- including the one
  // that decides whether sign-up is offered -- to the wrong host entirely.
  // The app gates on apiConfigProvider, so this is resolved before any screen
  // that uses it can build.
  return ApiClient(ref.watch(apiConfigProvider).requireValue);
});

final outboxProvider = Provider<Outbox>((ref) => Outbox(ref.watch(dbProvider)));

final habitRepositoryProvider = Provider<HabitRepository>(
  (ref) => HabitRepository(ref.watch(dbProvider), ref.watch(outboxProvider)),
);

final taskRepositoryProvider = Provider<TaskRepository>(
  (ref) => TaskRepository(ref.watch(dbProvider), ref.watch(outboxProvider)),
);

final schedulerProvider = Provider<NotificationScheduler>(
  (ref) => createScheduler(),
);

final reminderStatusProvider = FutureProvider<ReminderStatus>(
  (ref) => ref.watch(schedulerProvider).status(),
);

final syncEngineProvider = Provider<SyncEngine>((ref) {
  return SyncEngine(
    ref.watch(dbProvider),
    ref.watch(apiClientProvider),
    ref.watch(clientIdProvider).value ?? 'unconfigured',
  );
});

/// Drives the sync indicator and the manual "sync now" action.
class SyncController extends Notifier<SyncStatus> {
  @override
  SyncStatus build() => const SyncStatus();

  Future<void> refreshStatus() async {
    state = await ref.read(syncEngineProvider).status();
  }

  Future<void> syncNow() async {
    state = state.copyWith(phase: SyncPhase.pulling);
    final engine = ref.read(syncEngineProvider);
    final result = await engine.sync();
    // Refresh the cached agenda only after a successful sync: replacing it from
    // a half-finished pull would show a day built from stale habits.
    if (result.phase != SyncPhase.failed) {
      await engine.refreshHorizon();
      await _rescheduleReminders();
    }
    state = result;
  }

  /// Rebuild the alarm window from the freshly cached agenda.
  ///
  /// Cancel-and-reschedule over a rolling seven days rather than diffing: a
  /// settings change then takes effect within a day, and moving cities does not
  /// leave weeks of wrong alarms pinned to the system.
  Future<void> _rescheduleReminders() async {
    final db = ref.read(dbProvider);
    final days = await db.select(db.agendaDays).get();
    final scheduler = ref.read(schedulerProvider);
    await scheduler.initialise();
    await scheduler.reschedule(remindersFrom(days));
    ref.invalidate(reminderStatusProvider);
  }
}

final syncControllerProvider = NotifierProvider<SyncController, SyncStatus>(
  SyncController.new,
);

// --- domain streams ----------------------------------------------------------
// The UI reads from drift, never from the network. The sync engine writes into
// drift and the UI recomposes. The classic failure is letting a screen or two
// call the API directly "just for now"; that is what breaks offline.

final habitsProvider = StreamProvider<List<Habit>>((ref) {
  final db = ref.watch(dbProvider);
  return (db.select(db.habits)
        ..where((t) => t.deletedAt.isNull() & t.archivedAt.isNull())
        ..orderBy([(t) => OrderingTerm.asc(t.sortOrder)]))
      .watch();
});

final projectsProvider = StreamProvider<List<Project>>((ref) {
  final db = ref.watch(dbProvider);
  return (db.select(db.projects)
        ..where((t) => t.deletedAt.isNull() & t.archivedAt.isNull())
        ..orderBy([(t) => OrderingTerm.asc(t.sortOrder)]))
      .watch();
});

final tasksProvider = StreamProvider<List<Task>>((ref) {
  final db = ref.watch(dbProvider);
  return (db.select(db.tasks)
        ..where((t) => t.deletedAt.isNull())
        ..orderBy([
          (t) => OrderingTerm.asc(t.completedAt),
          (t) => OrderingTerm.desc(t.priority),
          (t) => OrderingTerm.asc(t.dueAt),
        ]))
      .watch();
});

final deadLettersProvider = StreamProvider<List<DeadLetter>>((ref) {
  final db = ref.watch(dbProvider);
  return db.select(db.deadLetters).watch();
});

/// Today's cached agenda, with local logs overlaid.
///
/// The agenda comes from the server fully expanded; the client never re-derives
/// windows. Local logs are overlaid so a habit ticked offline looks ticked
/// immediately rather than waiting for a round trip.
final agendaProvider = StreamProvider<AgendaView?>((ref) {
  final db = ref.watch(dbProvider);
  final today = AgendaView.todayKey();

  return (db.select(
    db.agendaDays,
  )..where((t) => t.day.equals(today))).watch().asyncMap((rows) async {
    if (rows.isEmpty) return null;
    final payload = jsonDecode(rows.first.payload) as Map<String, dynamic>;
    final logs = await (db.select(
      db.habitLogs,
    )..where((t) => t.habitDay.equals(today) & t.deletedAt.isNull())).get();
    return AgendaView(payload, logs, rows.first.fetchedAt);
  });
});

class AgendaView {
  AgendaView(this.payload, this.localLogs, this.fetchedAt);

  final Map<String, dynamic> payload;
  final List<HabitLog> localLogs;
  final DateTime fetchedAt;

  static String todayKey() {
    final now = DateTime.now();
    // The habit-day rolls at 03:00, so before then "today" is still yesterday.
    final effective = now.hour < 3
        ? now.subtract(const Duration(days: 1))
        : now;
    return '${effective.year.toString().padLeft(4, '0')}-'
        '${effective.month.toString().padLeft(2, '0')}-'
        '${effective.day.toString().padLeft(2, '0')}';
  }

  String get habitDay => payload['habit_day'] as String? ?? todayKey();

  List<Map<String, dynamic>> get occurrences =>
      ((payload['occurrences'] as List?) ?? const [])
          .cast<Map<String, dynamic>>();

  List<Map<String, dynamic>> get carryover =>
      ((payload['carryover'] as List?) ?? const [])
          .cast<Map<String, dynamic>>();

  List<Map<String, dynamic>> get flexible =>
      ((payload['flexible'] as List?) ?? const []).cast<Map<String, dynamic>>();

  bool get isStale =>
      DateTime.now().toUtc().difference(fetchedAt) > const Duration(hours: 12);

  /// Local logs count toward satisfaction as soon as they are written, so an
  /// offline tick is visible before it has been anywhere near the server.
  int localLogCount(String habitId, String slotKey) => localLogs
      .where((log) => log.habitId == habitId && log.slotKey == slotKey)
      .length;

  double localValue(String habitId, String slotKey) => localLogs
      .where((log) => log.habitId == habitId && log.slotKey == slotKey)
      .fold(0, (total, log) => total + (log.value ?? 0));
}
