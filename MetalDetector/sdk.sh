#!/bin/bash
# Fetch the Pico SDK the firmware builds against.
#
# Deliberately NOT a git submodule. Two reasons:
#
#   - MetalDetector/ is not its own repository; it is a folder inside
#     PimpingDory. A submodule here would belong to the PimpingDory repo and
#     bind that repo's history to a 37 MB upstream checkout it has no use for.
#   - picotool cannot be a submodule at all: cmake fetches it at first
#     configure into src/picotool/{picotool-src,picotool-build,...}, three
#     quarters of which is build state, not a checkout. Nothing to submodule.
#
# So both are fetched by script, pinned to a tag, which is what a submodule
# would have given us without entangling the parent repo.
#
#   ./sdk.sh          clone if missing
#   ./sdk.sh --force  re-clone
set -euo pipefail

VER="2.3.0"
cd "$(dirname "$0")"

if [ -d src/pico-sdk/.git ] && [ "${1:-}" != "--force" ]; then
  echo "Already present: src/pico-sdk ($(git -C src/pico-sdk describe --tags 2>/dev/null || echo unknown))"
  if [ -t 0 ]; then
    printf "Delete it and clone again? [y/N] "
    read -r ans
    case "$ans" in [yY]*) ;; *) echo "Keeping it."; exit 0 ;; esac
  else
    echo "Use --force to re-clone."
    exit 0
  fi
fi

mkdir -p src
rm -rf src/pico-sdk
echo "Cloning pico-sdk $VER ..."
git clone --depth 1 --branch "$VER" https://github.com/raspberrypi/pico-sdk.git src/pico-sdk

# Submodules stay uninitialised: they are only needed for USB stdio, which the
# firmware does not use. That is ~200 MB not downloaded.
echo ""
echo "Installed: src/pico-sdk ($(git -C src/pico-sdk describe --tags))"
echo "Submodules left uninitialised on purpose (USB stdio is off)."
echo ""
echo "picotool is fetched automatically by cmake on the first configure,"
echo "into src/picotool/. Nothing to do for it here."
