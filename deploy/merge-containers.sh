#!/bin/sh
# Explicit migration: three app services -> one. Tailscale and photo data stay in place.
set -eu
umask 077
. ./deploy/compact-command.sh
test ! -f config/compact.enabled || { printf 'Already merged; use upgrade-culling.\n' >&2; exit 1; }
test -f config/curation.enabled
test -s config/curation.json
mkdir config/.compact-operation-lock || { printf 'Another migration is active; inspect before retrying.\n' >&2; exit 1; }
BIRD_SWITCHING=0
bird_merge_exit() {
    BIRD_MERGE_EXIT=$?
    trap - EXIT HUP INT TERM
    if [ "$BIRD_SWITCHING" = 1 ]; then
        printf 'Merge did not finish; restoring the three original services.\n' >&2
        bird_compact stop -t 45 app || true
        bird_compact rm -f app || true
        if bird_rollback up -d --no-build --pull never --wait --wait-timeout 120 index organizer gateway; then
            rm -f config/compact.enabled
            printf 'Previous services restored. Data and Tailscale unchanged.\n' >&2
        else
            printf 'Automatic rollback needs attention: sh deploy/with-docker-sudo.sh rollback-compact\n' >&2
        fi
    fi
    rmdir config/.compact-operation-lock || true
    exit "$BIRD_MERGE_EXIT"
}
trap bird_merge_exit EXIT
trap 'exit 130' HUP INT TERM
bird_legacy config --quiet
bird_compact config --quiet
BIRD_OLD_INDEX=$(bird_legacy ps -q index)
BIRD_OLD_GATEWAY=$(bird_legacy ps -q gateway)
BIRD_OLD_ORGANIZER=$(bird_legacy ps -q organizer)
test -n "$BIRD_OLD_INDEX" && test -n "$BIRD_OLD_GATEWAY" && test -n "$BIRD_OLD_ORGANIZER"
test -z "$(bird_compact ps -aq app)" || { printf 'An app container already exists; inspect it before retrying.\n' >&2; exit 1; }
test "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/photos"}}{{.RW}}{{end}}{{end}}' "$BIRD_OLD_INDEX")" = false
# Check the proposed mounts against the containers actually in use. Do not print credentials.
BIRD_EXPECT_PHOTOS=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/photos"}}{{.Source}}{{end}}{{end}}' "$BIRD_OLD_INDEX")
BIRD_EXPECT_LIBRARY=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/library"}}{{.Source}}{{end}}{{end}}' "$BIRD_OLD_ORGANIZER")
for BIRD_MOUNT in data config models; do
    BIRD_ACTUAL=$(docker inspect --format "{{range .Mounts}}{{if eq .Destination \"/$BIRD_MOUNT\"}}{{.Source}}{{end}}{{end}}" "$BIRD_OLD_INDEX")
    test "$BIRD_ACTUAL" = "$(pwd -P)/$BIRD_MOUNT" || { printf 'Unexpected legacy mount: %s\n' "$BIRD_MOUNT" >&2; exit 1; }
done
for BIRD_MOUNT in data config; do
    BIRD_ACTUAL=$(docker inspect --format "{{range .Mounts}}{{if eq .Destination \"/$BIRD_MOUNT\"}}{{.Source}}{{end}}{{end}}" "$BIRD_OLD_GATEWAY")
    test "$BIRD_ACTUAL" = "$(pwd -P)/gateway-$BIRD_MOUNT" || { printf 'Unexpected legacy gateway mount.\n' >&2; exit 1; }
done
bird_compact config --format json | docker exec -i "$BIRD_OLD_INDEX" python -B -c '
import json,sys
v={m["target"]:m for m in json.load(sys.stdin)["services"]["app"]["volumes"]}
assert v["/photos"]["source"]==sys.argv[1] and v["/photos"].get("read_only") is True
assert v["/library"]["source"]==sys.argv[2]
for target,folder in [("/data","data"),("/config","config"),("/models","models"),("/gateway-data","gateway-data"),("/gateway-config","gateway-config")]:
 assert v[target]["source"]==sys.argv[3]+"/"+folder, "Unexpected mount "+target
print("Compact mount mapping checked")' "$BIRD_EXPECT_PHOTOS" "$BIRD_EXPECT_LIBRARY" "$(pwd -P)"
docker exec -i "$BIRD_OLD_INDEX" python -B - --probe < bird_index/compact_sandbox.py
docker exec -i "$BIRD_OLD_INDEX" python -B - < tools/compact_preflight.py
# Preserve the deployed HTTPS/auth configuration; only its internal upstream changes.
test "$(grep -c 'reverse_proxy index:8765' deploy/gateway/Caddyfile)" = 1 || { printf 'Custom gateway upstream requires review before merging.\n' >&2; exit 1; }
sed 's/reverse_proxy index:8765/reverse_proxy 127.0.0.1:8765/' deploy/gateway/Caddyfile > config/compact.Caddyfile
# Build only: no temporary helper container or package downloads needed.
docker image inspect bird-index-nas:0.3.0 caddy:2.11.7-alpine > /dev/null
bird_compact build app
BIRD_COMPACT_STAMP=$(date +%Y%m%d%H%M%S)
BIRD_COMPACT_BACKUP="config/compact-backup-$BIRD_COMPACT_STAMP"
mkdir "$BIRD_COMPACT_BACKUP"
cp .env "$BIRD_COMPACT_BACKUP/env"
cp compose.yaml compose.offline.yaml compose.curation.yaml "$BIRD_COMPACT_BACKUP/"
cp deploy/gateway/Caddyfile "$BIRD_COMPACT_BACKUP/gateway.Caddyfile"
for BIRD_ROLE in index organizer gateway; do
    BIRD_ROLE_ID=$(bird_legacy ps -q "$BIRD_ROLE")
    BIRD_ROLE_IMAGE=$(docker inspect --format '{{.Image}}' "$BIRD_ROLE_ID")
    docker tag "$BIRD_ROLE_IMAGE" "plumivault:legacy-$BIRD_ROLE-$BIRD_COMPACT_STAMP"
done
printf 'services:\n  index:\n    image: plumivault:legacy-index-%s\n  organizer:\n    image: plumivault:legacy-organizer-%s\n  gateway:\n    image: plumivault:legacy-gateway-%s\n' "$BIRD_COMPACT_STAMP" "$BIRD_COMPACT_STAMP" "$BIRD_COMPACT_STAMP" > "$BIRD_COMPACT_BACKUP/rollback-images.yaml"
printf '%s\n' "$BIRD_COMPACT_BACKUP" > config/compact.rollback-dir
# Close the entry point before the final idle check; a failed check restores it.
BIRD_SWITCHING=1
bird_legacy stop -t 30 gateway
docker exec -i "$BIRD_OLD_INDEX" python -B - --backup < tools/compact_preflight.py
bird_legacy stop -t 45 index organizer
# Removes only stopped container objects, never mounts, volumes or images.
bird_legacy rm -f index organizer gateway
bird_compact up -d --no-build --pull never --wait --wait-timeout 150 app
bird_compact exec -T app python -B -m bird_index.compact --health
printf 'compact-v1\n' > config/compact.enabled
BIRD_SWITCHING=0
bird_compact ps
printf 'Merged application services. Tailscale unchanged. No scan or original move started.\n'
