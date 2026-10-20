#!/bin/sh
set -eu
# Railway mounts volumes as root. Only bootstrap runs as root; app drops privileges.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/data/uploads /app/data/ops/backups /app/data/ops/monitor
    chown supportapp:supportapp /app/data /app/data/uploads /app/data/ops /app/data/ops/backups /app/data/ops/monitor
    exec gosu supportapp "$@"
fi
exec "$@"
