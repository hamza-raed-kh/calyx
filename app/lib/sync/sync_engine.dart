import 'dart:convert';
import 'dart:math';

import 'package:drift/drift.dart';

import '../data/api/api_client.dart';
import '../data/db/database.dart';
import 'outbox.dart';
import 'reconciler.dart';

enum SyncPhase { idle, pulling, pushing, offline, failed }

class SyncStatus {
  const SyncStatus({
    this.phase = SyncPhase.idle,
    this.pendingMutations = 0,
    this.deadLettered = 0,
    this.lastSyncedAt,
    this.lastError,
    this.clockSkew,
  });

  final SyncPhase phase;
  final int pendingMutations;
  final int deadLettered;
  final DateTime? lastSyncedAt;
  final String? lastError;
  final Duration? clockSkew;

  /// Skew matters far more for notification timing than for sync correctness --
  /// conflicts are resolved by server arrival order, not by any clock.
  bool get clockIsSuspect =>
      clockSkew != null && clockSkew!.abs() > const Duration(minutes: 5);

  SyncStatus copyWith({
    SyncPhase? phase,
    int? pendingMutations,
    int? deadLettered,
    DateTime? lastSyncedAt,
    String? lastError,
    Duration? clockSkew,
  }) {
    return SyncStatus(
      phase: phase ?? this.phase,
      pendingMutations: pendingMutations ?? this.pendingMutations,
      deadLettered: deadLettered ?? this.deadLettered,
      lastSyncedAt: lastSyncedAt ?? this.lastSyncedAt,
      lastError: lastError,
      clockSkew: clockSkew ?? this.clockSkew,
    );
  }
}

class SyncEngine {
  // Positional: Dart forbids private named parameters, so an initializing
  // formal is only available this way.
  SyncEngine(this._db, this._api, this._clientId);

  final AppDatabase _db;
  final ApiClient _api;
  final String _clientId;

  late final Outbox _outbox = Outbox(_db);
  late final Reconciler _reconciler = Reconciler(_db);

  /// Habit logs travel as intents, not as rows.
  ///
  /// Pushing a habit_log through the generic endpoint would bypass the server's
  /// adjudication of on-time versus late and let the device decide it -- which
  /// is exactly the judgment the server is supposed to own. The intent carries
  /// an occurrence id and a client-generated log id; the server re-derives the
  /// window and freezes the verdict, and the log id makes redelivery free.
  static const habitLogIntent = 'habit_log_intent';

  static const _pageLimit = 200;
  static const _batchLimit = 200;
  static const _maxAttempts = 8;

  bool _running = false;

  /// Pull, then push, then pull again.
  ///
  /// Pull first because deciding what a local change means requires knowing
  /// current server state. Pull last because the cursor only ever advances on a
  /// pull: taking it from a push response would skip anything another writer
  /// committed between this client's last pull and its push.
  Future<SyncStatus> sync() async {
    if (_running) return status();
    _running = true;
    try {
      await _pullAll();
      await _drainOutbox();
      await _pullAll();
      await _setState(lastPullAt: DateTime.now().toUtc());
      return (await status()).copyWith(
        phase: SyncPhase.idle,
        lastSyncedAt: DateTime.now().toUtc(),
      );
    } on Object catch (error) {
      return (await status()).copyWith(
        phase: SyncPhase.failed,
        lastError: error.toString(),
      );
    } finally {
      _running = false;
    }
  }

  Future<void> _pullAll() async {
    var guard = 0;
    while (guard++ < 500) {
      final cursor = await _cursor();
      final response = await _api.get(
        '/sync/pull/',
        query: {'cursor': cursor, 'limit': _pageLimit},
      );
      if (!response.ok) {
        throw ApiException('pull failed: HTTP ${response.status}');
      }

      final body = response.json;
      await _reconciler.apply(
        (body['changes'] as Map?)?.cast<String, dynamic>() ?? {},
      );
      await _setState(cursor: body['cursor'] as int? ?? cursor);
      _recordSkew(body['server_time'] as String?);

      if (body['has_more'] != true) return;
    }
  }

