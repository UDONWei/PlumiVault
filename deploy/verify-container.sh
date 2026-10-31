#!/bin/sh
# No writes to the real photo tree. Reports configured mount/resource boundaries.
set -eu
if [ -f config/compact.enabled ]; then
    . ./deploy/verify-compact.sh
    exit 0
fi
. ./deploy/compose-command.sh
bird_compose ps
CONTAINER=$(bird_compose ps -q index)
test -n "$CONTAINER"
docker inspect --format 'Mounts: {{json .Mounts}} Memory: {{.HostConfig.Memory}} ReadonlyRootfs: {{.HostConfig.ReadonlyRootfs}}' "$CONTAINER"
bird_compose exec -T index python -c 'import json,urllib.request; print(json.load(urllib.request.urlopen("http://127.0.0.1:8765/health")))'
bird_compose exec -T index python -c 'import sqlite3; c=sqlite3.connect("file:/data/index.sqlite3?mode=ro",uri=True); print("photos",c.execute("select count(*) from photos").fetchone()[0]); print("jobs",c.execute("select count(*) from jobs").fetchone()[0]); c.close()'
bird_compose exec -T index python -c 'import json; c=json.load(open("/config/config.json")); print("ScanLimit:", "unlimited" if c["max_files_per_job"]==0 else c["max_files_per_job"]); print("RequireFolderSelection:", c.get("require_folder_selection") is True)'
if [ -f config/curation.enabled ]; then
    BIRD_ORGANIZER_CONTAINER=$(bird_compose ps -q organizer)
    test -n "$BIRD_ORGANIZER_CONTAINER"
    docker inspect --format 'Organizer: {{.State.Status}} Mounts: {{json .Mounts}}' "$BIRD_ORGANIZER_CONTAINER"
    bird_compose exec -T index python -B -c 'from bird_index.organizer_client import call; r=call("status",{}); print("Organizer:",r); assert r["enabled"] is True and r["scope"]=="indexed_root"'
fi
printf 'No photo-write probe, automatic scan or original move was performed by this check.\n'
