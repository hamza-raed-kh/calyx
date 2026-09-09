# Convenience wrappers around docker compose. All commands are run from the
# repo root; compose itself lives in ops/.
export HOST_UID := $(shell id -u)
export HOST_GID := $(shell id -g)
COMPOSE := docker compose -f ops/docker-compose.yml

.PHONY: help up down restart logs ps build migrate makemigrations superuser shell test lint fmt check backup restore-check web-build web-deploy web-check flutter

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

up:              ## Start db, api and caddy
	$(COMPOSE) up -d db api caddy
down:            ## Stop everything (volumes preserved)
	$(COMPOSE) down
restart:         ## Restart the api
	$(COMPOSE) restart api
logs:            ## Tail logs
	$(COMPOSE) logs -f --tail=100
ps:              ## Service status
	$(COMPOSE) ps
build:           ## Rebuild the api image
	$(COMPOSE) build api

migrate:         ## Apply migrations
	$(COMPOSE) run --rm api python manage.py migrate
makemigrations:  ## Generate migrations
	$(COMPOSE) --profile test run --rm test python manage.py makemigrations
superuser:       ## Create the (single) user
	$(COMPOSE) run --rm api python manage.py createsuperuser
shell:           ## Django shell
	$(COMPOSE) run --rm api python manage.py shell

test:            ## Run the backend suite
	$(COMPOSE) --profile test run --rm test pytest
lint:            ## ruff check + format check (what CI runs)
	$(COMPOSE) --profile test run --rm test sh -c "ruff check . && ruff format --check ."
fmt:             ## Autoformat and autofix
	$(COMPOSE) --profile test run --rm test sh -c "ruff check --fix . && ruff format ."
check:           ## Everything CI runs
	$(MAKE) lint
	$(COMPOSE) --profile test run --rm test python manage.py makemigrations --check --dry-run
	$(MAKE) test

web-build:       ## Build the Flutter web bundle
	./ops/flutter.sh flutter build web --release --dart-define=API_BASE_URL=/api/v1
web-deploy:      ## Publish the built bundle into the serving volume
	$(COMPOSE) --profile app build web
	$(COMPOSE) --profile app up web
web-check:       ## Assert the served app reaches durable OPFS storage
	./ops/web-persistence-check.sh
flutter:         ## Run any flutter command, e.g. make flutter ARGS="pub get"
	./ops/flutter.sh flutter $(ARGS)

backup:          ## Dump the database
	./ops/backup.sh
restore-check:   ## Verify the newest dump actually restores
	./ops/restore-check.sh
