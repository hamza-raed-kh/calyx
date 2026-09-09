import 'dart:io';

import 'package:drift/native.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import '../persistence.dart';

/// Android and Linux desktop. SQLite is bundled by the `sqlite3` package on
/// both since drift 2.32, so neither needs a system library or an extra
/// dependency.
Future<OpenedDatabase> openDatabase() async {
  final directory = await getApplicationDocumentsDirectory();
  final file = File(p.join(directory.path, 'tasks.sqlite'));

  return OpenedDatabase(
    // createInBackground runs SQLite on its own isolate, so a long query cannot
    // jank the UI thread.
    executor: NativeDatabase.createInBackground(file),
    report: const PersistenceReport(
      tier: PersistenceTier.durable,
      implementation: 'native',
    ),
  );
}
