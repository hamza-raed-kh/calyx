import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart' show kIsWeb;

/// Where the API lives.
///
/// On web the app is served from the same origin as the API, so a relative path
/// is correct and avoids CORS entirely. On Android and Linux there is no origin
/// to be relative to, so the tailnet URL is configured in Settings.
/// Which build this is. Set by CI; "dev" locally.
///
/// Exists because a browser can keep serving a cached bundle long after the
/// image behind it was replaced, so "did my fix actually deploy?" is otherwise
/// unanswerable from the outside.
const kBuildRef = String.fromEnvironment('BUILD_REF', defaultValue: 'dev');

const kDefaultApiBase = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: '/api/v1',
);

class ApiConfig {
  const ApiConfig({required this.baseUrl, this.token});

  final String baseUrl;
  final String? token;

  /// Whether this build can actually reach an API.
  ///
  /// A relative path works on the web, where it resolves against the page's
  /// origin. Off the web there is no origin to resolve against, and Dio rejects
  /// it outright -- so an Android build shipped without API_BASE_URL does not
  /// merely point somewhere useless, it throws while being constructed. Better
  /// to detect that and say so than to crash on launch.
  bool get isUsable {
    if (baseUrl.isEmpty) return false;
    if (kIsWeb) return true;
    return baseUrl.startsWith('http://') || baseUrl.startsWith('https://');
  }
}

class ApiClient {
  ApiClient(this.config) : _dio = _build(config);

  final ApiConfig config;
  final Dio _dio;

  static Dio _build(ApiConfig config) {
    final dio = Dio(
      BaseOptions(
        // Never hand Dio a base it will reject; an unusable config is reported
        // by the UI instead of throwing here.
        baseUrl: config.isUsable
            ? config.baseUrl
            : 'http://unconfigured.invalid',
        connectTimeout: const Duration(seconds: 10),
        receiveTimeout: const Duration(seconds: 30),
        // Never throw on a status code: sync needs to inspect 4xx bodies to
        // decide between "retry later" and "dead-letter this permanently".
        validateStatus: (_) => true,
        headers: {
          if (config.token != null && config.token!.isNotEmpty)
            'Authorization': 'Token ${config.token}',
        },
      ),
    );
    return dio;
  }

  Future<ApiResponse> get(String path, {Map<String, dynamic>? query}) async {
    final response = await _dio.get<dynamic>(path, queryParameters: query);
    return ApiResponse(response.statusCode ?? 0, response.data);
  }

  Future<ApiResponse> post(String path, Object? body) async {
    final response = await _dio.post<dynamic>(path, data: body);
    return ApiResponse(response.statusCode ?? 0, response.data);
  }
}

class ApiResponse {
  const ApiResponse(this.status, this.data);

  final int status;
  final dynamic data;

  bool get ok => status >= 200 && status < 300;

  /// A request that failed in a way that retrying might fix. Distinguishing
  /// this from a permanent rejection is the difference between an outbox that
  /// drains and one that jams forever on a single bad row.
  bool get isTransient =>
      status == 0 || status >= 500 || status == 408 || status == 429;

  Map<String, dynamic> get json => data is Map<String, dynamic>
      ? data as Map<String, dynamic>
      : <String, dynamic>{};
}

class ApiException implements Exception {
  ApiException(this.message);
  final String message;
  @override
  String toString() => 'ApiException: $message';
}
