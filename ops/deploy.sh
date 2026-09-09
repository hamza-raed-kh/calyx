#!/usr/bin/env bash
# Deploy a tagged release on the home server.
#
#   ./deploy.sh v1.2.0                 # deploy that tag
#   ./deploy.sh "$(cat .env.image.prev | cut -d= -f2)"   # roll back
#
# Deliberately NOT Watchtower: Watchtower pulls and restarts without running
# migrations, so a new image boots against the old schema and 500s until
# somebody notices. Order here is: back up, pull, migrate, restart, verify.
set -euo pipefail

TAG="${1:?usage: deploy.sh <tag-or-digest>}"
cd "$(dirname "$0")"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.tailscale.yml)
OWNER="${GHCR_OWNER:?set GHCR_OWNER in the environment or .env}"

echo "==> backing up before touching anything"
./backup.sh

[[ -f .env.image ]] && cp -f .env.image .env.image.prev
cat > .env.image <<EOT
API_IMAGE=ghcr.io/${OWNER}/calyx-api:${TAG}
WEB_IMAGE=ghcr.io/${OWNER}/calyx-web:${TAG}
EOT
set -a; source .env.image; set +a

echo "==> pulling ${TAG}"
"${COMPOSE[@]}" --profile app pull

echo "==> migrating"
"${COMPOSE[@]}" run --rm api python manage.py migrate --noinput

echo "==> publishing web bundle"
"${COMPOSE[@]}" --profile app up --no-deps web

echo "==> restarting services"
"${COMPOSE[@]}" up -d --remove-orphans

echo "==> verifying"
for i in {1..30}; do
    if curl -fsS --max-time 5 "https://${SITE_ADDRESS}/api/v1/health/" >/dev/null 2>&1; then
        echo "deploy OK: ${TAG}"
        "${COMPOSE[@]}" ps
        exit 0
    fi
    sleep 2
done

echo "FATAL: health check never passed after deploying ${TAG}" >&2
echo "roll back with: ./deploy.sh \$(cut -d= -f2 <<< \"\$(grep API_IMAGE .env.image.prev)\" | cut -d: -f2)" >&2
exit 1
