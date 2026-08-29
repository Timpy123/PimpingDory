#!/usr/bin/env python3
"""PCB generator for the detector HAT.

Reads netlist.net (kicad-cli sch export netlist), imports footprints from
KiCad's libraries + hat.pretty, binds pads to nets, places parts on the
floorplan from docs/HAT-SCHEMATIC-SPEC.md, adds outline, mounting holes and
the ground-zone strategy (hatched pours, solid island under the RX front end).

Routing is applied on top of this placement in later passes.
Run from kicad/: python3 tools/pcb_gen.py
"""

import os
import re

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_paths import KICAD_FP, require   # noqa: E402
require("KICAD_FP")
BOARD_W, BOARD_H = 42.0, 135.0
# 2026-07-20: user relocated the whole component layout by a uniform group-move
# in the PCB editor (verified via BT1 and U10, both shifted identically) — the
# outline/zone frame must follow so it still wraps the actual components.
ORIGIN_X, ORIGIN_Y = 19.0, 41.0

# ---- floorplan: ref -> (x, y, rot) ------------------------------------------
# Blocks per spec: TX loop tight & near coil terminal; RX star-grounded at the
# coil terminal corner, away from the boosts; connectors for window parts on
# the right edge; boosts center-left; battery/charger left edge.

PLACE = {
    # N service end (threaded plug): battery, charge, debug, reed
    "J9": (57.48, 72.29, 90),
    # charger row (R3/R4 CC pull-downs removed with USB-C, 2026-07-24)
    "U1": (39.635, 48.815, 180), "C1": (45.7, 42.38, 180), "R7": (33.83, 49.42, 0),
    # cell protection
    "U2": (26.0725, 60.94, 180), "C2": (30, 61.47, 180), "R5": (30, 60.01, 0), "R6": (21.7, 61.765, 270),
    "Q2": (24.955, 67.4275, -90),
    # switch + diode-OR + fuse
    "Q1": (56.1225, 48.955, 0), "R1": (58.83, 49.04, 90), "R2": (57.07, 45.61, 90), "D7": (52.2, 50.94, 90),
    "F1": (40.05, 72.13, 90),
    # boosts (north of Pico; VSYS enters Pico top-right)
    "U3": (38.44, 54.9225, 90), "L1": (45.61, 55.2, -90), "D1": (53.8, 56.8, 180), "C3": (23.09, 49.88, 90),
    "C4": (59.08, 55.39, 90), "R8": (57.885, 59.7, 180), "R9": (53.735, 59.9, 180),
    "U4": (22.83, 74.0625, -90), "L2": (30.53, 54.29, -90), "D8": (40.1, 62.23, 180), "C5": (53.71, 45.57, 180),
    "C6": (48.725, 62.02, 0), "R14": (27.72, 78.18, 180), "R15": (27.885, 73.89, 0),
    # Pico lengthwise, pin1/USB end north
    "U10": (39.89, 114, 0),
    # left channel: I2C pull-ups near GP8/9, WS resistor near GP13
    "R31": (27.29, 113.53, 90), "R32": (27.23, 120.195, -90), "R30": (27, 129.825, 90),
    # top-side display/sensor docks, column along the left edge by R31/R32
    # (rough start positions — user fine-tunes in the GUI, checkpoint rule)
    "J6": (21.96, 112.2, 90), "J7": (21.96, 121.665, 90), "J8": (21.96, 103.36, 90),
    # sounder driver at Pico south end (SND on pins 19/20)
    "U8": (29.315, 44.605, 0), "C17": (34.385, 46.77, 0), "C18": (35.16, 42.74, 90), "C19": (53.05, 64.775, 90),
    "C20": (22.45, 82.91, 180),
    
    # display connectors on the top face, mid-window
    # J1 piezo, J3 5V-charge, J2 power-switch: 1x2 sockets in a row along the
    # north edge (J1 left corner, J3 middle, J2 right corner), aligned flush.
    "J1": (22.82, 42.3, 90), "J3": (41.23, 42.3, 90), "J2": (57.07, 42.3, 270),
    "BT1": (40, 114, 180),  # MYOUNG THT terminals, flipped to bottom by post-step
    # damping bank
    "R11": (39.76, 168.42, 90), "R12": (46.99, 168.42, 90), "R13": (54.19, 168.42, 90),
    "Q4": (54.56, 162.39, 270), "Q5": (47.03, 162.39, 270), "Q6": (39.61, 162.39, 270),
    "R16": (52.62, 155.9, 270), "R17": (48.48, 155.9, 270), "R18": (38.61, 155.9, 270),
    "R24": (54.49, 155.9, 90), "R25": (44.92, 155.9, 90), "R26": (36.4, 155.9, 90),
    # TX end: bulk caps -> MOSFET -> coil terminal at the S edge
    "C7": (26.32, 171.24, 180), "C8": (26.32, 162.14, 180), "Q3": (40, 162.5, 0), "U5": (43.365, 156.035, 180),
    "C10": (56.58, 174.03, 0), "R23": (36.93, 156.73, 180), "D2": (50.83, 171.26, 90),
    "R10": (50.83, 173.41, 180), "C9": (26.32, 153.09, 180), "J4": (43.81, 172, -90),
    # RX chain: right channel, signal flows S (coil) -> N (GP26 mid-right)
    "R20": (51.68, 166.68, 0), "D3": (56.312, 165.088, 0), "D4": (56.325, 162.5, 180),
    "C11": (56.95, 156, 180), "R49": (57, 151, 0), "R40": (57.195, 149.25, 0),
    "R41": (55.825, 146.5, 180), "U6": (55.5, 141, 90), "R48": (57.195, 135.5, 0),
    "D9": (56.325, 132, 0), "D10": (56.325, 128.5, 0), "U7": (55.5, 123.25, 90),
    "C16": (54.9, 116.07, 0), "U9": (55.405, 98.505, 90),
    "C14": (52.1, 107.57, 0), "R22": (53.91, 109.32, 180), "C13": (53.91, 110.79, 180),
    "D5": (53.37, 93.3, 0), "D6": (56.97, 91.65, 90), "R43": (54.915, 114.55, 0),
    "R42": (51.9, 119.5, 90), "R45": (53.87, 105.95, 180), "R44": (53.82, 104.22, 0),
    "C12": (53.5, 134.25, 0), "R21": (55.07, 107.57, 0), "R47": (57.04, 105.82, 0),
}

