#!/bin/bash
# Build the detector firmware. macOS and Linux.
#
# Everything the build needs is fetched by the three setup scripts beside this
# one; run them first, or run this and it will tell you which is missing.
#
#   ./build.sh              build (configure if needed)
#   ./build.sh --clean      throw the build directory away first
#   ./build.sh --debug      -DCMAKE_BUILD_TYPE=Debug instead of Release
#
# Output: src/detector-firmware/build/detector-firmware.uf2
set -euo pipefail
cd "$(dirname "$0")"

VER="14.2.rel1"
FW="src/detector-firmware"
CLEAN=0
BUILD_TYPE="Release"
for a in "$@"; do
  case "$a" in
    --clean) CLEAN=1 ;;
    --debug) BUILD_TYPE="Debug" ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

# --- the toolchain, whichever host this is ----------------------------------
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)  HOST="darwin-arm64" ;;
  Darwin-x86_64) HOST="darwin-x86_64" ;;
  Linux-x86_64)  HOST="x86_64" ;;
  Linux-aarch64) HOST="aarch64" ;;
  *) echo "Unsupported host $(uname -s)-$(uname -m)." >&2; exit 1 ;;
esac
TC="src/arm-gnu-toolchain-${VER}-${HOST}-arm-none-eabi"

missing=0
say_missing() { echo "  MISSING  $1" >&2; echo "           run: $2" >&2; missing=1; }
[ -d "$TC" ]            || say_missing "the ARM toolchain ($TC)" "./toolchain.sh"
[ -d src/pico-sdk/.git ] || say_missing "the Pico SDK (src/pico-sdk)" "./sdk.sh"
[ -f "$FW/CMakeLists.txt" ] || { echo "  MISSING  $FW — the firmware source is not here." >&2; missing=1; }
if [ "$missing" = 1 ]; then
  echo "" >&2
  echo "Nothing was built." >&2
  exit 1
fi

# host-side tools the SDK builds pioasm/picotool with
for t in cmake git python3; do
  command -v "$t" >/dev/null || { echo "  MISSING  $t on PATH" >&2; missing=1; }
done
if ! command -v cc >/dev/null && ! command -v gcc >/dev/null && ! command -v clang >/dev/null; then
  echo "  MISSING  a host C compiler" >&2
  if [ "$(uname -s)" = "Darwin" ]; then
    echo "           run: xcode-select --install" >&2
  else
    echo "           run: sudo apt install build-essential" >&2
  fi
  missing=1
fi
[ "$missing" = 1 ] && { echo "" >&2; echo "Nothing was built." >&2; exit 1; }

export PATH="$PWD/$TC/bin:$PATH"
echo "toolchain  $(arm-none-eabi-gcc --version | head -1)"
echo "sdk        $(git -C src/pico-sdk describe --tags 2>/dev/null || echo '(unknown)')"
echo "build type $BUILD_TYPE"
echo ""

# --- an existing build directory is the user's to keep or lose --------------
BUILD="$FW/build"
if [ -d "$BUILD" ]; then
  if [ "$CLEAN" = 1 ]; then
    echo "Removing $BUILD (--clean given) ..."
    rm -rf "$BUILD"
  elif [ -t 0 ]; then
    # Only reuse silently if it was configured for the same thing; a build
    # directory carrying a different CMAKE_BUILD_TYPE will quietly produce the
    # wrong binary.
    PREV=$(sed -n 's/^CMAKE_BUILD_TYPE:STRING=//p' "$BUILD/CMakeCache.txt" 2>/dev/null || true)
    if [ -n "$PREV" ] && [ "$PREV" != "$BUILD_TYPE" ]; then
      echo "$BUILD was configured as $PREV, you asked for $BUILD_TYPE."
      printf "Remove it and reconfigure? [y/N] "
      read -r ans
      case "$ans" in [yY]*) rm -rf "$BUILD" ;; *) echo "Keeping it; the type will not change."; esac
    fi
  fi
fi

cd "$FW"
cmake -S . -B build -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
      -DPICOTOOL_FETCH_FROM_GIT_PATH="$PWD/../picotool"
cmake --build build -j"$( (command -v nproc >/dev/null && nproc) || sysctl -n hw.ncpu || echo 4 )"

UF2="build/detector-firmware.uf2"
if [ -f "$UF2" ]; then
  echo ""
  echo "Built: $FW/$UF2  ($(du -h "$UF2" | cut -f1))"
  echo ""
  echo "Flash: hold BOOTSEL while plugging the Pico in, then copy the .uf2"
  echo "onto the RPI-RP2 drive that appears."
  echo "Debug console: 115200 baud on UART0 (GP0 = TX)."
else
  echo "" >&2
  echo "Build finished but $UF2 is not there." >&2
  exit 1
fi
