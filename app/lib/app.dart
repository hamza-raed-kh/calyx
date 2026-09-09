import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/providers.dart';
import 'core/router/router.dart';
import 'core/theme/app_theme.dart';
import 'core/theme/tokens.dart';

class TasksApp extends ConsumerWidget {
  const TasksApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final database = ref.watch(databaseProvider);

    return MaterialApp.router(
      title: 'Tasks',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.dark,
      routerConfig: appRouter,
      builder: (context, child) {
        return database.when(
          loading: () => const _Splash(),
          error: (error, _) => _Fatal(error: '$error'),
          data: (_) => child ?? const SizedBox.shrink(),
        );
      },
    );
  }
}

class _Splash extends StatelessWidget {
  const _Splash();

  @override
  Widget build(BuildContext context) => const ColoredBox(
    color: DarkPalette.background,
    child: Center(child: CircularProgressIndicator()),
  );
}

class _Fatal extends StatelessWidget {
  const _Fatal({required this.error});

  final String error;

  @override
  Widget build(BuildContext context) {
    return ColoredBox(
      color: DarkPalette.background,
      child: Center(
        child: Padding(
          padding: const EdgeInsets.all(Spacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.storage, color: DarkPalette.danger, size: 40),
              const SizedBox(height: Spacing.md),
              const Text('The local database could not be opened.'),
              const SizedBox(height: Spacing.sm),
              Text(
                error,
                textAlign: TextAlign.center,
                style: const TextStyle(color: DarkPalette.textMuted),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
