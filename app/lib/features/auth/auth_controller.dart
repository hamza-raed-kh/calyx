import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

class AuthState {
  const AuthState({this.token, this.user});

  final String? token;
  final Map<String, dynamic>? user;

  bool get isSignedIn => token != null && token!.isNotEmpty;
  String get username => user?['username'] as String? ?? '';
}

/// Sign-in state, persisted locally so it survives a restart.
///
/// The token is a credential, not configuration. The app asks for a username
/// and password like anything else; minting a token by hand on the server is
/// internal plumbing and has no business in the product.
class AuthController extends AsyncNotifier<AuthState> {
  @override
  Future<AuthState> build() async {
    final db = ref.watch(dbProvider);
    final raw = await db.meta('auth_user');
    return AuthState(
      token: await db.meta('api_token'),
      user: raw == null ? null : jsonDecode(raw) as Map<String, dynamic>,
    );
  }

  Future<String?> signIn({
    required String username,
    required String password,
  }) => _authenticate('/auth/login/', {
    'username': username,
    'password': password,
  });

  Future<String?> register({
    required String username,
    required String password,
    String email = '',
  }) => _authenticate('/auth/register/', {
    'username': username,
    'password': password,
    'email': email,
  });

  /// Returns null on success, or a message fit to show the user.
  Future<String?> _authenticate(String path, Map<String, Object?> body) async {
    final api = ref.read(apiClientProvider);
    try {
      final response = await api.post(path, body);

      if (response.status == 0) {
        return 'Could not reach the server. It may be down, or off this '
            "device's network.";
      }
      if (response.status == 404) {
        return 'Reached something, but not the API. The deployment is '
            'misconfigured.';
      }
      if (!response.ok) {
        return _describe(response.json) ??
            'Sign-in failed (HTTP ${response.status}).';
      }

      final db = ref.read(dbProvider);
      await db.setMeta('api_token', response.json['token'] as String);
      await db.setMeta('auth_user', jsonEncode(response.json['user']));
      ref.invalidate(apiConfigProvider);
      ref.invalidateSelf();
      return null;
    } on Object catch (error) {
      return 'Failed: $error';
    }
  }

  Future<void> signOut() async {
    // Revoke server-side first: a token merely forgotten locally is still a
    // working credential on a device you no longer have.
    try {
      await ref.read(apiClientProvider).post('/auth/logout/', const {});
    } on Object {
      // Offline sign-out still has to clear this device.
    }
    final db = ref.read(dbProvider);
    await db.setMeta('api_token', '');
    await db.setMeta('auth_user', '');
    ref.invalidate(apiConfigProvider);
    ref.invalidateSelf();
  }

  static String? _describe(Map<String, dynamic> body) {
    if (body['detail'] is String) return body['detail'] as String;
    for (final value in body.values) {
      if (value is List && value.isNotEmpty) return '${value.first}';
      if (value is String) return value;
    }
    return null;
  }
}

final authControllerProvider = AsyncNotifierProvider<AuthController, AuthState>(
  AuthController.new,
);

/// Whether this instance will currently accept a new account.
///
/// A fresh deployment accepts one regardless of the signups flag, so it can be
/// claimed from the app rather than over SSH.
final registrationOpenProvider = FutureProvider<bool>((ref) async {
  final response = await ref.read(apiClientProvider).get('/auth/config/');
  if (!response.ok) return false;
  return response.json['registration_open'] as bool? ?? false;
});
