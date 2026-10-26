#!/bin/sh
set -eu
export BIRD_GATEWAY_TOKEN="$(cat /run/secrets/gateway_token)"
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
