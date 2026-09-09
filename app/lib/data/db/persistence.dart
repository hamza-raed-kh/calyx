import 'package:drift/drift.dart';

/// How durable the local database actually is on this platform and browser.
///
/// This is decided at *runtime*, not build time. Drift's web backend silently
/// degrades through OPFS -> IndexedDB -> memory depending on what the browser
/// supports and which headers the page was served with, and it never throws.
/// Treating "opened successfully" as "data is safe" is the mistake this enum
/// exists to prevent.
enum PersistenceTier {
  /// Survives reload and is safe across tabs. Native platforms and OPFS.
  durable,

  /// Survives reload, but the browser may evict it under storage pressure,
  /// and some variants are not safe across concurrent tabs.
  bestEffort,

  /// Lost on reload. Offline writes MUST be refused in this tier -- otherwise
  /// a refresh silently eats the outbox with no error anywhere.
  ephemeral,
}

class PersistenceReport {
  const PersistenceReport({
    required this.tier,
    required this.implementation,
    this.missingFeatures = const [],
    this.storagePersisted,
    this.crossTabSafe = true,
  });

  final PersistenceTier tier;

  /// Drift's chosen storage implementation, verbatim (e.g. `opfsLocks`), or
  /// `native` off the web.
  final String implementation;

  /// Browser capabilities drift wanted but could not use. The usual cause is a
  /// missing COOP/COEP header pair rather than an old browser.
  final List<String> missingFeatures;

  /// Result of `navigator.storage.persist()`. Null off the web.
  final bool? storagePersisted;

  /// False for `unsafeIndexedDb`, where two open tabs can corrupt each other.
  final bool crossTabSafe;

  bool get acceptsOfflineWrites => tier != PersistenceTier.ephemeral;

  Map<String, Object?> toJson() => {
    'tier': tier.name,
    'implementation': implementation,
    'missingFeatures': missingFeatures,
    'storagePersisted': storagePersisted,
    'crossTabSafe': crossTabSafe,
    'acceptsOfflineWrites': acceptsOfflineWrites,
  };

  String get summary => switch (tier) {
    PersistenceTier.durable => 'Durable ($implementation)',
    PersistenceTier.bestEffort =>
      'Best effort ($implementation)${crossTabSafe ? '' : ' - not cross-tab safe'}',
    PersistenceTier.ephemeral =>
      'IN MEMORY ONLY ($implementation) - data is lost on reload',
  };
}

class OpenedDatabase {
  const OpenedDatabase({required this.executor, required this.report});

  final QueryExecutor executor;
  final PersistenceReport report;
}
