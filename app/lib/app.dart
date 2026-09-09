import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/providers.dart';
import 'core/router/router.dart';
import 'core/theme/app_theme.dart';
import 'core/theme/tokens.dart';
import 'features/auth/auth_controller.dart';
import 'features/auth/login_screen.dart';

class TasksApp extends ConsumerWidget {
  const TasksApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final database = ref.watch(databaseProvider);
    // The API address is resolved from deployment config before anything can
    // call the API, so no request is ever aimed at a placeholder host.
    final apiConfig = ref.watch(apiConfigProvider);

    return MaterialApp.router(
      title: 'calyx',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: ThemeMode.dark,
      routerConfig: appRouter,
      builder: (context, child) {
        return database.when(
          loading: () => const _Splash(),
          error: (error, _) => _Fatal(error: '\$error'),
          // Sign-in gates the app because every screen is a view of synced
          // data: without an account there is nothing to show.
          data: (_) => apiConfig.isLoading
              ? const _Splash()
              : !(apiConfig.value?.isUsable ?? false)
              ? const _Unconfigured()
              : ref
                    .watch(authControllerProvider)
                    .when(
                      loading: () => const _Splash(),
                      error: (error, _) => _Fatal(error: '\$error'),
                      data: (auth) => auth.isSignedIn
                          ? (child ?? const SizedBox.shrink())
                          : const LoginScreen(),
                    ),
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
              const Text('Local storage is unavailable.'),
              const SizedBox(height: Spacing.sm),
              const Text(
                'Private browsing, or blocked site data, will do this. '
                'Try a normal window and allow this site to store data.',
                textAlign: TextAlign.center,
                style: TextStyle(color: DarkPalette.textMuted, fontSize: 12),
              ),
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

/// Shown when the build has no usable server address.
///
/// Only reachable off the web, and only when API_BASE_URL was not supplied at
/// build time. Saying so plainly beats a crash or an app that silently reaches
/// nothing.
class _Unconfigured extends StatelessWidget {
  const _Unconfigured();

  @override
  Widget build(BuildContext context) {
    return const ColoredBox(
      color: DarkPalette.background,
      child: Center(
        child: Padding(
          padding: EdgeInsets.all(Spacing.lg),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.settings_ethernet,
                color: DarkPalette.warning,
                size: 40,
              ),
              SizedBox(height: Spacing.md),
              Text('No server configured in this build.'),
              SizedBox(height: Spacing.sm),
              Text(
                'This copy of calyx was built without API_BASE_URL, so it does '
                'not know where its server is. Rebuild the release with it set.',
                textAlign: TextAlign.center,
                style: TextStyle(color: DarkPalette.textMuted, fontSize: 12),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
