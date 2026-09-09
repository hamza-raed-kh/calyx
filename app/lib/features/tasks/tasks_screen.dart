import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/router/router.dart';
import '../../core/theme/glass_surface.dart';
import '../../core/theme/tokens.dart';
import '../../data/db/database.dart';

class TasksScreen extends ConsumerWidget {
  const TasksScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final tasks = ref.watch(tasksProvider);

    return Stack(
      children: [
        AppPage(
          title: 'Tasks',
          onRefresh: () => ref.read(syncControllerProvider.notifier).syncNow(),
          child: tasks.when(
            loading: () => const SliverToBoxAdapter(child: SizedBox.shrink()),
            error: (error, _) => SliverToBoxAdapter(child: Text('$error')),
            data: (rows) {
              final open = rows
                  .where((task) => task.completedAt == null)
                  .toList();
              final done = rows
                  .where((task) => task.completedAt != null)
                  .toList();
              if (rows.isEmpty) {
                return const SliverToBoxAdapter(
                  child: Padding(
                    padding: EdgeInsets.symmetric(vertical: Spacing.xl),
                    child: Center(child: Text('Nothing here yet.')),
                  ),
                );
              }
              return SliverList.list(
                children: [
                  ...open.map((task) => _TaskTile(task: task)),
                  if (done.isNotEmpty) ...[
                    const Padding(
                      padding: EdgeInsets.only(
                        top: Spacing.lg,
                        bottom: Spacing.sm,
                      ),
                      child: Text(
                        'Completed',
                        style: TextStyle(color: DarkPalette.textMuted),
                      ),
                    ),
                    ...done.map((task) => _TaskTile(task: task)),
                  ],
                ],
              );
            },
          ),
        ),
        Positioned(
          right: Spacing.md,
          bottom: Spacing.md,
          child: FloatingActionButton(
            onPressed: () => _add(context, ref),
            child: const Icon(Icons.add),
          ),
        ),
      ],
    );
  }

  Future<void> _add(BuildContext context, WidgetRef ref) async {
    final controller = TextEditingController();
    final title = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (sheetContext) => Padding(
        padding: EdgeInsets.only(
          left: Spacing.md,
          right: Spacing.md,
          bottom: MediaQuery.of(sheetContext).viewInsets.bottom + Spacing.md,
          top: Spacing.md,
        ),
        child: GlassSurface(
          borderRadius: Radii.sheetBorder,
          padding: const EdgeInsets.all(Spacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: controller,
                autofocus: true,
                decoration: const InputDecoration(
                  hintText: 'What needs doing?',
                  border: InputBorder.none,
                ),
                onSubmitted: (value) => Navigator.of(sheetContext).pop(value),
              ),
              const SizedBox(height: Spacing.md),
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton(
                  onPressed: () =>
                      Navigator.of(sheetContext).pop(controller.text),
                  child: const Text('Add'),
                ),
              ),
            ],
          ),
        ),
      ),
    );

    if (title != null && title.trim().isNotEmpty) {
      await ref.read(taskRepositoryProvider).create(title: title.trim());
      await ref.read(syncControllerProvider.notifier).refreshStatus();
    }
  }
}

class _TaskTile extends ConsumerWidget {
  const _TaskTile({required this.task});

  final Task task;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final complete = task.completedAt != null;

    return Padding(
      padding: const EdgeInsets.only(bottom: Spacing.sm),
      child: GlassSurface(
        padding: const EdgeInsets.symmetric(
          horizontal: Spacing.md,
          vertical: Spacing.sm,
        ),
        child: Row(
          children: [
            Checkbox(
              value: complete,
              shape: const RoundedRectangleBorder(
                borderRadius: Radii.cardBorder,
              ),
              onChanged: (value) async {
                await ref
                    .read(taskRepositoryProvider)
                    .setComplete(task, complete: value ?? false);
                await ref.read(syncControllerProvider.notifier).refreshStatus();
              },
            ),
            Expanded(
              child: Text(
                task.title,
                style: TextStyle(
                  decoration: complete ? TextDecoration.lineThrough : null,
                  color: complete ? DarkPalette.textMuted : DarkPalette.text,
                ),
              ),
            ),
            if (task.isPending)
              const Padding(
                padding: EdgeInsets.only(left: Spacing.sm),
                child: Icon(
                  Icons.cloud_upload_outlined,
                  size: 16,
                  color: DarkPalette.textMuted,
                ),
              ),
          ],
        ),
      ),
    );
  }
}
