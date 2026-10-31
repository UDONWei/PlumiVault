#!/bin/sh
# Source through with-docker-sudo.sh so id/file ownership stay with the invoking SSH user.
set -eu
test ! -f config/compact.enabled || { printf 'Already merged; use upgrade-culling and verify-container.\n' >&2; exit 1; }
. ./deploy/compose-command.sh
BIRD_COMPOSE_ONLINE=0
test -f .env
test -s config/gateway-token
test -f offline-build/manifest.json
BIRD_BASE_ID=$(docker image inspect python:3.12.14-slim-bookworm --format '{{.Id}}')
if [ "$BIRD_BASE_ID" != 'sha256:febd0be41adb897a0ab8f1f1c693d8912669ea60c4940e076e9946b60e210ef0' ]; then
    printf 'Unexpected Python base image; load the verified offline Python tar first.\n' >&2
    exit 1
fi
docker image inspect caddy:2.11.7-alpine --format '{{.Id}}'
docker run --rm --pull=never --network none --read-only --user "$(id -u):$(id -g)" \
    --mount "type=bind,source=$(pwd -P),target=/workspace,readonly" --workdir /workspace \
    python:3.12.14-slim-bookworm python -B tools/verify_offline_dependencies.py offline-build --config config/config.json
bird_compose config --quiet
bird_compose build index
bird_compose run --rm --no-deps --pull never index python -c '
from pathlib import Path
import json,hashlib
p=Path("/models")
for name in ("model.json","detector-ssdlite.json"):
    c=json.loads((p/name).read_text())
    w=(p/c["weights"]).resolve(strict=True)
    if not w.is_relative_to(p): raise SystemExit("Model path outside /models")
    h=hashlib.sha256()
    with w.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    if h.hexdigest()!=c["sha256"]:raise SystemExit("Model hash mismatch: "+name)
    print(name+": SHA-256 verified")'
bird_compose up -d --no-build --pull never
bird_compose ps
printf '\nStarted without scanning. Choose a folder in the web UI; a job limit of 0 means no photo-count limit.\n'
