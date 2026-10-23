# syntax=docker/dockerfile:1

# One file, two targets: `development` carries only the environment and expects
# the source to be mounted over it, `production` bakes the source in and serves
# it with daphne. Both share the dependency layer below, so the image you run
# locally is built on exactly what ships.

# --- base -------------------------------------------------------------------
# The interpreter plus the environment variables that make Python behave in a
# container: no .pyc files to write, and logs that are not held in a buffer the
# orchestrator never sees.
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app


# --- builder ----------------------------------------------------------------
# Dependencies get their own stage so editing a source file does not reinstall
# them. Every requirement ships a wheel for this platform, so no compiler and
# no -dev headers are needed; installing into a virtualenv is what lets the
# result be copied forward as a single directory.
FROM base AS builder

COPY requirements.txt .

RUN python -m venv /opt/venv \
    && pip install --no-cache-dir -r requirements.txt


# --- development ------------------------------------------------------------
# No source is copied: compose mounts the working tree over /app, so edits take
# effect without a rebuild and runserver reloads on them. It speaks ASGI here
# the same as anywhere else, because daphne precedes staticfiles in
# INSTALLED_APPS, so the chat socket works too.
FROM base AS development

COPY --from=builder /opt/venv /opt/venv

# Lives outside /app so the entrypoint still exists when the bind mount hides
# the directory it was copied into.
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV DJANGO_SETTINGS_MODULE=config.settings.dev

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


# --- production -------------------------------------------------------------
FROM base AS production

COPY --from=builder /opt/venv /opt/venv

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 1000 app

COPY --chown=app:app . .

ENV DJANGO_SETTINGS_MODULE=config.settings.prod

# uploads/ is written to when LocalFileSystemStorage is configured, and is
# container-local: mount a volume over it, or use the Cloudinary backend.
RUN mkdir -p /app/uploads /app/staticfiles \
    && chown app:app /app/uploads /app/staticfiles

USER app

# The defaults in config/settings/base.py are enough to collect static without
# a database, a secret, or any network.
RUN python manage.py collectstatic --noinput

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
