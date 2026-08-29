# Where KiCad lives, on whatever this machine is. Sourced, not run:
#     . "$(dirname "$0")/kicad_paths.sh"
# Sets KICAD_CLI and KICAD_PY, or exits with a message naming what to install.
#
# Written 2026-08-30: the tools had /Applications/... hardcoded, which is right
# on this Mac and wrong everywhere else. Nothing about the pipeline is
# macOS-specific apart from these two paths.

_kicad_find() {
  local name="$1"; shift
  local p
  for p in "$@"; do [ -x "$p" ] && { printf '%s' "$p"; return 0; }; done
  p=$(command -v "$name" 2>/dev/null) && { printf '%s' "$p"; return 0; }
  return 1
}

# kicad-cli: gerbers, drill, netlist export
KICAD_CLI="${KICAD_CLI:-$(_kicad_find kicad-cli \
  "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli" \
  "/usr/bin/kicad-cli" "/usr/local/bin/kicad-cli" \
  "/var/lib/flatpak/exports/bin/org.kicad.KiCad" \
  "$HOME/.local/share/flatpak/exports/bin/org.kicad.KiCad" || true)}"

# The python that can `import pcbnew` — KiCad's own on macOS, the system one on
# Linux where the package installs pcbnew into site-packages.
KICAD_PY="${KICAD_PY:-$(_kicad_find "" \
  "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3" \
  "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3" \
  || true)}"
if [ -z "${KICAD_PY:-}" ]; then
  for _p in python3 /usr/bin/python3; do
    if command -v "$_p" >/dev/null 2>&1 && "$_p" -c "import pcbnew" 2>/dev/null; then
      KICAD_PY=$(command -v "$_p"); break
    fi
  done
fi

# Stock footprint libraries, for pcb_gen.py
KICAD_FP="${KICAD_FP:-}"
if [ -z "$KICAD_FP" ]; then
  for _p in "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints" \
            "/usr/share/kicad/footprints" "/usr/local/share/kicad/footprints" \
            "$HOME/.local/share/kicad/footprints"; do
    [ -d "$_p" ] && { KICAD_FP="$_p"; break; }
  done
fi

# Freerouting, fetched by ../../freerouting.sh
FR="${FR:-}"
if [ -z "$FR" ]; then
  _root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  for _p in "../src/Freerouting.app/Contents/MacOS/freerouting" \
            "../src/freerouting-2.2.4-linux-x64.AppImage" \
            "$_root/src/Freerouting.app/Contents/MacOS/freerouting" \
            "$_root/src/freerouting-2.2.4-linux-x64.AppImage"; do
    [ -x "$_p" ] && { FR="$_p"; break; }
  done
fi

kicad_require() {
  local bad=0
  for _v in "$@"; do
    case "$_v" in
      cli) [ -n "${KICAD_CLI:-}" ] || { echo "kicad-cli not found." >&2
             echo "  macOS: install KiCad, or set KICAD_CLI=/path/to/kicad-cli" >&2
             echo "  Linux: apt install kicad  (or set KICAD_CLI)" >&2; bad=1; } ;;
      py)  [ -n "${KICAD_PY:-}" ] || { echo "No python with 'import pcbnew' found." >&2
             echo "  macOS: KiCad ships one; set KICAD_PY if it moved" >&2
             echo "  Linux: apt install kicad python3-pcbnew  (or set KICAD_PY)" >&2; bad=1; } ;;
      fp)  [ -n "${KICAD_FP:-}" ] || { echo "KiCad footprint libraries not found." >&2
             echo "  set KICAD_FP=/path/to/kicad/footprints" >&2; bad=1; } ;;
      fr)  [ -n "${FR:-}" ] || { echo "Freerouting not found." >&2
             echo "  run ../freerouting.sh from the MetalDetector folder" >&2; bad=1; } ;;
    esac
  done
  [ "$bad" = 0 ] || exit 1
}
