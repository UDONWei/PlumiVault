#!/bin/sh
# User-requested opt-in. No real photo is moved or used for a write probe.
set -eu
test ! -f config/compact.enabled || { printf 'Already merged with organizer; use verify-container.\n' >&2; exit 1; }
. ./deploy/compose-command.sh
test -f .env
test -f config/config.json
BIRD_ENABLE_INDEX=$(bird_compose ps -q index)
test -n "$BIRD_ENABLE_INDEX"
test "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/photos"}}{{.Source}}{{end}}{{end}}' "$BIRD_ENABLE_INDEX")" = '/volume1/照片/未处理'
test "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/photos"}}{{.RW}}{{end}}{{end}}' "$BIRD_ENABLE_INDEX")" = false
bird_compose exec -T index python -B -c '
from bird_index.db import Database
db=Database("/data")
assert not db.query("SELECT id FROM jobs WHERE state IN (\x27queued\x27,\x27discovering\x27,\x27running\x27,\x27paused\x27)"),"Finish pending scans before enabling organizer"
assert not db.query("SELECT 1 FROM job_items WHERE state=\x27running\x27"),"Wait for the current photo to finish"
assert not db.query("SELECT 1 FROM file_plans WHERE state=\x27executing\x27"),"Recover unfinished moves first"
print("Database backup:",db.backup())'
docker run --rm --pull=never --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=$(pwd -P),target=/deployment" \
    --mount 'type=bind,source=/volume1/照片,target=/library' \
    --entrypoint python bird-index-nas:0.3.0 -B /app/tools/enable_daily_curation.py --host-parent '/volume1/照片'
bird_compose config --quiet
bird_compose up -d --no-build --no-deps --pull never --wait --wait-timeout 120 index organizer
printf 'Organizer enabled for explicitly confirmed indexed photos. Index /photos stays read-only. No original moved.\n'
