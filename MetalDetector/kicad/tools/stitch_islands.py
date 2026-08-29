#!/usr/bin/env python3
"""Join isolated GND pour islands to the main GND network with the minimum
number of vias — one per island where possible, placed only where a real
island exists (no blanket stitching grid).

Method per round: fill zones, build a union-find over all GND copper
(pour outlines, pads, tracks, vias; THT pads and vias bridge layers),
identify the component holding the most GND pads as "main", then for every
other component that contains at least one GND pad, place a single GND via
at a spot that (a) lands well inside the island copper, (b) lands inside
main-component copper on the opposite layer, and (c) keeps clearance from
all non-GND copper and holes. Refill and repeat until no pad-bearing
islands remain (pours shift as vias are added, so islands can merge).

Run with KiCad's python from kicad/ after SES import + zone fill.
"""
import math

import pcbnew

VIA_D, VIA_DRILL = 0.6, 0.3
MARGIN = 0.35        # mm the via center must sit inside copper on both layers
CLEAR = 0.2          # mm clearance to non-GND copper (Power class rule; Default is 0.15)
HV_CLEAR = 0.6       # mm clearance against HV_Flyback copper (COIL_A)
HOLE_CLEAR = 0.60    # mm center-to-edge margin against other drilled items
MAX_ROUNDS = 5

M = 1e6


def find(parent, x):
    while parent.get(x, x) != x:
        x = parent[x]
    return x


def union(parent, a, b):
    ra, rb = find(parent, a), find(parent, b)
    if ra != rb:
        parent[ra] = rb


def build(b):
    """Return (parent, outline_units, pad_nodes) for current fill state."""
    parent = {}
    units = []  # (key, polyset, layer)
    for z in b.Zones():
        if z.GetNetname() != "GND":
            continue
        layer = pcbnew.F_Cu if z.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
        poly = z.GetFilledPolysList(layer)
        for i in range(poly.OutlineCount()):
            key = ("o", len(units))
            units.append((key, poly.UnitSet(i), layer))
            parent.setdefault(key, key)

    def outline_hits(shape, layer):
        return [k for (k, u, ly) in units if ly == layer and u.Collide(shape, 0)]

    pad_nodes = {}
    for fp in b.Footprints():
        for p in fp.Pads():
            if p.GetNetname() != "GND":
                continue
            key = ("p", fp.GetReference(), p.GetName())
            parent.setdefault(key, key)
            pad_nodes[key] = p
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                if not p.IsOnLayer(layer):
                    continue
                for k in outline_hits(p.GetEffectiveShape(layer), layer):
                    union(parent, key, k)

    gnd_tracks = [t for t in b.Tracks() if t.GetNetname() == "GND"]
    for idx, t in enumerate(gnd_tracks):
        key = ("t", idx)
        parent.setdefault(key, key)
        if isinstance(t, pcbnew.PCB_VIA):
            layers = (pcbnew.F_Cu, pcbnew.B_Cu)
        else:
            layers = (t.GetLayer(),)
        for layer in layers:
            for k in outline_hits(t.GetEffectiveShape(layer), layer):
                union(parent, key, k)
        # track/via touching a GND pad joins it
        for pkey, p in pad_nodes.items():
            for layer in layers:
                if p.IsOnLayer(layer) and \
                   t.GetEffectiveShape(layer).Collide(p.GetEffectiveShape(layer), 0):
                    union(parent, key, pkey)
                    break
    return parent, units, pad_nodes


def obstacle_ok(b, pt):
    """Candidate via at pt must clear all non-GND copper and all holes."""
    circle = pcbnew.SHAPE_CIRCLE(pt, int(VIA_D / 2 * M))
    for fp in b.Footprints():
        for p in fp.Pads():
            near = p.GetPosition()
            if abs(near.x - pt.x) > 4 * M or abs(near.y - pt.y) > 4 * M:
                continue
            if p.GetDrillSizeX() > 0:  # any drilled pad: hole-to-hole margin
                r = max(p.GetDrillSizeX(), p.GetDrillSizeY()) / 2 + HOLE_CLEAR * M
                if (near.x - pt.x) ** 2 + (near.y - pt.y) ** 2 < (r + VIA_DRILL / 2 * M) ** 2:
                    return False
            if p.GetNetname() != "GND":
                for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if p.IsOnLayer(layer) and \
                       p.GetEffectiveShape(layer).Collide(circle, int(CLEAR * M)):
                        return False
    for t in b.Tracks():
        near = t.GetPosition()
        if abs(near.x - pt.x) > 6 * M or abs(near.y - pt.y) > 6 * M:
            continue
        if isinstance(t, pcbnew.PCB_VIA):
            r = t.GetDrill() if t.GetDrill() > 0 else int(0.3 * M)
            if (near.x - pt.x) ** 2 + (near.y - pt.y) ** 2 < \
               (r / 2 + HOLE_CLEAR * M + VIA_DRILL / 2 * M) ** 2:
                return False
        if t.GetNetname() != "GND" and \
           t.GetEffectiveShape(t.GetLayer()).Collide(circle, int(CLEAR * M)):
            return False
    return True


