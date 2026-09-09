import 'package:flutter/widgets.dart';

/// Every radius, blur and opacity in the app comes from here.
///
/// Centralised because the design language leans on translucency, and blur that
/// is tuned per-widget drifts into inconsistency within a dozen screens.
abstract final class Radii {
  static const small = Radius.circular(10);
  static const medium = Radius.circular(18);
  static const large = Radius.circular(28);
  static const pill = Radius.circular(999);

  static const cardBorder = BorderRadius.all(medium);
  static const sheetBorder = BorderRadius.all(large);
  static const chipBorder = BorderRadius.all(pill);
}

abstract final class Blurs {
  /// BackdropFilter is expensive -- on web, stacked blurs visibly drop frames.
  /// Budget: at most two blurred layers per screen, and never inside a
  /// scrolling list item. Blur the container, not the rows.
  static const surface = 18.0;
  static const overlay = 32.0;
}

abstract final class Spacing {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 16.0;
  static const lg = 24.0;
  static const xl = 40.0;
}

/// Dark is the primary design; light is derived from it, not the other way
/// round.
abstract final class DarkPalette {
  static const background = Color(0xFF0B0D10);
  static const surface = Color(0x14FFFFFF);
  static const surfaceStrong = Color(0x1FFFFFFF);
  static const border = Color(0x1FFFFFFF);
  static const primary = Color(0xFF7FD1C1);
  static const onPrimary = Color(0xFF06231D);
  static const text = Color(0xFFECEFF3);
  static const textMuted = Color(0xFF9BA4B0);
  static const danger = Color(0xFFFF6B6B);
  static const warning = Color(0xFFFFC24B);
  static const success = Color(0xFF6BE3A6);
}

abstract final class LightPalette {
  static const background = Color(0xFFF6F7F9);
  static const surface = Color(0xCCFFFFFF);
  static const surfaceStrong = Color(0xFFFFFFFF);
  static const border = Color(0x14000000);
  static const primary = Color(0xFF1F7A69);
  static const onPrimary = Color(0xFFFFFFFF);
  static const text = Color(0xFF11161C);
  static const textMuted = Color(0xFF5C6672);
  static const danger = Color(0xFFC0392B);
  static const warning = Color(0xFF9A6700);
  static const success = Color(0xFF1B7F4E);
}
