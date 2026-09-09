import 'dart:convert';
import 'dart:js_interop';
import 'dart:js_interop_unsafe';

import 'package:drift/wasm.dart';
import 'package:web/web.dart' as web;

import '../persistence.dart';

/// Web. The storage tier is decided at runtime and must be inspected.
///
/// `WasmDatabase.open` never throws -- it falls back through OPFS, to
/// IndexedDB, to memory, reporting what it picked. Ignoring
/// `chosenImplementation` means shipping an app that looks fine and loses data
/// on refresh in whichever browser happens to land on `inMemory`.
///
/// Reaching OPFS on Chrome additionally requires the page to be
/// cross-origin isolated:
///
///     Cross-Origin-Opener-Policy: same-origin
///     Cross-Origin-Embedder-Policy: require-corp
///
/// Those come from the reverse proxy (see ops/Caddyfile), not from Flutter, so
/// a missing header shows up here as a downgraded tier.
/// How long to wait for the browser to hand over a database before giving up.
///
/// WasmDatabase.open() can simply never settle -- a worker that fails to start,
/// or a storage backend waiting on something that never arrives. Awaiting that
/// forever is indistinguishable from a frozen tab and leaves nothing on screen
/// to explain why. There is no useful fallback on the web (WASM SQLite is the
/// only SQLite there), so the honest move is to fail quickly and say so.
const _openTimeout = Duration(seconds: 8);

class StorageUnavailable implements Exception {
  StorageUnavailable(this.detail);

  final String detail;

  @override
  String toString() =>
      'This browser did not provide local storage within '
      '${_openTimeout.inSeconds}s. calyx keeps everything in a local database, '
      'so it cannot start without one.\n\n$detail';
}

Future<OpenedDatabase> openDatabase() async {
  try {
    return await _openWasm().timeout(_openTimeout);
  } on StorageUnavailable {
    rethrow;
  } on Object catch (error) {
    throw StorageUnavailable('$error');
  }
}

Future<OpenedDatabase> _openWasm() async {
  final result = await WasmDatabase.open(
    databaseName: 'tasks',
    sqlite3Uri: Uri.parse('sqlite3.wasm'),
    driftWorkerUri: Uri.parse('drift_worker.js'),
  );

  final implementation = result.chosenImplementation;
  final tier = switch (implementation) {
    WasmStorageImplementation.opfsShared ||
    WasmStorageImplementation.opfsLocks => PersistenceTier.durable,
    WasmStorageImplementation.sharedIndexedDb ||
    WasmStorageImplementation.unsafeIndexedDb => PersistenceTier.bestEffort,
    WasmStorageImplementation.inMemory => PersistenceTier.ephemeral,
  };

  // QUERY the eviction-protection state; never request it here.
  //
  // persist() prompts the user on Firefox, and awaiting that prompt on the
  // startup path blocks the database opening -- so the whole app hangs on a
  // permission dialog nobody asked for. persisted() reports the same state and
  // never prompts. Requesting it belongs behind an explicit action, if at all.
  bool? persisted;
  try {
    persisted = await web.window.navigator.storage.persisted().toDart.then(
      (v) => v.toDart,
    );
  } catch (_) {
    persisted = null;
  }

  final report = PersistenceReport(
    tier: tier,
    implementation: implementation.name,
    missingFeatures: result.missingFeatures.map((f) => f.name).toList(),
    storagePersisted: persisted,
    crossTabSafe: implementation != WasmStorageImplementation.unsafeIndexedDb,
  );

  _publishDiagnostics(report);
  return OpenedDatabase(executor: result.resolvedExecutor, report: report);
}

/// Mirror the probe result into the DOM and onto `globalThis`.
///
/// The app paints to a canvas, so there is otherwise no way to see which
/// storage tier a given browser actually resolved to -- not from devtools, not
/// from an automated check, not from a bug report. Cheap, and the only
/// practical way to diagnose "it forgot my data" on someone else's machine.
void _publishDiagnostics(PersistenceReport report) {
  final payload = jsonEncode({
    'isSecureContext': web.window.isSecureContext,
    'crossOriginIsolated': web.window.crossOriginIsolated,
    ...report.toJson(),
  });

  final node = web.document.createElement('div') as web.HTMLElement;
  node.id = 'drift-persistence';
  node.setAttribute('style', 'display:none');
  node.textContent = payload;
  web.document.body?.appendChild(node);

  globalContext.setProperty('driftPersistence'.toJS, payload.toJS);
}
