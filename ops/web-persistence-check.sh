#!/usr/bin/env bash
# Asserts the served web app actually reaches durable OPFS storage.
#
# This is a regression guard for a silent failure. Drift's WASM backend never
# throws -- it degrades through OPFS -> IndexedDB -> memory depending on what
# the browser can do, and reaching OPFS on Chrome requires the page to be
# cross-origin isolated by the COOP/COEP headers in ops/Caddyfile. Delete those
# headers and everything still "works", it just quietly stops being durable.
#
#   ./ops/web-persistence-check.sh                      # default https://localhost/
#   ./ops/web-persistence-check.sh https://tasks.x.ts.net/
#   EXPECT_TIER=bestEffort ./ops/web-persistence-check.sh ...
set -euo pipefail

TARGET="${1:-https://localhost/}"
EXPECT_TIER="${EXPECT_TIER:-durable}"
CHROME_IMAGE="${CHROME_IMAGE:-chromedp/headless-shell:latest}"
PORT="${CDP_PORT:-9222}"
NAME="web-persistence-check-$$"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --rm --name "$NAME" --network host \
    --entrypoint /headless-shell/headless-shell "$CHROME_IMAGE" \
    --headless --no-sandbox --disable-gpu \
    --ignore-certificate-errors \
    --remote-debugging-port="$PORT" --remote-debugging-address=0.0.0.0 >/dev/null

for _ in $(seq 1 30); do
    curl -sf "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1 && break
    sleep 1
done

REPORT="$(CDP="http://127.0.0.1:${PORT}" TARGET="$TARGET" node "$(dirname "$0")/web-probe.mjs")"
echo "$REPORT" | python3 -m json.tool

TIER="$(echo "$REPORT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tier"])')"
ISOLATED="$(echo "$REPORT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["crossOriginIsolated"])')"

if [[ "$TIER" != "$EXPECT_TIER" ]]; then
    echo "FAIL: storage tier is '$TIER', expected '$EXPECT_TIER'." >&2
    [[ "$ISOLATED" == "False" ]] && echo "      crossOriginIsolated is false -- check COOP/COEP in ops/Caddyfile." >&2
    exit 1
fi

echo "PASS: $TARGET reaches the '$TIER' tier."
