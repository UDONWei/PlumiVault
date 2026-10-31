#!/bin/sh
set -eu
test ! -f config/compact.enabled || { printf 'Already merged; use upgrade-culling and verify-container.\n' >&2; exit 1; }
. ./deploy/compose-command.sh
BIRD_COMPOSE_ONLINE=1
test -f .env
test -s config/gateway-token
bird_compose config --quiet
bird_compose build
bird_compose run --rm --no-deps index python -c '
from pathlib import Path
import json, hashlib
p=Path("/models")
for name in ("model.json", "detector-ssdlite.json"):
    c=json.loads((p/name).read_text())
    w=(p/c["weights"]).resolve(strict=True)
    if not w.is_relative_to(p): raise SystemExit("Model path outside /models")
    h=hashlib.sha256()
    with w.open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""): h.update(b)
    if h.hexdigest()!=c["sha256"]: raise SystemExit("Model hash mismatch: "+name)
    print(name+": SHA-256 verified")'
bird_compose up -d
bird_compose ps
printf '\nStarted without any scan. HTTPS: use BIRD_BIND_IP from .env on port 8443 ; user: bird\n'
printf 'Certificate trust and small-folder validation: docs/NAS_DEPLOYMENT.md\n'
