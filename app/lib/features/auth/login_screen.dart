import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/theme/glass_surface.dart';
import '../../core/theme/tokens.dart';
import 'auth_controller.dart';

/// Sign in, or claim a fresh instance.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _username = TextEditingController();
  final _password = TextEditingController();
  bool _creating = false;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });

    final auth = ref.read(authControllerProvider.notifier);
    final error = _creating
        ? await auth.register(
            username: _username.text.trim(),
            password: _password.text,
          )
        : await auth.signIn(
            username: _username.text.trim(),
            password: _password.text,
          );

    if (error == null) {
      // Land on a populated Today, not on an empty one with a Sync button.
      // Failure here is not a sign-in failure: they are authenticated either
      // way, and the Today screen reports sync problems itself.
      await ref.read(syncControllerProvider.notifier).syncNow();
    }

    if (!mounted) return;
    setState(() {
      _busy = false;
      _error = error;
    });
  }

  @override
  Widget build(BuildContext context) {
    final canRegister = ref.watch(registrationOpenProvider).value ?? false;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(Spacing.lg),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'calyx',
                    style: Theme.of(context).textTheme.headlineMedium,
                  ),
                  const SizedBox(height: Spacing.xs),
                  Text(
                    _creating ? 'Create your account' : 'Sign in to sync',
                    style: const TextStyle(color: DarkPalette.textMuted),
                  ),
                  const SizedBox(height: Spacing.lg),
                  GlassSurface(
                    padding: const EdgeInsets.all(Spacing.lg),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        TextField(
                          controller: _username,
                          autofillHints: const [AutofillHints.username],
                          textInputAction: TextInputAction.next,
                          decoration: const InputDecoration(
                            labelText: 'Username',
                          ),
                        ),
                        const SizedBox(height: Spacing.md),
                        TextField(
                          controller: _password,
                          obscureText: true,
                          autofillHints: const [AutofillHints.password],
                          textInputAction: TextInputAction.done,
                          onSubmitted: (_) => _busy ? null : _submit(),
                          decoration: const InputDecoration(
                            labelText: 'Password',
                          ),
                        ),
                        if (_error != null) ...[
                          const SizedBox(height: Spacing.md),
                          Text(
                            _error!,
                            style: const TextStyle(
                              color: DarkPalette.danger,
                              fontSize: 12,
                            ),
                          ),
                        ],
                        const SizedBox(height: Spacing.lg),
                        FilledButton(
                          onPressed: _busy ? null : _submit,
                          child: _busy
                              ? const SizedBox(
                                  height: 18,
                                  width: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : Text(_creating ? 'Create account' : 'Sign in'),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: Spacing.md),
                  if (canRegister || _creating)
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () => setState(() {
                              _creating = !_creating;
                              _error = null;
                            }),
                      child: Text(
                        _creating
                            ? 'I already have an account'
                            : 'Create an account',
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