  Future<void> _drainOutbox() async {
    await _drainIntents();

    var guard = 0;
    while (guard++ < 50) {
      final pending = (await _outbox.pending(
        limit: _batchLimit,
      )).where((entry) => entry.entity != habitLogIntent).toList();
      if (pending.isEmpty) return;

      final response = await _api.post('/sync/push/', {
        'client_id': _clientId,
        'mutations': [
          for (final entry in pending)
            {
              'mutation_id': entry.mutationId,
              'seq': entry.seq,
              'entity': entry.entity,
              'op': entry.op,
              'id': entry.entityId,
              'client_ts': entry.clientTs.toIso8601String(),
              if (entry.baseRowVersion != null)
                'base_row_version': entry.baseRowVersion,
              'payload': jsonDecode(entry.payload),
            },
        ],
      });

      if (!response.ok) {
        if (response.isTransient) {
          // Leave the outbox untouched and back off. mutation_id makes the
          // retry free, so the safe move is always to try again later.
          for (final entry in pending) {
            await _outbox.recordAttempt(entry.seq, 'HTTP ${response.status}');
          }
          throw ApiException('push failed: HTTP ${response.status}');
        }
        // A permanently malformed batch: dead-letter it rather than jam.
        for (final entry in pending) {
          await _outbox.deadLetter(entry, 'HTTP ${response.status}');
        }
        return;
      }

      final results = (response.json['results'] as List?) ?? const [];
      final bySeq = {for (final entry in pending) entry.mutationId: entry};
      final done = <int>[];

      for (final raw in results) {
        final result = (raw as Map).cast<String, dynamic>();
        final entry = bySeq[result['mutation_id']];
        if (entry == null) continue;

        final status = result['status'] as String?;
        if (status == 'rejected') {
          await _outbox.deadLetter(
            entry,
            '${result['reason']}: ${result['detail']}',
          );
          continue;
        }
        if (status == 'conflict' && result['overwritten'] != null) {
          await _reconciler.recordConflict(
            entry.entity,
            entry.entityId,
            jsonEncode(result['overwritten']),
          );
        }
        // Write the echoed canonical row so the UI settles on server values
        // without waiting for -- or flickering through -- the next pull.
        final row = result['row'];
        if (row is Map<String, dynamic>) {
          await _reconciler.apply({
            entry.entity: [row],
          });
        }
        done.add(entry.seq);
      }

      await _outbox.drop(done);

      final stuck = pending.where((entry) => !done.contains(entry.seq));
      for (final entry in stuck) {
        if (entry.attempts + 1 >= _maxAttempts) {
          await _outbox.deadLetter(
            entry,
            'gave up after $_maxAttempts attempts',
          );
        } else {
          await _outbox.recordAttempt(entry.seq, 'no result returned');
        }
      }
      if (done.isEmpty) return;
    }
  }

  /// Post queued habit logs one at a time, letting the server adjudicate each.
  Future<void> _drainIntents() async {
    final intents = (await _outbox.pending(
      limit: _batchLimit,
    )).where((entry) => entry.entity == habitLogIntent).toList();

    for (final entry in intents) {
      final body = (jsonDecode(entry.payload) as Map).cast<String, dynamic>();
      final response = await _api.post('/habits/logs/', {
        ...body,
        'id': entry.entityId,
      });

      if (response.ok) {
        await _reconciler.apply({
          'habit_logs': [response.json],
        });
        await _outbox.drop([entry.seq]);
        continue;
      }
      if (response.isTransient) {
        await _outbox.recordAttempt(entry.seq, 'HTTP ${response.status}');
        throw ApiException('log push failed: HTTP ${response.status}');
      }
      // 4xx: the server will never accept this. Retrying forever would jam the
      // queue behind it.
      await _outbox.deadLetter(
        entry,
        'HTTP ${response.status}: ${jsonEncode(response.data)}',
      );
    }
  }

  /// Cache expanded occurrences so the agenda renders offline.
  Future<int> refreshHorizon({int days = 35}) async {
    final response = await _api.get('/agenda/horizon/', query: {'days': days});
    if (!response.ok) return 0;

    final payload = (response.json['days'] as List?) ?? const [];
    await _db.transaction(() async {
      for (final raw in payload) {
        final day = (raw as Map).cast<String, dynamic>();
        await _db
            .into(_db.agendaDays)
            .insertOnConflictUpdate(
              AgendaDaysCompanion.insert(
                day: day['habit_day'] as String,
                payload: jsonEncode(day),
                fetchedAt: DateTime.now().toUtc(),
              ),
            );
      }
    });
    return payload.length;
  }

  Future<SyncStatus> status() async {
    final state = await _state();
    return SyncStatus(
      pendingMutations: await _outbox.count(),
      deadLettered: (await _outbox.deadLetters()).length,
      lastSyncedAt: state?.lastPullAt,
      clockSkew: _skew,
    );
  }

  // --- sync state ---------------------------------------------------------

  Future<SyncState?> _state() => (_db.select(
    _db.syncStates,
  )..where((t) => t.id.equals(1))).getSingleOrNull();

  Future<int> _cursor() async => (await _state())?.cursor ?? 0;

  Future<void> _setState({int? cursor, DateTime? lastPullAt}) async {
    await _db
        .into(_db.syncStates)
        .insertOnConflictUpdate(
          SyncStatesCompanion(
            id: const Value(1),
            cursor: cursor == null ? const Value.absent() : Value(cursor),
            lastPullAt: lastPullAt == null
                ? const Value.absent()
                : Value(lastPullAt),
          ),
        );
  }

  Duration? _skew;

  void _recordSkew(String? serverTime) {
    if (serverTime == null) return;
    final server = DateTime.tryParse(serverTime);
    if (server == null) return;
    _skew = DateTime.now().toUtc().difference(server.toUtc());
  }
}

/// Exponential backoff with jitter, capped. Used by the caller's retry loop.
Duration backoffFor(int attempt, {Random? random}) {
  final rng = random ?? Random();
  final base = min(pow(2, attempt).toInt(), 300);
  return Duration(seconds: base, milliseconds: rng.nextInt(1000));
}
