"""Where KiCad and Freerouting live, on whatever machine this is.

    from kicad_paths import KICAD_CLI, KICAD_FP, KICAD_PY, FR

Each is resolved by looking in the usual places for macOS and Linux, and each
can be overridden with an environment variable of the same name. Written
2026-08-30: these paths used to be hardcoded to /Applications/..., which is
correct on this Mac and wrong everywhere else. Nothing else in the pipeline is
platform-specific.
"""

import os
import shutil

_MAC = "/Applications/KiCad/KiCad.app/Contents"


def _first(env, candidates, kind="file"):
    override = os.environ.get(env)
    if override:
        return override
    for c in candidates:
        if not c:
            continue
        if kind == "dir" and os.path.isdir(c):
            return c
        if kind == "file" and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
        if kind == "any" and os.path.exists(c):
            return c
    return None


KICAD_CLI = _first("KICAD_CLI", [
    f"{_MAC}/MacOS/kicad-cli",
    "/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli",
    shutil.which("kicad-cli"),
])

KICAD_PY = _first("KICAD_PY", [
    f"{_MAC}/Frameworks/Python.framework/Versions/Current/bin/python3",
    f"{_MAC}/Frameworks/Python.framework/Versions/3.9/bin/python3",
])
if KICAD_PY is None:
    # On Linux the distribution package puts pcbnew in the system python.
    import subprocess
    for cand in ("python3", "/usr/bin/python3"):
        exe = shutil.which(cand) or cand
        try:
            if subprocess.run([exe, "-c", "import pcbnew"],
                              capture_output=True, timeout=20).returncode == 0:
                KICAD_PY = exe
                break
        except Exception:
            pass

KICAD_FP = _first("KICAD_FP", [
    f"{_MAC}/SharedSupport/footprints",
    "/usr/share/kicad/footprints",
    "/usr/local/share/kicad/footprints",
    os.path.expanduser("~/.local/share/kicad/footprints"),
], kind="dir")

# Relative to kicad/, which is where the tools are run from, but resolve it
# from this file's own location too so it works whatever the cwd is.
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FR = _first("FR", [
    "../src/Freerouting.app/Contents/MacOS/freerouting",
    "../src/freerouting-2.2.4-linux-x64.AppImage",
    os.path.join(_ROOT, "src/Freerouting.app/Contents/MacOS/freerouting"),
    os.path.join(_ROOT, "src/freerouting-2.2.4-linux-x64.AppImage"),
])

_ADVICE = {
    "KICAD_CLI": "install KiCad, or set KICAD_CLI=/path/to/kicad-cli"
                 "  (Linux: apt install kicad)",
    "KICAD_PY":  "a python that can 'import pcbnew'"
                 "  (Linux: apt install kicad python3-pcbnew), or set KICAD_PY",
    "KICAD_FP":  "KiCad's stock footprint libraries, or set KICAD_FP",
    "FR":        "run ../freerouting.sh from the MetalDetector folder, or set FR",
}


def require(*names):
    """Fail with something actionable rather than a confusing stack trace."""
    missing = [n for n in names if globals().get(n) is None]
    if missing:
        lines = ["Cannot find:"]
        for n in missing:
            lines.append(f"  {n} — {_ADVICE[n]}")
        raise SystemExit("\n".join(lines))
