#!/usr/bin/env python3
"""Name the actual unrouted net(s) after a Freerouting pass.

DRC's unconnected_items list is noisy (GND zone-lobe fragments dominate it)
and sometimes doesn't surface the real gap at all (a net can look "connected"
via zone touch without an actual track/via, or DRC just doesn't flag it).
This does a direct copper-graph check instead: union-find over every
track/via per net (GND excluded, since it's pour-connected by design), then
reports any net whose pads don't all land in one connected group.

Run with KiCad's python from kicad/, after the SES import + zone fill:
    python3 tools/check_unrouted.py
"""
import pcbnew


def key(pt, layer):
    return (round(pt.x / 1000), round(pt.y / 1000), layer)


def find(parent, x):
    while parent.get(x, x) != x:
        x = parent[x]
    return x


def union(parent, a, b):
    ra, rb = find(parent, a), find(parent, b)
    if ra != rb:
        parent[ra] = rb


def main():
    b = pcbnew.LoadBoard("detector-hat.kicad_pcb")
    parent = {}

    # THT pads bridge F.Cu/B.Cu just like a via (plated through-hole) — union
    # both layer-keys at every such pad, or multi-layer connectors (J3, U1...)
    # look split across layers even when fully routed.
    for fp in b.Footprints():
        for p in fp.Pads():
            if p.IsOnLayer(pcbnew.F_Cu) and p.IsOnLayer(pcbnew.B_Cu):
                pos = p.GetPosition()
                a, c = key(pos, "F"), key(pos, "B")
                parent.setdefault(a, a)
                parent.setdefault(c, c)
                union(parent, a, c)

    by_net = {}
    for t in b.Tracks():
        net = t.GetNetname()
        if net in ("GND", "", None):
            continue
        by_net.setdefault(net, []).append(t)

    for items in by_net.values():
        for t in items:
            if isinstance(t, pcbnew.PCB_VIA):
                p = t.GetPosition()
                a, c = key(p, "F"), key(p, "B")
                parent.setdefault(a, a)
                parent.setdefault(c, c)
                union(parent, a, c)
            else:
                L = "F" if t.GetLayer() == pcbnew.F_Cu else "B"
                s, e = key(t.GetStart(), L), key(t.GetEnd(), L)
                parent.setdefault(s, s)
                parent.setdefault(e, e)
                union(parent, s, e)

    pads_by_net = {}
    for fp in b.Footprints():
        for p in fp.Pads():
            n = p.GetNetname()
            if n in ("GND", "", None):
                continue
            pads_by_net.setdefault(n, []).append(
                (fp.GetReference(), p.GetName(), p.GetPosition(),
                 p.IsOnLayer(pcbnew.F_Cu), p.IsOnLayer(pcbnew.B_Cu)))

    bad = []
    for net, pads in pads_by_net.items():
        if len(pads) < 2:
            continue
        groups = set()
        for (ref, pname, pos, onF, onB) in pads:
            ks = []
            if onF:
                ks.append(key(pos, "F"))
            if onB:
                ks.append(key(pos, "B"))
            g = None
            for k in ks:
                if k in parent:
                    g = find(parent, k)
                    break
            groups.add(g)
        if len(groups) > 1 or None in groups:
            bad.append((net, [(r, pn) for (r, pn, *_ ) in pads]))

    if not bad:
        print("no unrouted nets found (all copper-connected)")
    else:
        print(f"{len(bad)} unrouted net(s):")
        for net, pads in bad:
            print(f"  {net}: " + ", ".join(f"{r}.{pn}" for r, pn in pads))


if __name__ == "__main__":
    main()
