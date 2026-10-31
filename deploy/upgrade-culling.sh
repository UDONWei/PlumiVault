#!/bin/sh
# Called through with-docker-sudo.sh; does not enable organizer or create scans.
set -eu
if [ -f config/compact.enabled ]; then
    . ./deploy/upgrade-compact.sh
    exit 0
fi
. ./deploy/compose-command.sh
test -f .env
test -f config/config.json
bird_compose config --quiet
BIRD_CULLING_CONTAINER=$(bird_compose ps -q index)
test -n "$BIRD_CULLING_CONTAINER"
BIRD_CULLING_PHOTOS_RW=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/photos"}}{{.RW}}{{end}}{{end}}' "$BIRD_CULLING_CONTAINER")
test "$BIRD_CULLING_PHOTOS_RW" = false || { printf 'Refusing upgrade: /photos must be read-only.\n' >&2; exit 1; }
bird_compose exec -T index python -c '
import json,sqlite3
from bird_index.db import Database
c=json.load(open("/config/config.json"))
assert type(c.get("max_files_per_job")) is int and c["max_files_per_job"]>=0 and c.get("require_folder_selection") is True,"Keep valid job limit and explicit folder selection"
db=Database(c["data_dir"])
assert not db.query("SELECT id FROM jobs WHERE state IN (\x27queued\x27,\x27discovering\x27,\x27running\x27,\x27paused\x27)"),"Finish or cancel pending jobs before upgrade"
assert not db.query("SELECT job_id FROM job_items WHERE state=\x27running\x27"),"Wait for the current photo to finish before upgrade"
assert not db.query("SELECT id FROM file_plans WHERE state=\x27executing\x27"),"Recover unfinished original moves before upgrading"
print("Backup:",db.backup())
print("No job or scan started")'
BIRD_CULLING_BACKUP_TAG="bird-index-nas:before-culling-$(date +%Y%m%d%H%M%S)"
docker tag bird-index-nas:0.3.0 "$BIRD_CULLING_BACKUP_TAG"
printf 'Previous image preserved as %s\n' "$BIRD_CULLING_BACKUP_TAG"
bird_compose build index
if [ -f config/curation.enabled ]; then
    bird_compose up -d --no-build --no-deps --pull never --wait --wait-timeout 120 index organizer
else
    bird_compose up -d --no-build --no-deps --pull never --wait --wait-timeout 120 index
fi
bird_compose ps
printf 'Updated services; existing organizer enablement preserved. No scan or original move started.\n'
