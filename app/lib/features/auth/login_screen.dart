import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
  late final TextEditingController _server = TextEditingController(
    text: ref.read(authControllerProvider).value?.serverAddress ?? '',
  );

  bool _creating = false;
  bool _busy = false;
  bool _showServer = false;
  String? _error;

  @override
  void dispose() {
    _username.dispose();
    _password.dispose();
    _server.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
    });

    final auth = ref.read(authControllerProvider.notifier);
    if (_server.text.trim().isNotEmpty) {
      await auth.setServerAddress(_server.text);
    }

    final error = _creating
        ? await auth.register(
            username: _username.text.trim(),
            password: _password.text,
          )
        : await auth.signIn(
            username: _username.text.trim(),
            password: _password.text,
          );

    if (!mounted) return;
    setState(() {
      _busy = false;
      _error = error;
      // Reveal the server field when the failure is plausibly the address,
      // rather than making them hunt for it.
      if (error != null &&
          (error.contains('reach') || error.contains('address'))) {
        _showServer = true;
      }
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
                        if (_showServer) ...[
                          const SizedBox(height: Spacing.md),
                          TextField(
                            controller: _server,
                            keyboardType: TextInputType.url,
                            decoration: const InputDecoration(
                              labelText: 'Server address',
                              hintText: 'https://calyx.example.ts.net/api/v1',
                            ),
                          ),
                        ],
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
                  TextButton(
                    onPressed: () => setState(() => _showServer = !_showServer),
                    child: Text(
                      _showServer
                          ? 'Hide server address'
                          : 'Change server address',
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
        ),
      ),
    );
  }
}
