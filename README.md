# calyx

Personal task and habit tracker. Django REST API plus a Flutter client (web,
Android, Linux desktop), self-hosted on a home server over Tailscale.

Single user by design: there is no owner foreign key anywhere in the schema and
settings models are singletons.

## What makes this one different

The habit half does not assume a habit is "a checkbox you tick once a day":

| Habit | Shape |
|---|---|
| Five prayers | five windowed slots per day, boundaries computed astronomically and moving daily |
| Quran, chess | one habit, satisfied by *either* of two components; which one is recorded |
| Piano | three times a week, no fixed days |
| Brushing teeth | twice a day, morning and evening windows |
| Work session | daily, linked to a project |
| Reading, walking | daily with optional numeric targets |

All six shapes come out of one engine. Adding a seventh is data entry, not code.

Two decisions worth knowing before reading the source:

- **Occurrences are computed, never stored.** What is materialised is the
  astronomical input (`PrayerTimeDay`), not the expectation derived from it.
  Schedules are temporally versioned, so editing a habit cannot corrupt history
  and backfilling into an old schedule sees the old slots and old target.
- **There are no streaks.** Stats are completion rates over trailing windows
  plus a per-slot breakdown, which is what actually answers "which prayer do I
  keep missing" without all-or-nothing framing.

## Layout

```
backend/   Django 5.2 + DRF, Postgres 17
app/       Flutter client
ops/       compose, Caddyfile, deploy/backup scripts, the Flutter wrapper
.github/   CI, image and release workflows
```

## Local development

```sh
cp ops/.env.example ops/.env      # fill in the two secrets
make up
make migrate
make seed LAT=21.3891 LON=39.8579 TZ=Asia/Riyadh
curl -k https://localhost/api/v1/health/
```

Caddy serves `https://localhost` with its own internal CA, so `curl` needs `-k`
and the browser warns once. **HTTPS locally is not optional**: the Flutter web
client needs a secure context for OPFS storage, so developing over plain HTTP
would exercise a different, weaker storage tier than production.

Flutter is not installed on the host. `ops/flutter.sh` runs the SDK in Docker,
pinned by `.flutter-version` to exactly the version CI uses, so "works locally"
and "works in CI" cannot drift apart.

```sh
make flutter ARGS="pub get"
make web-build && make web-deploy
make web-check          # asserts the served app reaches durable OPFS storage
make check              # everything CI runs
```

### Why `make web-check` exists

Drift's web backend never throws. It degrades OPFS → IndexedDB → memory
depending on the browser and the response headers, and reaching OPFS on Chrome
requires the page to be cross-origin isolated by the COOP/COEP headers in
`ops/Caddyfile`. Delete those headers and everything still "works" — it just
quietly stops being durable, and a refresh eats the outbox. Measured:

| | With COOP/COEP | Without |
|---|---|---|
| `crossOriginIsolated` | `true` | `false` |
| storage | `opfsLocks` | `sharedIndexedDb` |
| tier | durable | best effort |

## Deploying anywhere: `compose.yaml`

`compose.yaml` at the repo root is self-contained. Copy that one file to an
empty directory and run it — no `.env`, no proxy config, no source tree:

```sh
docker compose up -d
```

Images are pinned by name and pulled from GHCR (public, multi-arch), migrations
run to completion before the API starts, and every setting has a default. It
publishes **two ports for your own reverse proxy** and nothing else:

| Port | Service |
|---|---|
| `8080` (`WEB_PORT`) | the Flutter web app |
| `8000` (`API_PORT`) | the Django API and admin |

Postgres is never published; it exists only on the internal network.

### What your proxy must do

**Map both onto one hostname.** Same origin means no CORS and no rebuild — the
web bundle calls the API at the relative path `/api/v1`:

```
/        ->  127.0.0.1:8080
/api     ->  127.0.0.1:8000
/admin   ->  127.0.0.1:8000
/static  ->  127.0.0.1:8000
```

