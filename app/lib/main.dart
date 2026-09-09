import 'package:drift/drift.dart' show Value;
import 'package:flutter/material.dart';
import 'package:uuid/uuid.dart';

import 'core/theme/app_theme.dart';
import 'core/theme/glass_surface.dart';
import 'core/theme/tokens.dart';
import 'data/db/database.dart';
import 'data/db/persistence.dart';

void main() {
  runApp(const TasksApp());
}

class TasksApp extends StatelessWidget {
  const TasksApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Tasks',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.dark,
      home: const PersistenceSpikePage(),
    );
  }
}

/// Temporary. Proves the local database is actually durable on this platform
/// before any feature is built on top of it. Replaced by the Today screen.
class PersistenceSpikePage extends StatefulWidget {
  const PersistenceSpikePage({super.key});

  @override
  State<PersistenceSpikePage> createState() => _PersistenceSpikePageState();
}

class _PersistenceSpikePageState extends State<PersistenceSpikePage> {
  late final Future<_SpikeResult> _future = _run();

  Future<_SpikeResult> _run() async {
    final (db, report) = await openAppDatabase();

    // Survives-reload proof. Drift's own report says what it *chose*; this says
    // whether the bytes actually came back.
    final previous = int.tryParse(await db.meta('launch_count') ?? '0') ?? 0;
    final launches = previous + 1;
    await db.setMeta('launch_count', '$launches');

    final queued = await db.select(db.outboxEntries).get();
    return _SpikeResult(
      db: db,
      report: report,
      launches: launches,
      queued: queued.length,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 520),
            child: Padding(
              padding: const EdgeInsets.all(Spacing.lg),
              child: FutureBuilder<_SpikeResult>(
                future: _future,
                builder: (context, snapshot) {
                  if (snapshot.hasError) {
                    return _Message(
                      title: 'Database failed to open',
                      detail: '${snapshot.error}',
                      tone: DarkPalette.danger,
                    );
                  }
                  if (!snapshot.hasData) {
                    return const Center(child: CircularProgressIndicator());
                  }
                  return _Report(result: snapshot.data!);
                },
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _SpikeResult {
  const _SpikeResult({
    required this.db,
    required this.report,
    required this.launches,
    required this.queued,
  });

  final AppDatabase db;
  final PersistenceReport report;
  final int launches;
  final int queued;
}

class _Report extends StatefulWidget {
  const _Report({required this.result});

  final _SpikeResult result;

  @override
  State<_Report> createState() => _ReportState();
}

class _ReportState extends State<_Report> {
  late int _queued = widget.result.queued;

  Future<void> _enqueue() async {
    final db = widget.result.db;
    await db
        .into(db.outboxEntries)
        .insert(
          OutboxEntriesCompanion.insert(
            mutationId: const Uuid().v7(),
            entity: 'spike',
            op: 'upsert',
            entityId: const Uuid().v7(),
            payload: '{"probe":true}',
            clientTs: DateTime.now().toUtc(),
            baseRowVersion: const Value(null),
          ),
        );
    final rows = await db.select(db.outboxEntries).get();
    if (mounted) setState(() => _queued = rows.length);
  }

  @override
  Widget build(BuildContext context) {
    final report = widget.result.report;
    final tone = switch (report.tier) {
      PersistenceTier.durable => DarkPalette.success,
      PersistenceTier.bestEffort => DarkPalette.warning,
      PersistenceTier.ephemeral => DarkPalette.danger,
    };

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Persistence spike',
          style: Theme.of(context).textTheme.headlineSmall,
        ),
        const SizedBox(height: Spacing.lg),
        GlassSurface(
          padding: const EdgeInsets.all(Spacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                report.summary,
                style: TextStyle(color: tone, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: Spacing.md),
              _Row('Implementation', report.implementation),
              _Row('Tier', report.tier.name),
              _Row('Cross-tab safe', '${report.crossTabSafe}'),
              _Row('Storage persisted', '${report.storagePersisted ?? 'n/a'}'),
              _Row(
                'Missing features',
                report.missingFeatures.isEmpty
                    ? 'none'
                    : report.missingFeatures.join(', '),
              ),
              const Divider(height: Spacing.lg),
              _Row('Launches recorded', '${widget.result.launches}'),
              _Row('Outbox rows', '$_queued'),
            ],
          ),
        ),
        const SizedBox(height: Spacing.md),
        Text(
          widget.result.launches > 1
              ? 'Reload survived: the launch counter came back from disk.'
              : 'Reload the page. If the counter increments, storage is real.',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        const SizedBox(height: Spacing.lg),
        FilledButton(
          onPressed: report.acceptsOfflineWrites ? _enqueue : null,
          child: Text(
            report.acceptsOfflineWrites
                ? 'Queue an outbox row'
                : 'Offline writes refused',
          ),
        ),
      ],
    );
  }
}

class _Row extends StatelessWidget {
  const _Row(this.label, this.value);

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: Spacing.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 160,
            child: Text(label, style: Theme.of(context).textTheme.bodySmall),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message({
    required this.title,
    required this.detail,
    required this.tone,
  });

  final String title;
  final String detail;
  final Color tone;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: TextStyle(color: tone, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: Spacing.sm),
        Text(detail, style: Theme.of(context).textTheme.bodySmall),
      ],
    );
  }
}
