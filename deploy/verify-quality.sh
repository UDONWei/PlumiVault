#!/bin/sh
set -eu
. ./deploy/compose-command.sh
if [ -f config/compact.enabled ]; then BIRD_QUALITY_SERVICE=app; else BIRD_QUALITY_SERVICE=index; fi
bird_compose exec -T "$BIRD_QUALITY_SERVICE" python -B /app/tools/verify_quality_runtime.py
