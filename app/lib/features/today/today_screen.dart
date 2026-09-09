import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/router/router.dart';
import '../../core/theme/glass_surface.dart';
import '../../core/theme/tokens.dart';
import '../../sync/sync_engine.dart';
import 'occurrence_tile.dart';

class TodayScreen extends ConsumerWidget {
  const TodayScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final agenda = ref.watch(agendaProvider);
    final sync = ref.watch(syncControllerProvider);

    return AppPage(
      title: 'Today',
      onRefresh: () => ref.read(syncControllerProvider.notifier).syncNow(),
      actions: [
        IconButton(
          onPressed: () => ref.read(syncControllerProvider.notifier).syncNow(),
          icon:
              sync.phase == SyncPhase.pulling || sync.phase == SyncPhase.pushing
              ? const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.sync),
          tooltip: 'Sync now',
        ),
      ],
      child: agenda.when(
        loading: () => const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.all(Spacing.xl),
            child: Center(child: CircularProgressIndicator()),
          ),
        ),
        error: (error, _) => SliverToBoxAdapter(
          child: _Notice(text: '$error', tone: DarkPalette.danger),
        ),
        data: (view) => view == null
            ? const SliverToBoxAdapter(child: _EmptyAgenda())
            : _Agenda(view: view, pending: sync.pendingMutations),
      ),
    );
  }
}

class _Agenda extends ConsumerWidget {
  const _Agenda({required this.view, required this.pending});

  final AgendaView view;
  final int pending;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sections = <Widget>[];

    if (view.isStale) {
      sections.add(
        const _Notice(
          text: 'Showing a cached day. Reconnect to refresh the agenda.',
          tone: DarkPalette.warning,
        ),
      );
    }
    if (pending > 0) {
      sections.add(
        _Notice(
          text: '$pending change${pending == 1 ? '' : 's'} waiting to sync.',
          tone: DarkPalette.textMuted,
        ),
      );
    }

    if (view.carryover.isNotEmpty) {
      sections
        ..add(const _SectionLabel('Still open from yesterday'))
        ..addAll(
          view.carryover.map(
            (row) => OccurrenceTile(occurrence: row, view: view),
          ),
        );
    }

    final prayers = view.occurrences.where(_isPrayer).toList();
    final rest = view.occurrences.where((row) => !_isPrayer(row)).toList();

    if (prayers.isNotEmpty) {
      sections
        ..add(const _SectionLabel('Prayers'))
        ..addAll(
          prayers.map((row) => OccurrenceTile(occurrence: row, view: view)),
        );
    }
    if (rest.isNotEmpty) {
      sections
        ..add(const _SectionLabel('Habits'))
        ..addAll(
          rest.map((row) => OccurrenceTile(occurrence: row, view: view)),
        );
    }
    if (view.flexible.isNotEmpty) {
      sections
        ..add(const _SectionLabel('This week'))
        ..addAll(
          view.flexible.map(
            (row) =>
                OccurrenceTile(occurrence: row, view: view, flexible: true),
          ),
        );
    }

    return SliverList.list(children: sections);
  }

  static bool _isPrayer(Map<String, dynamic> row) =>
      ((row['habit'] as Map)['key'] as String?) == 'prayer';
}

class _SectionLabel extends StatelessWidget {
  const _SectionLabel(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(
        top: Spacing.lg,
        bottom: Spacing.sm,
        left: Spacing.xs,
      ),
      child: Text(
        text.toUpperCase(),
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
          color: DarkPalette.textMuted,
          letterSpacing: 1.2,
        ),
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({required this.text, required this.tone});

  final String text;
  final Color tone;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: Spacing.sm),
      child: GlassSurface(
        padding: const EdgeInsets.symmetric(
          horizontal: Spacing.md,
          vertical: Spacing.sm,
        ),
        child: Row(
          children: [
            Icon(Icons.info_outline, size: 16, color: tone),
            const SizedBox(width: Spacing.sm),
            Expanded(
              child: Text(text, style: TextStyle(color: tone, fontSize: 13)),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyAgenda extends ConsumerWidget {
  const _EmptyAgenda();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: Spacing.xl),
      child: Column(
        children: [
          const Icon(Icons.cloud_off, size: 40, color: DarkPalette.textMuted),
          const SizedBox(height: Spacing.md),
          const Text('Nothing synced yet.'),
          const SizedBox(height: Spacing.sm),
          const Text(
            'Your habits and tasks live on the server.\n'
            'Sync to pull today down to this device.',
            textAlign: TextAlign.center,
            style: TextStyle(color: DarkPalette.textMuted),
          ),
          const SizedBox(height: Spacing.lg),
          FilledButton(
            onPressed: () =>
                ref.read(syncControllerProvider.notifier).syncNow(),
            child: const Text('Sync now'),
          ),
        ],
      ),
    );
  }
}
