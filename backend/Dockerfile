# --- base: shared runtime dependencies ---------------------------------------
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- dev: adds test/lint tooling; used locally and by `make test` -------------
FROM base AS dev
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
CMD ["pytest"]

# --- runtime: the deployed image ---------------------------------------------
FROM base AS runtime

COPY . .

# collectstatic only needs settings to import, not a database.
RUN DJANGO_SECRET_KEY=build-only POSTGRES_HOST=unused \
    python manage.py collectstatic --noinput --clear

# Created in the image so a named volume mounted here inherits this ownership.
# A volume over a path that does not exist is created root-owned, and the app
# user then cannot write its generated secret key.
RUN mkdir -p /app/state /app/media \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

EXPOSE 8000

# No automatic migrate: ops/deploy.sh runs migrations explicitly before the new
# containers come up, so a schema change can never race the app booting.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
