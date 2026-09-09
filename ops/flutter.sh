#!/usr/bin/env bash
# Run a Flutter/Dart command in Docker.
#
# The SDK is not installed on the host on purpose: this pins the toolchain to
# the same stable channel CI uses, so "works locally" and "works in CI" cannot
# drift apart. The pub cache lives in a named volume so repeat runs are fast.
#
#   ./ops/flutter.sh flutter pub get
#   ./ops/flutter.sh flutter build web --release
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# Pinned, not ":stable". A moving tag means a locally cached image can be
# months behind whatever CI resolves, and the skew surfaces as pubspec.lock and
# generated-code churn that fails CI for no reason connected to the change.
FLUTTER_VERSION="$(cat "$REPO/.flutter-version")"
IMAGE="${FLUTTER_IMAGE:-ghcr.io/cirruslabs/flutter:$FLUTTER_VERSION}"
WORKDIR="${FLUTTER_WORKDIR:-/work/app}"

docker run --rm \
    -v "$REPO:/work" \
    -v tasks_pub_cache:/root/.pub-cache \
    -v tasks_gradle_cache:/root/.gradle \
    -e PUB_CACHE=/root/.pub-cache \
    -e HOME=/root \
    -w "$WORKDIR" \
    "$IMAGE" "$@"

# The container writes as root; hand the files back so the host can edit them.
docker run --rm -v "$REPO:/work" --entrypoint chown alpine:3 \
    -R "$(id -u):$(id -g)" /work >/dev/null 2>&1 || true
