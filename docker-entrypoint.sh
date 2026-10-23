#!/bin/sh
set -e

# Compose holds this container until Postgres passes its healthcheck, so the
# database is reachable by the time migrations run.
#
# Applying them on boot suits a single instance. Several replicas starting at
# once would race, so set MIGRATE_ON_START=0 there and run `manage.py migrate`
# as a release step instead.
if [ "${MIGRATE_ON_START:-1}" = "1" ]; then
    python manage.py migrate --noinput
fi

exec "$@"
