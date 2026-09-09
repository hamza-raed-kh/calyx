import 'package:calyx/core/providers.dart';
import 'package:calyx/data/api/api_client.dart';
import 'package:calyx/data/db/database.dart';
import 'package:calyx/features/auth/auth_controller.dart';
import 'package:drift/native.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

/// Answers /auth/me/ with whatever the test dictates.
class _FakeApi extends ApiClient {
  _FakeApi(this.status, {this.body = const {}})
    : super(const ApiConfig(baseUrl: 'https://example.test/api/v1'));

  final int status;
  final Map<String, dynamic> body;
  final calls = <String>[];

  @override
  Future<ApiResponse> get(String path, {Map<String, dynamic>? query}) async {
    calls.add(path);
    return ApiResponse(status, body);
  }

  @override
  Future<ApiResponse> post(String path, Object? data) async {
    calls.add(path);
    return ApiResponse(status, body);
  }
}

Future<(ProviderContainer, AppDatabase)> _harness(
  _FakeApi api, {
  String? token,
}) async {
  final db = AppDatabase(NativeDatabase.memory());
  if (token != null) await db.setMeta('api_token', token);

  final container = ProviderContainer(
    overrides: [
      dbProvider.overrideWithValue(db),
      apiClientProvider.overrideWithValue(api),
    ],
  );
  return (container, db);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('stored session', () {
    test('no token means signed out, and the server is never asked', () async {
      final api = _FakeApi(200);
      final (container, _) = await _harness(api);

      final state = await container.read(authControllerProvider.future);

      expect(state.isSignedIn, isFalse);
      expect(api.calls, isEmpty, reason: 'nothing to validate');
    });

    test('a valid token signs you in', () async {
      final api = _FakeApi(200, body: {'username': 'omar'});
      final (container, _) = await _harness(api, token: 'good-token');

      final state = await container.read(authControllerProvider.future);

      expect(state.isSignedIn, isTrue);
      expect(state.username, 'omar');
      expect(api.calls, contains('/auth/me/'));
    });

    test('a REJECTED token does not sign you in', () async {
      // The bug this exists for: a token left over from an older build, or
      // belonging to a database that has since been wiped, looked identical to
      // a valid one -- so the app sailed past sign-in and then failed every
      // sync with no explanation.
      final api = _FakeApi(401);
      final (container, db) = await _harness(api, token: 'stale-token');

      final state = await container.read(authControllerProvider.future);

      expect(state.isSignedIn, isFalse);
      expect(
        await db.meta('api_token'),
        isEmpty,
        reason: 'the dead token is cleared',
      );
    });

    test('a forbidden token is treated the same as rejected', () async {
      final api = _FakeApi(403);
      final (container, _) = await _harness(api, token: 'stale-token');
      expect(
        (await container.read(authControllerProvider.future)).isSignedIn,
        isFalse,
      );
    });

    test('being offline does NOT sign you out', () async {
      // Losing the network is not the same as losing authorisation. Signing
      // somebody out on a flaky connection would be its own bug.
      final api = _FakeApi(0);
      final (container, db) = await _harness(api, token: 'good-token');

      final state = await container.read(authControllerProvider.future);

      expect(state.isSignedIn, isTrue);
      expect(await db.meta('api_token'), 'good-token');
    });

    test('a server error does not sign you out either', () async {
      final api = _FakeApi(503);
      final (container, _) = await _harness(api, token: 'good-token');
      expect(
        (await container.read(authControllerProvider.future)).isSignedIn,
        isTrue,
      );
    });
  });
}