def _clr(netname):
    return int((HV_CLEAR if netname == "COIL_A" else CLEAR) * M)


def stub_ok(b, a, c, layer, width=0.3):
    """A short GND stub track from a to c on layer must clear non-GND copper."""
    seg = pcbnew.SHAPE_SEGMENT(a, c, int(width * M))
    for fp in b.Footprints():
        for p in fp.Pads():
            if p.GetNetname() == "GND":
                continue
            near = p.GetPosition()
            if abs(near.x - a.x) > 12 * M or abs(near.y - a.y) > 12 * M:
                continue
            if p.IsOnLayer(layer) and \
               p.GetEffectiveShape(layer).Collide(seg, _clr(p.GetNetname())):
                return False
    for t in b.Tracks():
        if t.GetNetname() == "GND":
            continue
        near = t.GetPosition()
        if abs(near.x - a.x) > 14 * M or abs(near.y - a.y) > 14 * M:
            continue
        if isinstance(t, pcbnew.PCB_VIA) or t.GetLayer() == layer:
            if t.GetEffectiveShape(layer).Collide(seg, _clr(t.GetNetname())):
                return False
    return True


def inside_with_margin(unit, pt):
    m = int(MARGIN * M)
    for dx, dy in ((0, 0), (m, 0), (-m, 0), (0, m), (0, -m)):
        if not unit.Contains(pcbnew.VECTOR2I(pt.x + dx, pt.y + dy)):
            return False
    return True


