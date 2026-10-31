#!/bin/sh
set -eu
. ./deploy/compact-command.sh
bird_compact ps
BIRD_COMPACT_ID=$(bird_compact ps -q app)
test -n "$BIRD_COMPACT_ID"
test "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/photos"}}{{.RW}}{{end}}{{end}}' "$BIRD_COMPACT_ID")" = false
docker inspect --format 'Health={{.State.Health.Status}} ReadonlyRootfs={{.HostConfig.ReadonlyRootfs}} Memory={{.HostConfig.Memory}} Mounts={{json .Mounts}}' "$BIRD_COMPACT_ID"
bird_compact exec -T app python -B -m bird_index.compact --health
bird_compact exec -T app python -B -c 'import json,sqlite3; from pathlib import Path; c=sqlite3.connect("file:/data/index.sqlite3?mode=ro",uri=True); print("photos",c.execute("SELECT count(*) FROM photos").fetchone()[0]); print("jobs",c.execute("SELECT count(*) FROM jobs").fetchone()[0]); c.close(); [print(json.loads(p.read_text())) for p in Path("/tmp").glob("compact-*.json")]'
printf 'Index writes restricted by Landlock; /photos mounted read-only. No scan or original move started.\n'
