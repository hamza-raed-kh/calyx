# tasks

Personal task and habit tracker. Django REST API + Flutter client (web, Android,
Linux desktop), self-hosted on a home server over Tailscale.

Single user by design: there is no owner foreign key anywhere in the schema and
settings models are singletons.

## Layout

```
backend/   Django 5.2 + DRF, Postgres 17
app/       Flutter client            (not scaffolded yet -- step 2)
ops/       compose, Caddyfile, deploy/backup scripts
.github/   CI and image workflows
```

The full design, including why habits are modelled as computed occurrences
rather than stored rows, is in `~/.claude/plans/wise-herding-dolphin.md`.

## Local development

```sh
cp ops/.env.example ops/.env      # then fill in the two secrets
make up
curl -k https://localhost/api/v1/health/
```

Caddy serves on `https://localhost` with its own internal CA, so `curl` needs
`-k` and the browser will warn once. **HTTPS locally is not optional**: the
Flutter web client needs a secure context for OPFS storage and service workers,
so developing over plain HTTP would exercise a different storage tier than
production.

`make help` lists everything. `make check` runs exactly what CI runs.

## Deployment

CI cannot reach the home server -- nothing is exposed publicly -- so it builds
and publishes images to GHCR and you pull:

```sh
ssh homeserver '/srv/tasks/ops/deploy.sh v1.2.0'
```

`deploy.sh` backs up, pulls, migrates, publishes the web bundle, restarts and
health-checks, in that order. It records the previous image so rollback is
`./deploy.sh <previous-tag>`.

Watchtower is deliberately not used: it restarts containers without running
migrations, which would boot a new image against the old schema.

## Backups

`ops/backup.sh` runs nightly via `ops/tasks-backup.timer` (install both unit
files to `/etc/systemd/system/`). Dumps go to `/srv/backups`, retained 14 days.

Two things that are on you, not the scripts:

1. Point `BACKUP_DIR` at a **different physical disk** from the Postgres volume.
2. Wire up the off-box copy at the bottom of `backup.sh`. A home server is one
   house fire from total loss.

`make restore-check` restores the newest dump into a throwaway container and
asserts it has tables. Run it monthly; an untested backup is a hope.
