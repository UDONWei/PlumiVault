#!/bin/sh
# Read-only diagnostics. No image scan, chmod, or trial writes to photos.
set -eu
printf 'Architecture: '; uname -m
id
docker version --format 'Docker server: {{.Server.Version}}'
docker compose version
free -m
df -h /volume1
test -d '/volume1/照片/未处理'
printf 'Photo entry exists. Directory contents and image bytes were not scanned.\n'
