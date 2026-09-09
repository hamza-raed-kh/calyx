/// Android and Linux.
///
/// There is no origin to ask, so the API address is baked in at build time via
/// --dart-define=API_BASE_URL. Nothing to resolve at runtime.
Future<String?> runtimeApiBaseUrl() async => null;
