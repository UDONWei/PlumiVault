#!/bin/sh
# Explicit user opt-in: unlimited selected-folder jobs, original mount remains read-only.
# Source through with-docker-sudo.sh; only Docker is elevated.
set -eu
test -f .env
test -f config/config.json
docker compose -f compose.yaml -f compose.offline.yaml config --quiet
BIRD_UNLIMITED_CONTAINER=$(docker compose -f compose.yaml -f compose.offline.yaml ps -q index)
test -n "$BIRD_UNLIMITED_CONTAINER"
test "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/photos"}}{{.RW}}{{end}}{{end}}' "$BIRD_UNLIMITED_CONTAINER")" = false
docker compose -f compose.yaml -f compose.offline.yaml exec -T index python -B -c '
import json
from bird_index.db import Database
c=json.load(open("/config/config.json"))
assert c.get("require_folder_selection") is True,"Keep explicit folder selection"
db=Database(c["data_dir"])
assert not db.query("SELECT id FROM jobs WHERE state IN (\x27queued\x27,\x27discovering\x27,\x27running\x27,\x27paused\x27)"),"Finish or cancel pending jobs before upgrade"
assert not db.query("SELECT 1 FROM job_items WHERE state=\x27running\x27 LIMIT 1"),"Wait until the current photo finishes, including cancelled jobs"
print("Database backup:",db.backup())
print("No job or scan started")'
BIRD_UNLIMITED_BACKUP_TAG="bird-index-nas:before-unlimited-$(date +%Y%m%d%H%M%S)"
docker tag bird-index-nas:0.3.0 "$BIRD_UNLIMITED_BACKUP_TAG"
printf 'Previous image preserved as %s\n' "$BIRD_UNLIMITED_BACKUP_TAG"
# Build before changing settings so a failed build leaves the current limit intact.
docker compose -f compose.yaml -f compose.offline.yaml build index
# This one-shot helper mounts only config, never photos or model/data directories.
docker run --rm --pull=never --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=$(pwd -P)/config,target=/settings" \
    --entrypoint python bird-index-nas:0.3.0 -B /app/tools/enable_unlimited_scan.py /settings/config.json
docker compose -f compose.yaml -f compose.offline.yaml up -d --no-build --pull never --force-recreate --no-deps index
docker compose -f compose.yaml -f compose.offline.yaml ps
printf 'Selected-folder job limit is now unlimited (0). Photos remain read-only.\n'
printf 'No scan or original move started. Organizer is NOT enabled.\n'
