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
Future<OpenedDatabase> openDatabase() async {
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

  // Best-effort request that the browser not evict us under storage pressure.
  // Never a guarantee, and deliberately not treated as one.
  bool? persisted;
  try {
    persisted = await web.window.navigator.storage.persist().toDart.then(
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
