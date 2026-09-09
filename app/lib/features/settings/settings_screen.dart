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
                    hint: 'https://calyx.example.ts.net/api/v1',
                    onSave: (input) => _save(ref, 'api_base_url', input),
                  ),
                  const _Explainer(
                    'The full URL ending in /api/v1. The default only works '
                    'when this page is served from the same host as the API.',
                  ),
                  const SizedBox(height: Spacing.md),
                  _Field(
                    label: 'API token',
                    value: value.token ?? '',
                    obscure: true,
                    hint: 'a long random string',
                    onSave: (input) => _save(ref, 'api_token', input),
                  ),
                  const _Explainer(
                    'Generate one on the server:\n'
                    'make superuser        (once)\n'
                    'make token USER=<you>',
                  ),
                  const SizedBox(height: Spacing.md),
                  const _ConnectionTest(),
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

/// Short grey note under a field. Setup is the one moment the app cannot
/// assume the reader already knows what it wants from them.
class _Explainer extends StatelessWidget {
  const _Explainer(this.text);

  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: Spacing.xs),
      child: Text(
        text,
        style: const TextStyle(
          fontSize: 11,
          color: DarkPalette.textMuted,
          height: 1.4,
        ),
      ),
    );
  }
}

/// Says whether the address and token actually work, and why not when they do
/// not. Without it a misconfiguration is indistinguishable from an empty
/// database: both look like a blank Today screen.
class _ConnectionTest extends ConsumerStatefulWidget {
  const _ConnectionTest();

  @override
  ConsumerState<_ConnectionTest> createState() => _ConnectionTestState();
}

class _ConnectionTestState extends ConsumerState<_ConnectionTest> {
  String? _result;
  Color _tone = DarkPalette.textMuted;
  bool _busy = false;

  Future<void> _run() async {
    setState(() {
      _busy = true;
      _result = null;
    });

    final api = ref.read(apiClientProvider);
    String message;
    Color tone;
    try {
      final health = await api.get('/health/');
      if (health.status == 0) {
        message =
            'Could not reach the server. Check the address, and that it '
            'is HTTPS and resolvable from this device.';
        tone = DarkPalette.danger;
      } else if (health.status == 404) {
        message =
            'Reached a server, but no API there. Does the address end in /api/v1?';
        tone = DarkPalette.danger;
      } else if (!health.ok) {
        message = 'Server answered HTTP ${health.status}.';
        tone = DarkPalette.danger;
      } else {
        // Health is deliberately unauthenticated, so a second, authenticated
        // call is the only thing that actually proves the token.
        final pull = await api.get(
          '/sync/pull/',
          query: {'cursor': 0, 'limit': 1},
        );
        if (pull.status == 401 || pull.status == 403) {
          message = 'Server reachable, but the token was rejected.';
          tone = DarkPalette.danger;
        } else if (!pull.ok) {
          message = 'Server reachable; sync returned HTTP ${pull.status}.';
          tone = DarkPalette.warning;
        } else {
          message = 'Connected and authenticated.';
          tone = DarkPalette.success;
        }
      }
    } on Object catch (error) {
      message = 'Failed: $error';
      tone = DarkPalette.danger;
    }

    if (!mounted) return;
    setState(() {
      _busy = false;
      _result = message;
      _tone = tone;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        OutlinedButton.icon(
          onPressed: _busy ? null : _run,
          icon: _busy
              ? const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.network_check, size: 18),
          label: const Text('Test connection'),
        ),
        if (_result != null)
          Padding(
            padding: const EdgeInsets.only(top: Spacing.sm),
            child: Text(_result!, style: TextStyle(fontSize: 12, color: _tone)),
          ),
      ],
    );
  }
}
