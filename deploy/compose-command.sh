#!/bin/sh
# The marker is written only by the user-invoked enable-curation step.
bird_compose() {
    if [ -f config/compact.enabled ]; then
        docker compose -f compose.compact.yaml "$@"
        return
    fi
    if [ -f config/curation.enabled ]; then
        set -- -f compose.curation.yaml "$@"
    fi
    if [ "${BIRD_COMPOSE_ONLINE:-0}" = 1 ]; then
        docker compose -f compose.yaml "$@"
    else
        docker compose -f compose.yaml -f compose.offline.yaml "$@"
    fi
}
