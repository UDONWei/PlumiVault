#!/bin/sh
# Invoke as your normal SSH user: sh deploy/with-docker-sudo.sh setup-nas
# Only Docker receives sudo; application files and id output keep the login user.
set -eu
if [ "$(id -u)" -eq 0 ]; then
    printf 'Run this wrapper as your normal SSH user, without sudo before sh.\n' >&2
    exit 1
fi
case "${1:-}" in
    check-nas|setup-nas|start-nas|start-nas-offline|upgrade-culling|upgrade-unlimited|enable-curation|verify-container|merge-containers|rollback-compact|verify-compact) BIRD_DEPLOY_STEP=$1 ;;
    *) printf 'Usage: sh deploy/with-docker-sudo.sh {check-nas|setup-nas|start-nas|start-nas-offline|upgrade-culling|upgrade-unlimited|enable-curation|verify-container|merge-containers|rollback-compact|verify-compact}\n' >&2; exit 1 ;;
esac
test -f "deploy/$BIRD_DEPLOY_STEP.sh"
command sudo -v
docker() { command sudo -- docker "$@"; }
# Source into this shell to retain the Docker-only wrapper function.
. "./deploy/$BIRD_DEPLOY_STEP.sh"
