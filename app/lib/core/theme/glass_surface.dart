import 'dart:ui';

import 'package:flutter/material.dart';

import 'tokens.dart';

/// The one blurred container in the app.
///
/// Everything translucent goes through this widget so the blur budget stays
/// countable. Deliberately not usable as a list item: `BackdropFilter` inside a
/// scrolling list re-rasterises every frame and is the single easiest way to
/// make a Flutter web build feel broken.
class GlassSurface extends StatelessWidget {
  const GlassSurface({
    super.key,
    required this.child,
    this.borderRadius = Radii.cardBorder,
    this.padding = const EdgeInsets.all(Spacing.md),
    this.blur = Blurs.surface,
  });

  final Widget child;
  final BorderRadius borderRadius;
  final EdgeInsetsGeometry padding;
  final double blur;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return ClipRRect(
      borderRadius: borderRadius,
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: blur, sigmaY: blur),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: isDark ? DarkPalette.surface : LightPalette.surface,
            borderRadius: borderRadius,
            border: Border.all(
              color: isDark ? DarkPalette.border : LightPalette.border,
            ),
          ),
          child: Padding(padding: padding, child: child),
        ),
      ),
    );
  }
}
