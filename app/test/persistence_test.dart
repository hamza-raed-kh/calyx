import 'package:flutter_test/flutter_test.dart';
import 'package:tasks/data/db/persistence.dart';

void main() {
  group('PersistenceReport', () {
    test('refuses offline writes only in the ephemeral tier', () {
      const ephemeral = PersistenceReport(
        tier: PersistenceTier.ephemeral,
        implementation: 'inMemory',
      );
      const bestEffort = PersistenceReport(
        tier: PersistenceTier.bestEffort,
        implementation: 'unsafeIndexedDb',
      );
      const durable = PersistenceReport(
        tier: PersistenceTier.durable,
        implementation: 'opfsLocks',
      );

      expect(ephemeral.acceptsOfflineWrites, isFalse);
      expect(bestEffort.acceptsOfflineWrites, isTrue);
      expect(durable.acceptsOfflineWrites, isTrue);
    });

    test('ephemeral summary states the consequence, not just the tier', () {
      const report = PersistenceReport(
        tier: PersistenceTier.ephemeral,
        implementation: 'inMemory',
      );
      // A user staring at "ephemeral" learns nothing; they need to know a
      // refresh destroys their data.
      expect(report.summary, contains('lost on reload'));
    });

    test('flags a tier that is not safe across tabs', () {
      const report = PersistenceReport(
        tier: PersistenceTier.bestEffort,
        implementation: 'unsafeIndexedDb',
        crossTabSafe: false,
      );
      expect(report.summary, contains('not cross-tab safe'));
    });

    test(
      'reports missing browser features so a header problem is diagnosable',
      () {
        const report = PersistenceReport(
          tier: PersistenceTier.bestEffort,
          implementation: 'sharedIndexedDb',
          missingFeatures: ['fileSystemAccess', 'sharedWorkers'],
        );
        expect(report.missingFeatures, hasLength(2));
      },
    );
  });
}