def main():
    b = pcbnew.LoadBoard("detector-hat.kicad_pcb")
    filler = pcbnew.ZONE_FILLER(b)
    filler.Fill(b.Zones())
    gnd = b.GetNetsByName()["GND"]
    added = []

    for rnd in range(MAX_ROUNDS):
        parent, units, pad_nodes = build(b)
        comps = {}
        for pkey in pad_nodes:
            comps.setdefault(find(parent, pkey), []).append(pkey)
        if len(comps) <= 1:
            break
        main_root = max(comps, key=lambda r: len(comps[r]))
        main_units = {"F": [], "B": []}
        for (k, u, ly) in units:
            if find(parent, k) == main_root:
                main_units["F" if ly == pcbnew.F_Cu else "B"].append(u)

        placed_this_round = 0
        for root, pads in comps.items():
            if root == main_root:
                continue
            island_units = [(u, ly) for (k, u, ly) in units if find(parent, k) == root]
            bare = not island_units  # pad(s) with no pour contact at all
            spot = None
            # candidates: ring around each stranded pad, then island-bbox grid.
            # bare mode: ring tight enough that the via barrel overlaps the pad
            # copper (that overlap IS the connection — there is no pour to land in)
            cands = []
            for pkey in pads:
                p = pad_nodes[pkey]
                c = p.GetPosition()
                if bare:
                    r = int(max(p.GetSizeX(), p.GetSizeY()) / 2 + (VIA_D / 2 - 0.15) * M)
                else:
                    r = int(max(p.GetSizeX(), p.GetSizeY()) / 2 + 0.75 * M)
                for i in range(12):
                    a = i * math.pi / 6
                    cands.append(pcbnew.VECTOR2I(int(c.x + r * math.cos(a)),
                                                 int(c.y + r * math.sin(a))))
            for (u, ly) in island_units:
                bb = u.BBox()
                step = int(0.5 * M)
                x = bb.GetLeft()
                while x <= bb.GetRight():
                    y = bb.GetTop()
                    while y <= bb.GetBottom():
                        cands.append(pcbnew.VECTOR2I(x, y))
                        y += step
                    x += step
            for pt in cands:
                if bare:
                    on_island = None
                    probe = pcbnew.SHAPE_CIRCLE(pt, int((VIA_D / 2 - 0.1) * M))
                    for pkey in pads:
                        p = pad_nodes[pkey]
                        for ly in (pcbnew.F_Cu, pcbnew.B_Cu):
                            if p.IsOnLayer(ly) and \
                               probe.Collide(p.GetEffectiveShape(ly), 0):
                                on_island = ly
                                break
                        if on_island is not None:
                            break
                else:
                    on_island = next((ly for (u, ly) in island_units
                                      if inside_with_margin(u, pt)), None)
                if on_island is None:
                    continue
                other = "B" if on_island == pcbnew.F_Cu else "F"
                if not any(inside_with_margin(u, pt) for u in main_units[other]):
                    continue
                if not obstacle_ok(b, pt):
                    continue
                spot = pt
                break
            stub = None  # (from_pt, to_pt, layer, needs_via)
            if spot is None and bare:
                # fallback: short stub track from the pad to the nearest spot
                # that reaches main copper — via only if that copper is on the
                # opposite layer.
                for pkey in pads:
                    p = pad_nodes[pkey]
                    layer = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
                    other = "B" if layer == pcbnew.F_Cu else "F"
                    same = "F" if layer == pcbnew.F_Cu else "B"
                    c = p.GetPosition()
                    grid = []
                    step = int(0.4 * M)
                    for gx in range(-20, 21):
                        for gy in range(-20, 21):
                            pt = pcbnew.VECTOR2I(c.x + gx * step, c.y + gy * step)
                            grid.append(((pt.x - c.x) ** 2 + (pt.y - c.y) ** 2, pt))
                    for _d, pt in sorted(grid, key=lambda t: t[0]):
                        # cheap pour-containment test first; stub/obstacle
                        # collision scans only run for the few points that pass
                        on_same = any(inside_with_margin(u, pt) for u in main_units[same])
                        on_other = (not on_same and
                                    any(inside_with_margin(u, pt) for u in main_units[other]))
                        if not (on_same or on_other):
                            continue
                        if not stub_ok(b, c, pt, layer):
                            continue
                        if on_same:
                            stub = (c, pt, layer, False)
                            break
                        if obstacle_ok(b, pt):
                            stub = (c, pt, layer, True)
                            break
                    if stub:
                        break
                # last resort: two segments with a layer hop — short stub on
                # the pad's layer to a via, then a stub on the other layer
                # into main copper (for pads fenced in on their own layer)
                if stub is None:
                    for pkey in pads:
                        p = pad_nodes[pkey]
                        layer = pcbnew.F_Cu if p.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
                        oly = pcbnew.B_Cu if layer == pcbnew.F_Cu else pcbnew.F_Cu
                        okey = "B" if layer == pcbnew.F_Cu else "F"
                        c = p.GetPosition()
                        v1s = []
                        r0 = int(max(p.GetSizeX(), p.GetSizeY()) / 2 + 0.65 * M)
                        for rr in (r0, r0 + int(0.5 * M), r0 + int(M)):
                            for i in range(12):
                                a = i * math.pi / 6
                                v1s.append(pcbnew.VECTOR2I(int(c.x + rr * math.cos(a)),
                                                           int(c.y + rr * math.sin(a))))
                        step = int(0.4 * M)
                        for v1 in v1s:
                            if not stub_ok(b, c, v1, layer) or not obstacle_ok(b, v1):
                                continue
                            grid = []
                            for gx in range(-20, 21):
                                for gy in range(-20, 21):
                                    pt = pcbnew.VECTOR2I(v1.x + gx * step, v1.y + gy * step)
                                    grid.append(((pt.x - v1.x) ** 2 + (pt.y - v1.y) ** 2, pt))
                            for _d, pt in sorted(grid, key=lambda t: t[0]):
                                if not any(inside_with_margin(u, pt)
                                           for u in main_units[okey]):
                                    continue
                                if stub_ok(b, v1, pt, oly):
                                    stub = (c, v1, layer, True, pt, oly)
                                    break
                            if stub:
                                break
                        if stub:
                            break
            if spot is not None or stub is not None:
                names = ",".join(f"{r}.{pn}" for (_t, r, pn) in pads)

                def add_track(a, c2, layer):
                    t = pcbnew.PCB_TRACK(b)
                    t.SetStart(a)
                    t.SetEnd(c2)
                    t.SetWidth(int(0.3 * M))
                    t.SetLayer(layer)
                    t.SetNet(gnd)
                    b.Add(t)

                if stub is not None and len(stub) == 6:
                    (a, v1, layer, _nv, pt2, oly) = stub
                    add_track(a, v1, layer)
                    add_track(v1, pt2, oly)
                    spot = v1
                elif stub is not None:
                    (a, c2, layer, needs_via) = stub
                    add_track(a, c2, layer)
                    if needs_via:
                        spot = c2
                    else:
                        added.append((c2.x / M, c2.y / M, names + " (stub, no via)"))
                        placed_this_round += 1
                if spot is not None:
                    v = pcbnew.PCB_VIA(b)
                    v.SetPosition(spot)
                    v.SetDrill(int(VIA_DRILL * M))
                    v.SetWidth(int(VIA_D * M))
                    v.SetNet(gnd)
                    b.Add(v)
                    added.append((spot.x / M, spot.y / M, names))
                    placed_this_round += 1
        filler.Fill(b.Zones())
        if placed_this_round == 0:
            break

    pcbnew.SaveBoard("detector-hat.kicad_pcb", b, True)  # skip settings: never touch .kicad_pro

    # final audit
    parent, units, pad_nodes = build(b)
    comps = {}
    for pkey in pad_nodes:
        comps.setdefault(find(parent, pkey), []).append(pkey)
    print(f"stitch vias added: {len(added)}")
    for (x, y, names) in added:
        print(f"  via at ({x:.2f}, {y:.2f}) for island [{names}]")
    if len(comps) <= 1:
        print(f"GND fully joined: 1 component, {len(pad_nodes)} GND pads")
    else:
        sizes = sorted((len(v) for v in comps.values()), reverse=True)
        print(f"REMAINING islands: {len(comps) - 1} (component sizes {sizes})")
        main_root = max(comps, key=lambda r: len(comps[r]))
        for root, pads in comps.items():
            if root != main_root:
                print("  stranded:", [f"{r}.{p}" for (_t, r, p) in pads])


if __name__ == "__main__":
    main()
