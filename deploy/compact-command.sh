#!/bin/sh
bird_compact() { docker compose -f compose.compact.yaml "$@"; }
bird_legacy() { docker compose -f compose.yaml -f compose.offline.yaml -f compose.curation.yaml "$@"; }
bird_rollback() {
    BIRD_ROLLBACK_DIR=$(cat config/compact.rollback-dir)
    case "$BIRD_ROLLBACK_DIR" in config/compact-backup-*) ;; *) return 1 ;; esac
    case "${BIRD_ROLLBACK_DIR#config/compact-backup-}" in ''|*[!0-9]*) return 1 ;; esac
    test -d "$BIRD_ROLLBACK_DIR"
    docker compose --project-directory "$(pwd -P)" --env-file "$BIRD_ROLLBACK_DIR/env" \
        -f "$BIRD_ROLLBACK_DIR/compose.yaml" -f "$BIRD_ROLLBACK_DIR/compose.offline.yaml" \
        -f "$BIRD_ROLLBACK_DIR/compose.curation.yaml" -f "$BIRD_ROLLBACK_DIR/rollback-images.yaml" "$@"
}
