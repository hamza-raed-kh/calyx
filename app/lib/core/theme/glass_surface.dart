import 'dart:ui';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';

import 'tokens.dart';

/// Whether real backdrop blur is affordable here.
///
/// It is not, on the web. Flutter renders through CanvasKit, where every
/// BackdropFilter forces a readback and re-rasterisation of everything beneath
/// it, once per layer, per frame. Chromium absorbs a couple; Firefox does not,
/// and a screen with several -- a settings page of cards, or a list where each
/// row is its own blurred surface -- can stop responding altogether.
///
/// The fallback is a flat translucent fill. On a dark theme the difference is
/// close to invisible, and it costs nothing.
const bool kBackdropBlurIsAffordable = !kIsWeb;

/// The one translucent container in the app.
///
/// Everything that looks like frosted glass goes through here, so the blur
/// budget stays countable and can be switched off in one place.
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

    // Slightly more opaque without the blur, so the surface still separates
    // from the background rather than looking like a stray border.
    final fill = isDark
        ? (kBackdropBlurIsAffordable
              ? DarkPalette.surface
              : DarkPalette.surfaceStrong)
        : (kBackdropBlurIsAffordable
              ? LightPalette.surface
              : LightPalette.surfaceStrong);

    final surface = DecoratedBox(
      decoration: BoxDecoration(
        color: fill,
        borderRadius: borderRadius,
        border: Border.all(
          color: isDark ? DarkPalette.border : LightPalette.border,
        ),
      ),
      child: Padding(padding: padding, child: child),
    );

    if (!kBackdropBlurIsAffordable) {
      return ClipRRect(borderRadius: borderRadius, child: surface);
    }

    return ClipRRect(
      borderRadius: borderRadius,
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: blur, sigmaY: blur),
        child: surface,
      ),
    );
  }
}
