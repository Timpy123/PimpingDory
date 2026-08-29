#!/bin/bash
# Fetch the ARM cross-compiler the firmware builds with.
#
# Not in git: 976 MB of vendor binaries, and every byte of it comes back from
# one download. Version is pinned so a rebuild years from now produces the same
# binary rather than whatever ARM ships that week.
#
#   ./toolchain.sh          install if missing
#   ./toolchain.sh --force  reinstall over an existing copy
set -euo pipefail

VER="14.2.rel1"
BASE="https://developer.arm.com/-/media/Files/downloads/gnu/${VER}/binrel"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) HOST="darwin-arm64" ;;
  Darwin-x86_64) HOST="darwin-x86_64" ;;
  Linux-x86_64) HOST="x86_64" ;;
  Linux-aarch64) HOST="aarch64" ;;
  *) echo "No ARM toolchain build for $(uname -s)-$(uname -m)." >&2
     echo "Pick one by hand: https://developer.arm.com/downloads/-/arm-gnu-toolchain-downloads" >&2
     exit 1 ;;
esac

TAR="arm-gnu-toolchain-${VER}-${HOST}-arm-none-eabi.tar.xz"
DIR="src/arm-gnu-toolchain-${VER}-${HOST}-arm-none-eabi"
cd "$(dirname "$0")"

if [ -d "$DIR" ] && [ "${1:-}" != "--force" ]; then
  echo "Already present: $DIR"
  echo "  $("$DIR/bin/arm-none-eabi-gcc" --version 2>/dev/null | head -1)"
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
echo "Downloading $TAR (~1 GB unpacked) ..."
curl -fL --progress-bar -o "src/$TAR" "$BASE/$TAR"

echo "Unpacking ..."
rm -rf "$DIR"
tar xf "src/$TAR" -C src
rm -f "src/$TAR"

# macOS quarantines downloaded binaries; without this every tool prompts.
if [ "$(uname -s)" = "Darwin" ]; then
  xattr -dr com.apple.quarantine "$DIR" 2>/dev/null || true
fi

echo ""
echo "Installed: $DIR"
echo "  $("$DIR/bin/arm-none-eabi-gcc" --version | head -1)"
echo ""
echo "Add it to PATH for a build:"
echo "  export PATH=\"\$PWD/$DIR/bin:\$PATH\""
