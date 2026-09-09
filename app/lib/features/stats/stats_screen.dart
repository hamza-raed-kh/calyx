import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/router/router.dart';
import '../../core/theme/glass_surface.dart';
import '../../core/theme/tokens.dart';

/// Rates over trailing windows. No streaks anywhere, by design.
final ratesProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final response = await ref
      .watch(apiClientProvider)
      .get('/stats/rates/', query: {'windows': '7,30,90'});
  if (!response.ok) return const [];
  return ((response.json['habits'] as List?) ?? const [])
      .cast<Map<String, dynamic>>();
});

class StatsScreen extends ConsumerWidget {
  const StatsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rates = ref.watch(ratesProvider);

    return AppPage(
      title: 'Stats',
      onRefresh: () async => ref.invalidate(ratesProvider),
      child: rates.when(
        loading: () => const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.all(Spacing.xl),
            child: Center(child: CircularProgressIndicator()),
          ),
        ),
        error: (error, _) => SliverToBoxAdapter(
          child: Text(
            'Stats need a connection.\n$error',
            style: const TextStyle(color: DarkPalette.textMuted),
          ),
        ),
        data: (habits) => habits.isEmpty
            ? const SliverToBoxAdapter(
                child: Padding(
                  padding: EdgeInsets.symmetric(vertical: Spacing.xl),
                  child: Center(child: Text('No statistics yet.')),
                ),
              )
            : SliverList.list(children: habits.map(_HabitStats.new).toList()),
      ),
    );
  }
}

class _HabitStats extends StatelessWidget {
  const _HabitStats(this.entry);

  final Map<String, dynamic> entry;

  @override
  Widget build(BuildContext context) {
    final windows = (entry['windows'] as Map).cast<String, dynamic>();

    return Padding(
      padding: const EdgeInsets.only(bottom: Spacing.sm),
      child: GlassSurface(
        padding: const EdgeInsets.all(Spacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              entry['habit_name'] as String? ?? '',
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: Spacing.sm),
            Row(
              children: [
                for (final days in ['7', '30', '90'])
                  Expanded(
                    child: _Window(
                      days: days,
                      stats: windows[days] as Map<String, dynamic>?,
                    ),
                  ),
              ],
            ),
            ..._slots(windows['30'] as Map<String, dynamic>?),
          ],
        ),
      ),
    );
  }

  List<Widget> _slots(Map<String, dynamic>? stats) {
    final slots = ((stats?['by_slot'] as List?) ?? const [])
        .cast<Map<String, dynamic>>();
    if (slots.length < 2) return const [];
    return [
      const Divider(height: Spacing.lg),
      for (final slot in slots)
        Padding(
          padding: const EdgeInsets.only(bottom: 2),
          child: Row(
            children: [
              SizedBox(
                width: 90,
                child: Text(
                  slot['label'] as String? ?? '',
                  style: const TextStyle(
                    fontSize: 12,
                    color: DarkPalette.textMuted,
                  ),
                ),
              ),
              Expanded(
                child: LinearProgressIndicator(
                  value: (slot['rate'] as num?)?.toDouble() ?? 0,
                  minHeight: 6,
                  borderRadius: Radii.chipBorder,
                  backgroundColor: DarkPalette.surface,
                ),
              ),
              const SizedBox(width: Spacing.sm),
              Text(
                '${slot['satisfied']}/${slot['expected']}',
                style: const TextStyle(
                  fontSize: 11,
                  color: DarkPalette.textMuted,
                ),
              ),
            ],
          ),
        ),
    ];
  }
}

class _Window extends StatelessWidget {
  const _Window({required this.days, required this.stats});

  final String days;
  final Map<String, dynamic>? stats;

  @override
  Widget build(BuildContext context) {
    final rate =
        (stats?['slot_rate'] as num?)?.toDouble() ??
        (stats?['period_rate'] as num?)?.toDouble();
    final eligible = stats?['eligible_days'] as int? ?? 0;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${days}d',
          style: const TextStyle(fontSize: 11, color: DarkPalette.textMuted),
        ),
        Text(
          rate == null ? '—' : '${(rate * 100).round()}%',
          style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
        ),
        // Always shown: 83% of 12 days is a different claim from 83% of 90.
        Text(
          'of $eligible days',
          style: const TextStyle(fontSize: 10, color: DarkPalette.textMuted),
        ),
      ],
    );
  }
}
