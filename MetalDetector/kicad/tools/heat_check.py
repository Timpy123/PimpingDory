#!/usr/bin/env python3
"""Thermal placement check: flag heat-source <-> heat-sensitive parts that sit
too close, INCLUDING stacked on opposite sides (heat conducts through the FR4).
Reports only current violations. Run with KiCad's python from kicad/.

Heat source next to something that dislikes heat is the actionable rule; we do
NOT flag heat-source pairs that belong together (a boost IC beside its own
inductor/diode), which would just be noise.
"""
import pcbnew

# ref -> why it runs hot
HOT = {
    "U1": "charger (hot while charging)",
    "R10": "2W damping resistor",
    "U3": "12V boost", "L1": "12V boost inductor", "D1": "12V boost diode",
    "U4": "9V boost", "L2": "9V boost inductor", "D8": "9V boost diode",
    "Q3": "TX switch",
    "Q4": "damping switch", "Q5": "damping switch", "Q6": "damping switch",
}
# ref -> why it dislikes heat (only real electrolytics; C1 is a ceramic 0805)
SENSITIVE = {
    "BT1": "18650 cell",
    "C7": "electrolytic", "C8": "electrolytic", "C9": "electrolytic",
    "C20": "electrolytic",
    "U6": "RX op-amp", "U9": "RX op-amp",
}
# pairs that MUST stay close by design, so don't report them as violations:
# C7/C8/C9 are the TX bulk caps that belong tight to Q3 for a low-inductance
# pulse loop (and Q3's duty cycle is low, so it barely heats).
ACCEPTED = {frozenset(p) for p in (("Q3", "C7"), ("Q3", "C8"), ("Q3", "C9"))}
GAP_MM = 2.5  # bounding-box edge gap at/below which a pair is "too close"


def main():
    b = pcbnew.LoadBoard("detector-hat.kicad_pcb")
    info = {}
    for ref in list(HOT) + list(SENSITIVE):
        fp = b.FindFootprintByReference(ref)
        if fp:
            info[ref] = (fp.GetBoundingBox(), "B" if fp.IsFlipped() else "T")

    def gap(a, c):
        ba, bc = info[a][0], info[c][0]
        dx = max(0, ba.GetLeft() - bc.GetRight(), bc.GetLeft() - ba.GetRight())
        dy = max(0, ba.GetTop() - bc.GetBottom(), bc.GetTop() - ba.GetBottom())
        return (dx ** 2 + dy ** 2) ** 0.5 / 1e6

    hits = []
    for h in HOT:
        if h not in info:
            continue
        for s in SENSITIVE:
            if s not in info or frozenset((h, s)) in ACCEPTED:
                continue
            g = gap(h, s)
            if g <= GAP_MM:
                hits.append((g, h, HOT[h], s, SENSITIVE[s], info[h][1], info[s][1]))
    hits.sort()

    if not hits:
        print("HEAT CHECK: clear (no hot/heat-sensitive parts too close)")
        return
    print(f"HEAT CHECK: {len(hits)} pair(s) too close:")
    for g, h, hd, s, sd, sh, ss in hits:
        side = "same side" if sh == ss else "OPPOSITE sides (through-board)"
        print(f"  {h} ({hd}) <-> {s} ({sd}): gap {g:.1f}mm, {side}")


if __name__ == "__main__":
    main()