def _sync_live_positions(place):
    """Read whatever's currently saved on disk (GUI edits, one-off script
    tweaks, anything) and overlay it onto PLACE, in-memory, before this
    module is used for anything. Prevents ever silently discarding a live
    edit just because a regenerate ran without a manual sync_place.py first.
    Safe no-op if the board doesn't exist yet or a ref isn't found."""
    import os
    import re
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "detector-hat.kicad_pcb")
    if not os.path.exists(path):
        return 0
    board = open(path).read()
    n = 0
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
        # footprint-level (layer ...) is the first one in the block (pad/graphic
        # layers come later). generation always re-emits on F.Cu then flips
        # BOTTOM-set members after — so a B.Cu-side angle read straight off disk
        # must be de-flipped to its F.Cu-canonical equivalent here, or the next
        # flip step re-flips an already-flipped angle and the part rotates
        # 180 deg every single pipeline run (this bit J3/USB-C visibly since
        # it's asymmetric; symmetric parts hid the same bug).
        layer = re.search(r'\(layer "([^"]+)"\)', fp)
        if at and ref and ref.group(1) in place:
            x, y = float(at.group(1)), float(at.group(2))
            rot = float(at.group(3) or 0)
            if layer and layer.group(1) == "B.Cu":
                rot = (180 - rot) % 360
            place[ref.group(1)] = (x, y, rot)
            n += 1
    return n


_synced = _sync_live_positions(PLACE)
if _synced:
    print(f"(pcb_gen: auto-synced {_synced} live positions from board on import)")

BOTTOM = {"BT1", "J3", "U1", "C1", "R7", "C5",
          "U2", "C2", "R5", "R6", "Q1", "R1", "R2", "D7", "F1",
          "R10", "R11", "R12", "R13", "Q4", "Q5", "Q6", "J1", "J2",
          "R16", "R17", "R18", "R24", "R25", "R26"}

MOUNTING_HOLES = []  # strip rides printed cradle rails; no board holes


# ---- netlist parsing ---------------------------------------------------------

