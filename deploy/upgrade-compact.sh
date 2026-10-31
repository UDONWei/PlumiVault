#!/bin/sh
# Called by upgrade-culling after an explicit merge. No extra persistent containers.
set -eu
. ./deploy/compact-command.sh
mkdir config/.compact-operation-lock
BIRD_UPGRADE_STOPPED=0
BIRD_COMPACT_OLD_IMAGE=''
bird_upgrade_exit() {
    BIRD_COMPACT_EXIT=$?
    trap - EXIT HUP INT TERM
    if [ "$BIRD_UPGRADE_STOPPED" = 1 ]; then
        printf 'Compact update failed; restoring previous app image.\n' >&2
        bird_compact stop -t 45 app || true
        docker tag "$BIRD_COMPACT_OLD_IMAGE" plumivault:compact-r12
        bird_compact up -d --no-build --pull never --wait --wait-timeout 150 app || printf 'Rollback needs attention.\n' >&2
    fi
    rmdir config/.compact-operation-lock || true
    exit "$BIRD_COMPACT_EXIT"
}
trap bird_upgrade_exit EXIT
trap 'exit 130' HUP INT TERM
bird_compact exec -T app python -B /app/tools/compact_preflight.py --backup
BIRD_COMPACT_OLD_IMAGE=$(docker inspect --format '{{.Image}}' "$(bird_compact ps -q app)")
docker tag "$BIRD_COMPACT_OLD_IMAGE" "plumivault:before-compact-update-$(date +%Y%m%d%H%M%S)"
bird_compact build app
# Repeat after build so newly queued work is not silently interrupted.
bird_compact exec -T app python -B /app/tools/compact_preflight.py
BIRD_UPGRADE_STOPPED=1
bird_compact stop -t 45 app
bird_compact up -d --no-build --pull never --wait --wait-timeout 150 app
bird_compact exec -T app python -B -m bird_index.compact --health
BIRD_UPGRADE_STOPPED=0
printf 'Compact services updated; no scan or move started.\n'
