#!/bin/sh
# Run interactively inside a dedicated application directory. Never edits photos.
set -eu
if [ "$(id -u)" -eq 0 ]; then
    printf 'Run as the normal SSH user. For Docker permission errors use deploy/with-docker-sudo.sh.\n' >&2
    exit 1
fi
APP_DIR=$(pwd -P)
case "$APP_DIR" in /volume1/照片|/volume1/照片/*) printf 'Do not install inside photos.\n' >&2; exit 1;; esac
test -f compose.yaml
test -f models/model.json
test -f models/detector-ssdlite.json
test -f models/text_features.pt
test -d '/volume1/照片/未处理'
docker compose version
umask 077
mkdir -p data config gateway-data gateway-config
# Preserve existing configuration on retry or upgrade.
if [ ! -f config/config.json ]; then cp deploy/config.nas.example.json config/config.json; fi
if [ ! -f .env ]; then
    docker pull caddy:2.11.7-alpine
    printf 'Set web password for user bird (input hidden): ' > /dev/tty
    BIRD_TTY_MODE=$(stty -g < /dev/tty)
    trap 'stty "$BIRD_TTY_MODE" < /dev/tty' EXIT HUP INT TERM
    stty -echo < /dev/tty
    IFS= read -r BIRD_PASSWORD < /dev/tty
    printf '\nRepeat password: ' > /dev/tty
    IFS= read -r BIRD_REPEAT < /dev/tty
    stty "$BIRD_TTY_MODE" < /dev/tty
    trap - EXIT HUP INT TERM
    printf '\n' > /dev/tty
    if [ -z "$BIRD_PASSWORD" ] || [ "$BIRD_PASSWORD" != "$BIRD_REPEAT" ]; then
        printf 'Empty or different passwords. Run this script again.\n' >&2; exit 1
    fi
    # Caddy 2.11.7 requires newline-terminated stdin (ReadBytes('\n')).
    # Shell builtin printf sends plaintext only through stdin, never process arguments.
    BIRD_HASH=$(printf '%s\n' "$BIRD_PASSWORD" | docker run --rm -i caddy:2.11.7-alpine caddy hash-password --algorithm bcrypt)
    unset BIRD_PASSWORD BIRD_REPEAT
    case "$BIRD_HASH" in \$2*) ;; *) printf 'Password hashing failed.\n' >&2; exit 1;; esac
    printf 'BIRD_UID=%s\nBIRD_GID=%s\nBIRD_BIND_IP=192.0.2.10\nBIRD_PHOTOS_PATH=/volume1/照片/未处理\nBIRD_AUTH_HASH=\047%s\047\n' "$(id -u)" "$(id -g)" "$BIRD_HASH" > .env.pending
    mv .env.pending .env
fi
if [ ! -s config/gateway-token ]; then
    docker run --rm --entrypoint python python:3.12.14-slim-bookworm -c 'import secrets;print(secrets.token_hex(32))' > config/gateway-token.pending
    test "$(wc -c < config/gateway-token.pending)" -ge 32
    mv config/gateway-token.pending config/gateway-token
fi
chmod 600 .env config/gateway-token
docker compose config --quiet
printf '\nConfiguration prepared. Existing settings preserved. No service or scan started.\n'
printf 'Edit BIRD_BIND_IP in .env to your NAS LAN IP before starting. Then: sh deploy/start-nas.sh\n'
