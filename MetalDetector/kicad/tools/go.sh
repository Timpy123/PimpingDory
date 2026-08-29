#!/bin/bash
# Full reroute pipeline, one shot: regen -> flip/rip -> Freerouting (once)
# -> SES import + zone fill -> pre-stitch stranded report -> stitch_islands
# -> silk -> sync -> signal-net check.
# Run from anywhere: kicad/tools/go.sh . Output ends with a SUMMARY block.
set -euo pipefail
cd "$(dirname "$0")/.."

# Paths resolve per machine; override any of them in the environment.
. "$(dirname "$0")/kicad_paths.sh"
kicad_require py fr cli
PY="$KICAD_PY"

filter() { grep -v "memory leak\|assert\|image handler\|Debug:" || true; }

echo "== 1/8 regenerate board (auto-syncs your GUI moves) =="
"$PY" tools/pcb_gen.py 2>&1 | filter

echo "== 2/8 flip bottom set, rip tracks, export DSN =="
"$PY" - 2>&1 <<'EOF' | filter
import re
import pcbnew
b = pcbnew.LoadBoard("detector-hat.kicad_pcb")
src = open("tools/pcb_gen.py").read()
BOTTOM = eval(re.search(r"BOTTOM = (\{[^}]*\})", src).group(1))
n = 0
for fp in b.Footprints():
    if (fp.GetReference() in BOTTOM) != fp.IsFlipped():
        fp.Flip(fp.GetPosition(), False)
        n += 1
print("flipped", n)
for t in list(b.Tracks()):
    b.RemoveNative(t)
print("DSN export:", pcbnew.ExportSpecctraDSN(b, "detector-hat.dsn"))
pcbnew.SaveBoard("detector-hat.kicad_pcb", b, True)  # skip settings: never touch .kicad_pro
EOF

echo "== 3/8 freerouting (single run, -mp 400) =="
FRLINE=$("$FR" -de detector-hat.dsn -do detector-hat.ses -mp 400 2>&1 \
  | grep -E "session completed|ERROR" || true)
echo "$FRLINE"

echo "== 4/8 import SES + fill zones =="
"$PY" - 2>&1 <<'EOF' | filter
import pcbnew
b = pcbnew.LoadBoard("detector-hat.kicad_pcb")
pcbnew.ImportSpecctraSES(b, "detector-hat.ses")
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard("detector-hat.kicad_pcb", b, True)  # skip settings: never touch .kicad_pro
print("imported+filled")
EOF

echo "== 5/8 pre-stitch stranded GND pads =="
PRE=$("$PY" - 2>&1 <<'EOF' | filter
import sys
sys.path.insert(0, "tools")
import pcbnew
from stitch_islands import build, find
b = pcbnew.LoadBoard("detector-hat.kicad_pcb")
parent, units, pad_nodes = build(b)
comps = {}
for pk in pad_nodes:
    comps.setdefault(find(parent, pk), []).append(pk)
main = max(comps, key=lambda r: len(comps[r]))
stranded = sorted(f"{r}.{p}" for root, pads in comps.items()
                  if root != main for (_t, r, p) in pads)
print(f"PRE-STITCH STRANDED: {len(stranded)}")
print("  " + ", ".join(stranded) if stranded else "  (none)")
EOF
)
echo "$PRE"

echo "== 6/8 stitch islands =="
STITCH=$("$PY" tools/stitch_islands.py 2>&1 | filter)
echo "$STITCH"

echo "== 7/8 silk + sync =="
"$PY" tools/silk.py 2>&1 | filter
"$PY" tools/sync_place.py 2>&1 | filter

echo "== 8/9 signal-net check (KiCad DRC, authoritative) =="
# scratch is ALWAYS <repo>/tmp — never /tmp or /private/tmp
SCRATCH="../tmp"
mkdir -p "$SCRATCH"
"$KICAD_CLI" pcb drc --format json -o "$SCRATCH/go_drc.json" detector-hat.kicad_pcb >/dev/null 2>&1 || true
CHECK=$(python3 tools/signal_check.py "$SCRATCH/go_drc.json")
echo "$CHECK"

echo "== 9/9 heat placement check =="
HEAT=$("$PY" tools/heat_check.py 2>&1 | filter)
echo "$HEAT"

echo "== SUMMARY =="
FRN=$(echo "$FRLINE" | grep -o '[0-9]* unrouted' | tail -1 | grep -o '^[0-9]*' || echo 0)
echo "freerouting: $FRN unrouted (raw count; the GND pads it lists are covered by the pour)"
echo "$PRE" | grep "PRE-STITCH" || true
echo "$STITCH" | grep -E "stitch vias added|REMAINING|fully joined|stranded:" || true
echo "$CHECK"
echo "$HEAT"
echo "== DONE =="
