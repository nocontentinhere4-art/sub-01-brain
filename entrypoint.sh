#!/bin/sh
# Container entrypoint (#18): the server and its Chromium run as uid 1000 (user sub01), so Chromium keeps its own
# sandbox. Started as root (the default; Railway mounts the /data volume root-owned): give /data to uid 1000, then
# drop privileges for good and run the CMD. Started as uid 1000 already (docker run --user 1000): run the CMD as is.
# RUN_AS_ROOT=1 is the rollback switch: everything stays root as before #18 (Chromium then runs with --no-sandbox).
set -e
DATA_DIR="${SUB01_DATA_DIR:-/data}"
APP_UID=1000
APP_GID=1000

if [ "$(id -u)" = "0" ]; then
    if [ "${RUN_AS_ROOT:-0}" = "1" ]; then
        echo "entrypoint: RUN_AS_ROOT=1, staying root (Chromium sandbox off)" >&2
        exec "$@"
    fi
    mkdir -p "$DATA_DIR"
    # chown only when something is not ours yet: the first start hands the whole volume over, later starts change nothing
    if [ -n "$(find "$DATA_DIR" -xdev \( ! -uid "$APP_UID" -o ! -gid "$APP_GID" \) -print -quit)" ]; then
        echo "entrypoint: chown -R $APP_UID:$APP_GID $DATA_DIR" >&2
        chown -R "$APP_UID:$APP_GID" "$DATA_DIR"
    fi
    export HOME=/home/sub01 USER=sub01 LOGNAME=sub01
    exec setpriv --reuid="$APP_UID" --regid="$APP_GID" --clear-groups --inh-caps=-all --bounding-set=-all -- "$@"
fi

if [ -d "$DATA_DIR" ] && ! [ -w "$DATA_DIR" ]; then
    echo "entrypoint: !!! $DATA_DIR is not writable by uid $(id -u); start the container as root (on Railway:" \
         "RAILWAY_RUN_UID=0) so it can be handed to uid $APP_UID" >&2
fi
exec "$@"
