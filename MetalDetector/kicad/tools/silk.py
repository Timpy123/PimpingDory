#!/usr/bin/env python3
"""Silk extras (pin-1 dots, battery polarity, board name). Board-file-only
items — pcb_gen regeneration wipes them, so re-run this after the
regen -> flip -> SES-import -> stitch -> fill pipeline. Run with KiCad's python
from kicad/."""
import pcbnew, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
b = pcbnew.LoadBoard('detector-hat.kicad_pcb')

def dot(x, y, layer):
    c = pcbnew.PCB_SHAPE(b)
    c.SetShape(pcbnew.SHAPE_T_CIRCLE)
    c.SetCenter(pcbnew.VECTOR2I(int(x*1e6), int(y*1e6)))
    c.SetEnd(pcbnew.VECTOR2I(int((x+0.35)*1e6), int(y*1e6)))
    c.SetFilled(True); c.SetLayer(layer); c.SetWidth(0)
    b.Add(c)

def text(s, x, y, layer, size=4.0, thick=0.8, angle=0):
    t = pcbnew.PCB_TEXT(b)
    t.SetText(s)
    t.SetPosition(pcbnew.VECTOR2I(int(x*1e6), int(y*1e6)))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(int(size*1e6), int(size*1e6)))
    t.SetTextThickness(int(thick*1e6))
    if angle: t.SetTextAngle(pcbnew.EDA_ANGLE(angle))
    if layer == pcbnew.B_SilkS: t.SetMirrored(True)
    b.Add(t)
    return t

btp = {p.GetNetname(): p.GetPosition() for p in b.FindFootprintByReference('BT1').Pads()}

def pin1_dot(ref, dx=1.6, dy=-1.0):
    """Pin-1 dot on whichever silk side the connector sits on; skip if the
    connector isn't on the board (J5 retired 2026-07-24 — skip-if-missing so
    removing a connector never crashes the silk step again)."""
    fp = b.FindFootprintByReference(ref)
    if fp is None:
        return
    p1 = [p for p in fp.Pads() if p.GetName() == '1']
    if not p1:
        return
    pos = p1[0].GetPosition()
    layer = pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS
    dot(pos.x / 1e6 + dx, pos.y / 1e6 + dy, layer)

for _ref in ('J4', 'J6', 'J7', 'J8'):
    pin1_dot(_ref)

def pin_labels(ref, labels, size=1.0, thick=0.15, clear=3.5):
    """Print a label under each named pad, pushed clear of the connector body/
    courtyard toward the board interior (these docks hug an edge, so the letters
    would sit under the jumper otherwise). Each letter stays at its pad's X so it
    still identifies the right pin."""
    fp = b.FindFootprintByReference(ref)
    if fp is None:
        return
    layer = pcbnew.B_SilkS if fp.IsFlipped() else pcbnew.F_SilkS
    dy = clear if fp.GetPosition().y / 1e6 < 108.5 else -clear  # toward interior
    for p in fp.Pads():
        lbl = labels.get(p.GetName())
        if not lbl:
            continue
        pos = p.GetPosition()
        text(lbl, pos.x / 1e6, pos.y / 1e6 + dy, layer, size, thick)

# J1 piezo (1=P,2=N), J2 switch (1=R Reed,2=G GND), J3 charge (1=5V,2=G GND)
pin_labels('J1', {'1': 'P', '2': 'N'})
pin_labels('J2', {'1': 'R', '2': 'G'})
pin_labels('J3', {'1': '5V', '2': 'G'})

def draw_analog_keepout():
    """Design aid, NOT manufactured: outline the sensitive RX analog region on
    Dwgs.User (toggle 'User.Drawings' in the editor). Keep switching nets
    (V12_TX, the boosts, WS_DATA) and their vias out of this box — comment.txt
    topic 5. Auto-computed from the analog-net pad bbox so it tracks moves."""
    analog = {"VREF", "STG2_IN", "STG2_OUT", "RX_B", "RX_CL", "RX_DIV",
              "RX_ADC", "U6_FB", "U9_FB", "POT_A"}
    xs, ys = [], []
    for fp in b.Footprints():
        for p in fp.Pads():
            if p.GetNetname() in analog:
                pos = p.GetPosition()
                xs.append(pos.x)
                ys.append(pos.y)
    if not xs:
        return
    m = int(2.0 * 1e6)
    r = pcbnew.PCB_SHAPE(b)
    r.SetShape(pcbnew.SHAPE_T_RECT)
    r.SetStart(pcbnew.VECTOR2I(min(xs) - m, min(ys) - m))
    r.SetEnd(pcbnew.VECTOR2I(max(xs) + m, max(ys) + m))
    r.SetLayer(pcbnew.Dwgs_User)
    r.SetWidth(int(0.2 * 1e6))
    r.SetFilled(False)
    b.Add(r)
    text('RX ANALOG - KEEP SWITCHING NETS CLEAR',
         (min(xs) - m) / 1e6, (min(ys) - m) / 1e6 - 1.4, pcbnew.Dwgs_User, 1.4, 0.2)

draw_analog_keepout()
text('+', btp['VBAT_RAW'].x/1e6 + 7, btp['VBAT_RAW'].y/1e6 + 1.5, pcbnew.B_SilkS, 5, 1.0)
text('-', btp['BAT_NEG'].x/1e6 + 7, btp['BAT_NEG'].y/1e6 - 1.5, pcbnew.B_SilkS, 5, 1.0)
# title: rotated 90 deg, run parallel to the Pico socket (west edge), scaled
# to its exact 51.2mm pad span (measured bounding box, not eyeballed).
# anchor coords are frame-relative; +19/+41 matches pcb_gen.py's ORIGIN_X/
# ORIGIN_Y (the 2026-07-20 whole-board group-move) or this text floats off
# in empty space to the old pre-move origin instead of sitting on the board.
ORIGIN_X, ORIGIN_Y = 19.0, 41.0
title = text('UnderwaterMetalDetector V1.0', ORIGIN_X + 3.2, ORIGIN_Y + 73, pcbnew.F_SilkS, 2.24, 0.38, angle=90)
bb = title.GetBoundingBox()
span = bb.GetHeight() / 1e6
scale = 51.2 / span
title.SetTextSize(pcbnew.VECTOR2I(int(title.GetTextSize().x * scale), int(title.GetTextSize().y * scale)))
title.SetTextThickness(int(title.GetTextThickness() * scale))

# copyright line: second parallel run, offset further from the edge (toward
# board center), smaller size; "doesn't matter if it lands over transistors"
text('Copyright (c) 2026 Timpy Holding B.V.', ORIGIN_X + 6.4, ORIGIN_Y + 73, pcbnew.F_SilkS, 1.2, 0.2, angle=90)

pcbnew.SaveBoard('detector-hat.kicad_pcb', b, True)  # skip settings: never touch .kicad_pro
print('silk applied')
