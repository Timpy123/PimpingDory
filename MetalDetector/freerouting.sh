#!/bin/bash
# Fetch Freerouting — the autorouter used on the HAT layout.
#
# Not in git: a 137 MB app bundle plus its 80 MB .dmg, and it is a released
# third-party binary that anyone can download. Version pinned so a rerun
# routes the same way.
#
#   ./freerouting.sh          install if missing
#   ./freerouting.sh --force  reinstall
set -euo pipefail

VER="2.2.4"
REPO="https://github.com/freerouting/freerouting/releases/download/v${VER}"
cd "$(dirname "$0")"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)  ASSET="freerouting-${VER}-macos-arm64.dmg";  KIND="dmg" ;;
  Darwin-x86_64) ASSET="freerouting-${VER}-macos-x64.dmg";    KIND="dmg" ;;
  Linux-*)       ASSET="freerouting-${VER}-linux-x64.AppImage"; KIND="appimage" ;;
  *) echo "No Freerouting build for $(uname -s)-$(uname -m)." >&2
     echo "Releases: https://github.com/freerouting/freerouting/releases" >&2
     exit 1 ;;
esac

if [ -d "src/Freerouting.app" ] && [ "${1:-}" != "--force" ]; then
  echo "Already present: src/Freerouting.app"
  if [ -t 0 ]; then
    printf "Download again and replace it? [y/N] "
    read -r ans
    case "$ans" in [yY]*) ;; *) echo "Keeping it."; exit 0 ;; esac
  else
    echo "Use --force to reinstall."
    exit 0
  fi
fi

mkdir -p src
echo "Downloading $ASSET ..."
curl -fL --progress-bar -o "src/$ASSET" "$REPO/$ASSET"

if [ "$KIND" = "dmg" ]; then
  echo "Mounting ..."
  MNT=$(hdiutil attach -nobrowse -readonly "src/$ASSET" | awk -F'\t' '/Volumes/{print $NF}' | tail -1)
  if [ -z "$MNT" ]; then echo "Could not mount $ASSET" >&2; exit 1; fi
  rm -rf src/Freerouting.app
  cp -R "$MNT"/*.app src/Freerouting.app
  hdiutil detach "$MNT" >/dev/null
  rm -f "src/$ASSET"
  xattr -dr com.apple.quarantine src/Freerouting.app 2>/dev/null || true
  echo ""
  echo "Installed: src/Freerouting.app"
  echo "Run:  open src/Freerouting.app"
else
  chmod +x "src/$ASSET"
  echo ""
  echo "Installed: src/$ASSET"
  echo "Run:  ./src/$ASSET"
fi
