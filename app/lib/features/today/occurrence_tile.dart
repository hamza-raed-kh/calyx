import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/theme/glass_surface.dart';
import '../../core/theme/tokens.dart';

/// One expectation on the day: a prayer, a habit, or a weekly session.
class OccurrenceTile extends ConsumerWidget {
  const OccurrenceTile({
    super.key,
    required this.occurrence,
    required this.view,
    this.flexible = false,
  });

  final Map<String, dynamic> occurrence;
  final AgendaView view;
  final bool flexible;

  Map<String, dynamic> get _habit =>
      (occurrence['habit'] as Map).cast<String, dynamic>();
  Map<String, dynamic> get _slot =>
      (occurrence['slot'] as Map).cast<String, dynamic>();

  bool get _satisfied {
    final server =
        ((occurrence['progress'] as Map?)?['satisfied'] as bool?) ?? false;
    if (server) return true;
    // A log made offline counts immediately; waiting for the server to agree
    // would make the tick feel broken on a train.
    final local = view.localLogCount(
      _habit['id'] as String,
      _slot['key'] as String,
    );
    final target = occurrence['target'] as Map?;
    if (target == null) return local > 0;
    final needed = double.tryParse(target['value'] as String? ?? '') ?? 0;
    final serverValue =
        double.tryParse(
          (occurrence['progress'] as Map?)?['value'] as String? ?? '',
        ) ??
        0;
    return serverValue +
            view.localValue(_habit['id'] as String, _slot['key'] as String) >=
        needed;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = occurrence['state'] as String? ?? 'open';
    final satisfied = _satisfied;
    final isOpen = state == 'open';
    final unavailable = state == 'unavailable';

    final tone = satisfied
        ? DarkPalette.success
        : isOpen
        ? DarkPalette.primary
        : DarkPalette.textMuted;

    return Padding(
      padding: const EdgeInsets.only(bottom: Spacing.sm),
      child: GlassSurface(
        padding: const EdgeInsets.symmetric(
          horizontal: Spacing.md,
          vertical: Spacing.sm,
        ),
        child: Row(
          children: [
            _Check(
              satisfied: satisfied,
              tone: tone,
              enabled: !unavailable,
              onTap: () => _log(ref),
            ),
            const SizedBox(width: Spacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    _title,
                    style: TextStyle(
                      fontWeight: isOpen ? FontWeight.w600 : FontWeight.w400,
                      decoration: satisfied ? TextDecoration.lineThrough : null,
                      color: satisfied
                          ? DarkPalette.textMuted
                          : DarkPalette.text,
                    ),
                  ),
                  if (_subtitle != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(
                        _subtitle!,
                        style: const TextStyle(
                          fontSize: 12,
                          color: DarkPalette.textMuted,
                        ),
                      ),
                    ),
                ],
              ),
            ),
            if (isOpen && !satisfied)
              Container(
                width: 6,
                height: 6,
                decoration: const BoxDecoration(
                  color: DarkPalette.primary,
                  shape: BoxShape.circle,
                ),
              ),
          ],
        ),
      ),
    );
  }

  String get _title {
    final habitName = _habit['name'] as String? ?? '';
    final slotLabel = _slot['label'] as String? ?? '';
    if (_habit['key'] == 'prayer' || slotLabel != habitName) {
      return slotLabel.isEmpty ? habitName : slotLabel;
    }
    return habitName;
  }

  String? get _subtitle {
    if (flexible) {
      final done = occurrence['period_target'];
      return done == null ? null : 'Target $done this week';
    }
    final start = occurrence['window_start'] as String?;
    final end = occurrence['window_end'] as String?;
    final target = occurrence['target'] as Map?;

    final parts = <String>[];
    if (start != null && end != null && _habit['key'] == 'prayer') {
      parts.add('${_clock(start)} – ${_clock(end)}');
    }
    if (target != null) {
      parts.add('${_trim(target['value'] as String? ?? '')} ${target['unit']}');
    }
    if (occurrence['state'] == 'unavailable') parts.add('unavailable');
    return parts.isEmpty ? null : parts.join(' · ');
  }

  static String _clock(String iso) {
    final local = DateTime.parse(iso).toLocal();
    return '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
  }

  static String _trim(String value) =>
      value.endsWith('.00') ? value.substring(0, value.length - 3) : value;

  Future<void> _log(WidgetRef ref) async {
    final repository = ref.read(habitRepositoryProvider);
    await repository.logOccurrence(occurrence);
    await ref.read(syncControllerProvider.notifier).refreshStatus();
  }
}

class _Check extends StatelessWidget {
  const _Check({
    required this.satisfied,
    required this.tone,
    required this.enabled,
    required this.onTap,
  });

  final bool satisfied;
  final Color tone;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      checked: satisfied,
      child: InkWell(
        onTap: enabled ? onTap : null,
        borderRadius: Radii.chipBorder,
        child: Container(
          width: 28,
          height: 28,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(
              color: satisfied ? tone : DarkPalette.border,
              width: 2,
            ),
            color: satisfied
                ? tone.withValues(alpha: 0.18)
                : Colors.transparent,
          ),
          child: satisfied ? Icon(Icons.check, size: 16, color: tone) : null,
        ),
      ),
    );
  }
}
