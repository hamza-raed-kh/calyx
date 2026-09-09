import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/router/router.dart';
import '../../core/theme/glass_surface.dart';
import '../../core/theme/tokens.dart';
import '../../data/db/persistence.dart';
import '../../notifications/scheduler.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final persistence = ref.watch(persistenceProvider);
    final sync = ref.watch(syncControllerProvider);
    final config = ref.watch(apiConfigProvider);
    final deadLetters = ref.watch(deadLettersProvider);

    return AppPage(
      title: 'Settings',
      child: SliverList.list(
        children: [
          _Card(
            title: 'Server',
            child: config.when(
              loading: () => const SizedBox.shrink(),
              error: (error, _) => Text('$error'),
              data: (value) => Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _Field(
                    label: 'API address',
                    value: value.baseUrl,
                    hint: 'https://tasks.your-tailnet.ts.net/api/v1',
                    onSave: (input) => _save(ref, 'api_base_url', input),
                  ),
                  const SizedBox(height: Spacing.md),
                  _Field(
                    label: 'API token',
                    value: value.token ?? '',
                    obscure: true,
                    hint: 'from manage.py drf_create_token',
                    onSave: (input) => _save(ref, 'api_token', input),
                  ),
                ],
              ),
            ),
          ),
          _Card(
            title: 'Sync',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Row('Pending changes', '${sync.pendingMutations}'),
                _Row('Dead-lettered', '${sync.deadLettered}'),
                _Row('Last synced', _ago(sync.lastSyncedAt)),
                if (sync.lastError != null)
                  _Row('Last error', sync.lastError!, tone: DarkPalette.danger),
                if (sync.clockIsSuspect)
                  const Padding(
                    padding: EdgeInsets.only(top: Spacing.sm),
                    // Skew is nearly harmless for sync -- conflicts resolve by
                    // server order -- but it makes reminders fire at the wrong
                    // time, which is what the owner would actually notice.
                    child: Text(
                      'This device’s clock is off by more than five minutes. '
                      'Reminders may fire at the wrong time.',
                      style: TextStyle(
                        color: DarkPalette.warning,
                        fontSize: 12,
                      ),
                    ),
                  ),
                const SizedBox(height: Spacing.md),
                FilledButton.icon(
                  onPressed: () =>
                      ref.read(syncControllerProvider.notifier).syncNow(),
                  icon: const Icon(Icons.sync, size: 18),
                  label: const Text('Sync now'),
                ),
              ],
            ),
          ),
          _Card(
            title: 'Reminders',
            child: ref
                .watch(reminderStatusProvider)
                .when(
                  loading: () => const SizedBox.shrink(),
                  error: (error, _) => Text('\$error'),
                  data: (reminders) => Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      _Row(
                        'Status',
                        reminders.summary,
                        tone: switch (reminders.capability) {
                          ReminderCapability.exact => DarkPalette.success,
                          ReminderCapability.inexact => DarkPalette.warning,
                          _ => DarkPalette.textMuted,
                        },
                      ),
                      if (reminders.detail.isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: Spacing.sm),
                          child: Text(
                            reminders.detail,
                            style: const TextStyle(
                              fontSize: 12,
                              color: DarkPalette.textMuted,
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
          ),
          _Card(
            title: 'Local storage',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _Row(
                  'Tier',
                  persistence.summary,
                  tone: _tone(persistence.tier),
                ),
                _Row('Implementation', persistence.implementation),
                _Row(
                  'Offline writes',
                  persistence.acceptsOfflineWrites ? 'accepted' : 'refused',
                ),
                if (persistence.missingFeatures.isNotEmpty)
                  _Row('Missing', persistence.missingFeatures.join(', ')),
              ],
            ),
          ),
          deadLetters.when(
            loading: () => const SizedBox.shrink(),
            error: (_, _) => const SizedBox.shrink(),
            data: (rows) => rows.isEmpty
                ? const SizedBox.shrink()
                : _Card(
                    title: 'Rejected changes',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'These were refused permanently and will not be retried.',
                          style: TextStyle(
                            color: DarkPalette.textMuted,
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(height: Spacing.sm),
                        ...rows
                            .take(10)
                            .map(
                              (row) => Padding(
                                padding: const EdgeInsets.only(
                                  bottom: Spacing.xs,
                                ),
                                child: Text(
                                  '${row.entity}: ${row.reason}',
                                  style: const TextStyle(fontSize: 12),
                                ),
                              ),
                            ),
                      ],
                    ),
                  ),
          ),
        ],
      ),
    );
  }

  static Color _tone(PersistenceTier tier) => switch (tier) {
    PersistenceTier.durable => DarkPalette.success,
    PersistenceTier.bestEffort => DarkPalette.warning,
    PersistenceTier.ephemeral => DarkPalette.danger,
  };

  static String _ago(DateTime? at) {
    if (at == null) return 'never';
    final delta = DateTime.now().toUtc().difference(at);
    if (delta.inMinutes < 1) return 'just now';
    if (delta.inHours < 1) return '${delta.inMinutes}m ago';
    if (delta.inDays < 1) return '${delta.inHours}h ago';
    return '${delta.inDays}d ago';
  }

  Future<void> _save(WidgetRef ref, String key, String value) async {
    await ref.read(dbProvider).setMeta(key, value.trim());
    ref.invalidate(apiConfigProvider);
  }
}

class _Card extends StatelessWidget {
  const _Card({required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: Spacing.md),
      child: GlassSurface(
        padding: const EdgeInsets.all(Spacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: Spacing.sm),
            child,
          ],
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  const _Row(this.label, this.value, {this.tone});

  final String label;
  final String value;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 130,
            child: Text(
              label,
              style: const TextStyle(
                fontSize: 12,
                color: DarkPalette.textMuted,
              ),
            ),
          ),
          Expanded(
            child: Text(value, style: TextStyle(fontSize: 13, color: tone)),
          ),
        ],
      ),
    );
  }
}

class _Field extends StatefulWidget {
  const _Field({
    required this.label,
    required this.value,
    required this.onSave,
    this.hint,
    this.obscure = false,
  });

  final String label;
  final String value;
  final String? hint;
  final bool obscure;
  final Future<void> Function(String) onSave;

  @override
  State<_Field> createState() => _FieldState();
}

class _FieldState extends State<_Field> {
  late final TextEditingController _controller = TextEditingController(
    text: widget.value,
  );

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: TextField(
            controller: _controller,
            obscureText: widget.obscure,
            decoration: InputDecoration(
              labelText: widget.label,
              hintText: widget.hint,
              isDense: true,
            ),
          ),
        ),
        const SizedBox(width: Spacing.sm),
        IconButton(
          onPressed: () => widget.onSave(_controller.text),
          icon: const Icon(Icons.check),
          tooltip: 'Save',
        ),
      ],
    );
  }
}