def sexpr_blocks(text, tag):
    """Yield balanced s-expr blocks starting with (tag ..."""
    for m in re.finditer(r'\(' + tag + r'[\s(]', text):
        depth = 0
        i = m.start()
        for j in range(i, len(text)):
            if text[j] == '(':
                depth += 1
            elif text[j] == ')':
                depth -= 1
                if depth == 0:
                    yield text[i:j + 1]
                    break


def parse_netlist(path):
    text = open(path).read()
    fp_of = {}
    for block in sexpr_blocks(text, "comp"):
        ref = re.search(r'\(ref "([^"]+)"\)', block).group(1)
        fp = re.search(r'\(footprint "([^"]+)"\)', block)
        fp_of[ref] = fp.group(1) if fp else ""
    netnames = {}   # code -> name
    pad_net = {}    # (ref, pin) -> code
    for block in sexpr_blocks(text, "net "):
        code = int(re.search(r'\(code "(\d+)"\)', block).group(1))
        name = re.search(r'\(name "([^"]+)"\)', block).group(1)
        netnames[code] = name
        for node in re.finditer(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', block):
            pad_net[(node.group(1), node.group(2))] = code
    return fp_of, netnames, pad_net


# ---- footprint import --------------------------------------------------------

def load_footprint(lib_id):
    lib, name = lib_id.split(":")
    if lib == "hat":
        path = f"hat.pretty/{name}.kicad_mod"
    else:
        path = f"{KICAD_FP}/{lib}.pretty/{name}.kicad_mod"
    return open(path).read()


def bind_and_place(fp_text, lib_id, ref, x, y, rot, pad_net, netnames):
    """Set position, reference, and per-pad nets on an imported footprint."""
    # strip file-level metadata tokens that belong to .kicad_mod files
    fp_text = re.sub(r'\(version \d+\)\s*', '', fp_text)
    fp_text = re.sub(r'\(generator[^)]*\)\s*', '', fp_text)
    fp_text = fp_text.replace(f'(footprint "{lib_id.split(":")[1]}"',
                              f'(footprint "{lib_id}" (at {x} {y} {rot})', 1)
    fp_text = fp_text.replace('"REF**"', f'"{ref}"')
    # bind nets pad by pad
    out = []
    pos = 0
    for m in re.finditer(r'\(pad\s+"([^"]*)"', fp_text):
        pad_name = m.group(1)
        # find the end of this pad block
        depth = 0
        for j in range(m.start(), len(fp_text)):
            if fp_text[j] == '(':
                depth += 1
            elif fp_text[j] == ')':
                depth -= 1
                if depth == 0:
                    end = j
                    break
        code = pad_net.get((ref, pad_name))
        if code is not None:
            out.append((end, f' (net {code} "{netnames[code]}")'))
        # rotate pads with the footprint: KiCad stores pad angle as total
        if rot:
            pad_block = fp_text[m.start():end]
            at = re.search(r'\(at ([-\d.]+) ([-\d.]+)( [-\d.]+)?\)', pad_block)
            if at:
                a = float(at.group(3) or 0) + rot
                new_at = f'(at {at.group(1)} {at.group(2)} {a})'
                out.append((m.start() + at.start(), (at.group(0), new_at)))
    # apply insertions/replacements back-to-front
    for item in sorted(out, key=lambda t: -t[0]):
        if isinstance(item[1], tuple):
            old, new = item[1]
            i = item[0]
            fp_text = fp_text[:i] + fp_text[i:].replace(old, new, 1)
        else:
            fp_text = fp_text[:item[0]] + item[1] + fp_text[item[0]:]
    return fp_text


# ---- board assembly ----------------------------------------------------------

LAYERS = """  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (36 "B.SilkS" user "B.Silkscreen")
    (37 "F.SilkS" user "F.Silkscreen")
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (40 "Dwgs.User" user "User.Drawings")
    (44 "Edge.Cuts" user)
    (46 "B.CrtYd" user "B.Courtyard")
    (47 "F.CrtYd" user "F.Courtyard")
    (48 "B.Fab" user)
    (49 "F.Fab" user)
    (50 "B.Paste" user)
    (51 "F.Paste" user)
  )
"""


def zone(net, netname, layer, pts, hatched, priority=0):
    fill_mode = "(mode hatch)" if hatched else ""
    hatch_params = ("(hatch_thickness 0.8) (hatch_gap 1.2) (hatch_orientation 45) "
                    if hatched else "")
    xy = " ".join(f"(xy {x} {y})" for x, y in pts)
    return (f'  (zone (net {net}) (net_name "{netname}") (layer "{layer}")'
            f' (name "{netname}_{layer}") (priority {priority})\n'
            f'    (hatch edge 0.508)\n'
            f'    (connect_pads yes (clearance 0.25))\n'
            f'    (min_thickness 0.15)\n'
            f'    (fill yes {fill_mode} {hatch_params}(thermal_gap 0.5)'
            f' (thermal_bridge_width 0.5) (island_removal_mode 0))\n'
            f'    (polygon (pts {xy}))\n'
            f'  )\n')


def main():
    fp_of, netnames, pad_net = parse_netlist("netlist.net")

    body = ""
    missing = []
    for ref, (x, y, rot) in PLACE.items():
        lib_id = fp_of.get(ref, "")
        if not lib_id:
            missing.append(ref)
            continue
        fp = load_footprint(lib_id)
        body += bind_and_place(fp, lib_id, ref, x, y, rot, pad_net, netnames) + "\n"
    unplaced = sorted(set(fp_of) - set(PLACE))
    if missing or unplaced:
        print("WARNING missing footprint:", missing, "unplaced:", unplaced)

    # mounting holes (board-only footprints)
    hole_fp = load_footprint("MountingHole:MountingHole_3.2mm_M3")
    for i, (hx, hy) in enumerate(MOUNTING_HOLES):
        body += bind_and_place(hole_fp, "MountingHole:MountingHole_3.2mm_M3",
                               f"H{i + 1}", hx, hy, 0, {}, {}) + "\n"

    nets = "".join(f'  (net {code} "{name}")\n'
                   for code, name in sorted(netnames.items()))

    outline = (f'  (gr_rect (start {ORIGIN_X} {ORIGIN_Y})'
               f' (end {ORIGIN_X + BOARD_W} {ORIGIN_Y + BOARD_H})'
               f' (stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))\n')

    gnd = next(c for c, n in netnames.items() if n == "GND")
    # solid pours away from the coil (fill integrity); hatch only the
    # coil-adjacent south strip (eddy-current rule); solid RX island on top
    def fr(pts):  # translate frame-relative polygon points into board space
        return [(ORIGIN_X + x, ORIGIN_Y + y) for (x, y) in pts]
    north_pts = fr([(0, 0), (BOARD_W, 0), (BOARD_W, 110), (0, 110)])
    south_pts = fr([(0, 109), (BOARD_W, 109), (BOARD_W, BOARD_H), (0, BOARD_H)])
    rx_pts = fr([(31.5, 92), (BOARD_W, 92), (BOARD_W, 128), (31.5, 128)])
    # All same priority ON PURPOSE (2026-07-22): differing priorities make
    # same-net zones knock each other's fill back to a flush zero-overlap
    # seam, which KiCad connectivity treats as DISCONNECTED — it split the
    # whole TX region (south of the seam) into F+B islands and produced the
    # standing "GND zone-lobe" DRC noise. Equal priorities let the 1mm
    # polygon overlaps actually merge copper. Where hatched south overlaps
    # solid rx, the union is solid — which is the intent there anyway.
    zones = (zone(gnd, "GND", "F.Cu", north_pts, hatched=False)
             + zone(gnd, "GND", "B.Cu", north_pts, hatched=False)
             + zone(gnd, "GND", "F.Cu", south_pts, hatched=True)
             + zone(gnd, "GND", "B.Cu", south_pts, hatched=True)
             + zone(gnd, "GND", "F.Cu", rx_pts, hatched=False))

    content = ('(kicad_pcb (version 20221018) (generator "pcb_gen")\n'
               '  (general (thickness 1.6))\n'
               '  (paper "A4")\n'
               + LAYERS
               + '  (setup (pad_to_mask_clearance 0))\n'
               + '  (net 0 "")\n' + nets
               + outline + body + zones + ')\n')
    with open("detector-hat.kicad_pcb", "w") as f:
        f.write(content)
    print(f"wrote detector-hat.kicad_pcb: {len(PLACE)} parts placed,"
          f" {len(netnames)} nets")


if __name__ == "__main__":
    main()
