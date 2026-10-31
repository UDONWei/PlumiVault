#!/bin/sh
set -eu
. ./deploy/compact-command.sh
test -s config/compact.rollback-dir
mkdir config/.compact-operation-lock
trap 'rmdir config/.compact-operation-lock' EXIT
if [ -n "$(bird_compact ps -q app)" ]; then
    bird_compact exec -T app python -B /app/tools/compact_preflight.py --backup
fi
bird_compact stop -t 45 app
bird_compact rm -f app
bird_rollback up -d --no-build --pull never --wait --wait-timeout 120 index organizer gateway
if [ -f config/compact.enabled ]; then rm config/compact.enabled; fi
bird_rollback ps
printf 'Restored original services using saved images/config. Kept current database, photos and Tailscale.\n'
