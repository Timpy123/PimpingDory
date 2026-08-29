#!/usr/bin/env python3
"""Pull footprint positions/rotations from detector-hat.kicad_pcb back into
pcb_gen.py's PLACE table, so manual moves in the KiCad GUI survive
regeneration. Run from kicad/ after editing the board:

    python3 tools/sync_place.py
"""

import re

board = open("detector-hat.kicad_pcb").read()
positions = {}
for m in re.finditer(r'\(footprint "', board):
    depth, j = 0, m.start()
    while True:
        if board[j] == '(':
            depth += 1
        elif board[j] == ')':
            depth -= 1
            if depth == 0:
                break
        j += 1
    fp = board[m.start():j + 1]
    at = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', fp)
    ref = re.search(r'\(property "Reference" "([^"]+)"', fp) or \
        re.search(r'fp_text reference "([^"]+)"', fp)
    # de-flip B.Cu angles to their F.Cu-canonical equivalent — pcb_gen.py always
    # regenerates on F.Cu then flips BOTTOM-set members after, so PLACE must
    # hold the pre-flip angle or the next flip doubles up (see pcb_gen.py's
    # _sync_live_positions for the full explanation).
    layer = re.search(r'\(layer "([^"]+)"\)', fp)
    if at and ref:
        x, y = float(at.group(1)), float(at.group(2))
        rot = float(at.group(3) or 0)
        if layer and layer.group(1) == "B.Cu":
            rot = (180 - rot) % 360
        positions[ref.group(1)] = (x, y, rot)

gen = open("tools/pcb_gen.py").read()
updated = 0
for ref, (x, y, rot) in positions.items():
    def fmt(v):
        return f"{v:g}"
    pat = re.compile(r'"' + re.escape(ref) + r'": \([-\d. ]+,[-\d. ]+,[-\d. ]+\)')
    new = f'"{ref}": ({fmt(x)}, {fmt(y)}, {fmt(rot)})'
    if pat.search(gen):
        gen = pat.sub(new, gen)
        updated += 1

open("tools/pcb_gen.py", "w").write(gen)
print(f"synced {updated} positions from board into PLACE")