Two different hostnames also work, but then set the API address by hand in the
app's Settings screen.

**Terminate TLS.** This is not about confidentiality on your own network. The
web client needs a *secure context* for OPFS storage, and browsers exempt
`localhost` only — measured, over plain HTTP on a LAN address:

| Served as | Secure context | Storage |
|---|---|---|
| `https://…` or `http://localhost` | yes | `opfsLocks`, durable |
| `http://192.168.x.x` | **no** | `sharedIndexedDb`, evictable |

**Do not strip `Cross-Origin-Opener-Policy` or `Cross-Origin-Embedder-Policy`.**
The bundled nginx sets them, so you have nothing to configure — but a proxy that
drops them silently downgrades storage in the same way, with no error anywhere.

Verify any of this against a running deployment:

```sh
./ops/web-persistence-check.sh https://tasks.example.ts.net/
```

Set `DJANGO_CSRF_TRUSTED_ORIGINS` to your external origin if you want to log
into `/admin/` through the proxy. The API generates and persists its own signing
key on first boot, so this file carries no published secret.

## Deploying to the home server

The alternative to the standalone file above: `ops/docker-compose.yml` bundles
Caddy, which terminates TLS with a tailnet certificate and serves both halves
from one origin, so there is no external proxy to run at all.

CI cannot reach the server — nothing is exposed publicly — so it publishes
multi-arch images to GHCR and you pull:

```sh
ssh homeserver '/srv/tasks/ops/deploy.sh v1.2.0'
```

`deploy.sh` backs up, pulls, migrates, publishes the web bundle, restarts and
health-checks, in that order, recording the previous image so rollback is
`./deploy.sh <previous-tag>`.

Watchtower is deliberately not used: it restarts containers *without* running
migrations, so a new image boots against the old schema and 500s until somebody
notices.

On the server, use the Tailscale overlay so Caddy can fetch a tailnet
certificate straight from `tailscaled` — no cert files, no renewal cron:

```sh
docker compose -f docker-compose.yml -f docker-compose.tailscale.yml up -d
```

Set `SITE_ADDRESS=tasks.<your-tailnet>.ts.net` in `ops/.env` first, and enable
HTTPS certificates for the tailnet in the Tailscale admin console.

## Connecting the app

```sh
make superuser
docker compose -f ops/docker-compose.yml run --rm api \
    python manage.py drf_create_token <username>
```

- **Web** is served from the API's own origin, so it needs no configuration.
- **Android and Linux** have no origin to be relative to: open Settings in the
  app and set the API address to `https://tasks.<tailnet>.ts.net/api/v1` plus
  the token above.

Signups are off unless `ALLOW_SIGNUPS=true`. Tailscale already provides device
authentication, so the token is the second factor rather than the only one.

## Reminders

Device-local, no push service. Android checks for the exact-alarm permission
before **every** scheduling pass — it is denied by default on Android 14+ and
can vanish after a backup-and-restore — and falls back to inexact alarms with a
visible warning rather than silently scheduling nothing.

A rolling seven-day window, so a settings change takes effect within a day and
moving cities does not leave weeks of wrong alarms pinned to the system.

Linux gets reminders only while the app is open (`zonedSchedule` throws
`UnimplementedError` there). Web gets none: Web Push would require public FCM
or Mozilla endpoints, which contradicts a deployment kept off the internet.

## Backups

`ops/backup.sh` runs nightly via `ops/tasks-backup.timer` (install both unit
files to `/etc/systemd/system/`). Dumps go to `/srv/backups`, retained 14 days.

Two things are on you, not the scripts:

1. Point `BACKUP_DIR` at a **different physical disk** from the Postgres volume.
2. Wire up the off-box copy at the bottom of `backup.sh`. A home server is one
   house fire from total loss.

`make restore-check` restores the newest dump into a throwaway container and
asserts it has tables. Run it monthly; an untested backup is a hope.
