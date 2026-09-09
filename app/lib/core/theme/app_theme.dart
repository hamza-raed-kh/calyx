import 'package:flutter/material.dart';

import 'tokens.dart';

abstract final class AppTheme {
  static ThemeData get dark => _build(
    brightness: Brightness.dark,
    background: DarkPalette.background,
    surface: DarkPalette.surfaceStrong,
    primary: DarkPalette.primary,
    onPrimary: DarkPalette.onPrimary,
    text: DarkPalette.text,
    muted: DarkPalette.textMuted,
    danger: DarkPalette.danger,
  );

  static ThemeData get light => _build(
    brightness: Brightness.light,
    background: LightPalette.background,
    surface: LightPalette.surfaceStrong,
    primary: LightPalette.primary,
    onPrimary: LightPalette.onPrimary,
    text: LightPalette.text,
    muted: LightPalette.textMuted,
    danger: LightPalette.danger,
  );

  static ThemeData _build({
    required Brightness brightness,
    required Color background,
    required Color surface,
    required Color primary,
    required Color onPrimary,
    required Color text,
    required Color muted,
    required Color danger,
  }) {
    final scheme = ColorScheme(
      brightness: brightness,
      primary: primary,
      onPrimary: onPrimary,
      secondary: primary,
      onSecondary: onPrimary,
      error: danger,
      onError: Colors.white,
      surface: surface,
      onSurface: text,
    );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: background,
      textTheme: Typography.material2021(platform: TargetPlatform.android).black
          .apply(bodyColor: text, displayColor: text)
          .copyWith(bodySmall: TextStyle(color: muted)),
      cardTheme: CardThemeData(
        shape: const RoundedRectangleBorder(borderRadius: Radii.cardBorder),
        color: surface,
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          shape: const RoundedRectangleBorder(borderRadius: Radii.chipBorder),
          padding: const EdgeInsets.symmetric(
            horizontal: Spacing.lg,
            vertical: Spacing.md,
          ),
        ),
      ),
    );
  }
}
