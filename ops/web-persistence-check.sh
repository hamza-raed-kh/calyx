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

SECURE="$(echo "$REPORT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["isSecureContext"])')"

if [[ "$TIER" != "$EXPECT_TIER" ]]; then
    echo "FAIL: storage tier is '$TIER', expected '$EXPECT_TIER'." >&2
    if [[ "$SECURE" == "False" ]]; then
        # The likelier cause in a proxied deployment, and it is not fixable by
        # any header: OPFS needs a secure context, and only localhost gets one
        # without TLS.
        echo "      Not a secure context. Serve over HTTPS -- browsers exempt" >&2
        echo "      localhost only, so a plain-HTTP LAN address will always" >&2
        echo "      degrade to evictable storage." >&2
    elif [[ "$ISOLATED" == "False" ]]; then
        echo "      crossOriginIsolated is false: the COOP/COEP headers are" >&2
        echo "      missing or were stripped by a proxy in front." >&2
    fi
    exit 1
fi

echo "PASS: $TARGET reaches the '$TIER' tier."
