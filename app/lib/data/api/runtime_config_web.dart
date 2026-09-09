import 'dart:convert';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

/// Web.
///
/// The API address is served by the container that serves this app, so one
/// published image works for any hostname without a rebuild. Falling back to
/// the compile-time default keeps `flutter run` and same-origin deployments
/// working with no configuration at all.
Future<String?> runtimeApiBaseUrl() async {
  try {
    final response = await web.window.fetch('/config.json'.toJS).toDart;
    if (!response.ok) return null;
    final body = (await response.text().toDart).toDart;
    final decoded = jsonDecode(body);
    if (decoded is! Map) return null;
    final value = decoded['apiBaseUrl'];
    return value is String && value.isNotEmpty ? value : null;
  } catch (_) {
    // No config served, or it is malformed. The compile-time default applies.
    return null;
  }
}
