import '../persistence.dart';

Future<OpenedDatabase> openDatabase() {
  throw UnsupportedError('No drift connection backend for this platform');
}
