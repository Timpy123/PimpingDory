#!/bin/bash
# Full project backup: kicad/ (minus generated backup dirs and caches) plus
# CLAUDE.md, as a timestamped tarball in the repo scratch folder ../tmp/backups.
# Scratch is ALWAYS <repo>/tmp — never /tmp or /private/tmp.
# Run from anywhere: kicad/tools/backup.sh
set -euo pipefail
cd "$(dirname "$0")/../.."          # -> MetalDetector/

OUT="../tmp/backups"                # -> PimpingDory/tmp/backups
TS=$(date +%Y-%m-%d_%H%M%S)
mkdir -p "$OUT"
tar --exclude='kicad/backups' --exclude='kicad/detector-hat-backups' \
    --exclude='kicad/tools/__pycache__' --exclude='kicad/.DS_Store' \
    -czf "$OUT/kicad-full-${TS}.tar.gz" kicad CLAUDE.md
ls -la "$OUT/kicad-full-${TS}.tar.gz"
