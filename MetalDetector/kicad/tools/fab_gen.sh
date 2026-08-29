#!/bin/bash
# Generate the JLCPCB upload package (gerbers zip, BOM CSV, CPL CSV) in
# kicad/fab/ from the current detector-hat.kicad_pcb / .kicad_sch.
# Run from kicad/: tools/fab_gen.sh
set -euo pipefail
cd "$(dirname "$0")/.."

. "$(dirname "$0")/kicad_paths.sh"
kicad_require cli
BOARD="detector-hat.kicad_pcb"
SCH="detector-hat.kicad_sch"
OUT="fab"
NAME="detector-hat"
LAYERS="F.Cu,B.Cu,F.Paste,B.Paste,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts"

rm -rf "$OUT/gerbers"
mkdir -p "$OUT/gerbers"

"$KICAD_CLI" pcb export gerbers "$BOARD" -o "$OUT/gerbers" --layers "$LAYERS"
"$KICAD_CLI" pcb export drill "$BOARD" -o "$OUT/gerbers" --excellon-separate-th
( cd "$OUT/gerbers" && rm -f "../${NAME}-gerbers.zip" && zip -q -r "../${NAME}-gerbers.zip" . )

"$KICAD_CLI" pcb export pos "$BOARD" -o "$OUT/positions-raw.csv" --format csv --units mm --side both

# LCSC field is baked into each schematic symbol by sch_gen.py's LCSC dict —
# --ref-range-delimiter "" keeps designator lists like "C2,C10,C11" instead
# of collapsing to ranges JLC's uploader chokes on.
"$KICAD_CLI" sch export bom "$SCH" -o "$OUT/bom-raw.csv" \
  --fields "Reference,Value,Footprint,LCSC" \
  --labels "Reference,Value,Footprint,LCSC" \
  --group-by "Value,Footprint,LCSC" \
  --ref-range-delimiter ""

python3 tools/make_jlc_csv.py

echo "fab package ready in $OUT/ (${NAME}-gerbers.zip, ${NAME}-bom.csv, ${NAME}-cpl.csv)"
