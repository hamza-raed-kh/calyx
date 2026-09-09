import 'dart:convert';

import 'package:drift/drift.dart';
import 'package:uuid/uuid.dart';

import '../data/db/database.dart';

/// The durable queue of local changes awaiting push.
class Outbox {
  Outbox(this._db);

  final AppDatabase _db;
  static const _uuid = Uuid();

  Future<int> enqueue({
    required String entity,
    required String op,
    required String entityId,
    required Map<String, Object?> payload,
    int? baseRowVersion,
  }) {
    return _db
        .into(_db.outboxEntries)
        .insert(
          OutboxEntriesCompanion.insert(
            mutationId: _uuid.v7(),
            entity: entity,
            op: op,
            entityId: entityId,
            payload: jsonEncode(payload),
            clientTs: DateTime.now().toUtc(),
            baseRowVersion: Value(baseRowVersion),
          ),
        );
  }

  Future<List<OutboxEntry>> pending({int limit = 200}) {
    return (_db.select(_db.outboxEntries)
          ..orderBy([(t) => OrderingTerm.asc(t.seq)])
          ..limit(limit))
        .get();
  }

  Future<int> count() async =>
      (await _db.select(_db.outboxEntries).get()).length;

  Future<void> drop(Iterable<int> seqs) async {
    if (seqs.isEmpty) return;
    await (_db.delete(_db.outboxEntries)..where((t) => t.seq.isIn(seqs))).go();
  }

  Future<void> recordAttempt(int seq, String error) async {
    final row = await (_db.select(
      _db.outboxEntries,
    )..where((t) => t.seq.equals(seq))).getSingleOrNull();
    if (row == null) return;
    await (_db.update(
      _db.outboxEntries,
    )..where((t) => t.seq.equals(seq))).write(
      OutboxEntriesCompanion(
        attempts: Value(row.attempts + 1),
        lastError: Value(error),
      ),
    );
  }

  /// Move a permanently-rejected mutation aside.
  ///
  /// This path exists from day one on purpose. A poison mutation that retries
  /// forever is the likeliest way an offline sync engine breaks, and without
  /// somewhere to put the casualty the failure is invisible: the queue simply
  /// stops draining and nothing says why.
  Future<void> deadLetter(OutboxEntry entry, String reason) async {
    await _db.transaction(() async {
      await _db
          .into(_db.deadLetters)
          .insert(
            DeadLettersCompanion.insert(
              mutationId: entry.mutationId,
              entity: entry.entity,
              payload: entry.payload,
              reason: reason,
              rejectedAt: DateTime.now().toUtc(),
            ),
          );
      await (_db.delete(
        _db.outboxEntries,
      )..where((t) => t.seq.equals(entry.seq))).go();
    });
  }

  Future<List<DeadLetter>> deadLetters() => _db.select(_db.deadLetters).get();

  Future<void> clearDeadLetters() => _db.delete(_db.deadLetters).go();
}
