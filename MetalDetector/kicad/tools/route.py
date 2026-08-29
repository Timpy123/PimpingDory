#!/usr/bin/env python3
"""Grid A* autorouter for the detector HAT board.

Reads detector-hat.kicad_pcb (placed, unrouted), routes all nets as tracks
(GND too — pours are bonus copper, not the sole path), writes the routed board
in place. Verify with kicad-cli pcb drc afterwards; iterate on failures.

Model: 0.5 mm grid, layers F.Cu/B.Cu, manhattan+diagonal moves, via cost.
Widths by net class (fat TX/power, thin signals). Approximate clearances —
DRC is the authority; unroutable connections are reported, not hidden.
"""

import math
import re
import heapq

BOARD_W, BOARD_H = 90.0, 65.0
G = 0.5                      # grid pitch mm
NX, NY = int(BOARD_W / G) + 1, int(BOARD_H / G) + 1
EDGE = 2                     # keep-out cells from board edge
VIA_COST = 24
VIA_SIZE, VIA_DRILL = 0.6, 0.3

WIDTH = {"COIL_A": 1.0, "V12_TX": 1.0}
FAT = {"V9_SND", "VBAT_SW", "VBAT_P", "VBAT_RAW", "VSYS_PICO", "VBUS_C",
       "BAT_NEG", "FET_D", "PIEZO_P", "PIEZO_N", "SW1", "SW2"}
ORDER_FIRST = ["COIL_A", "V12_TX", "SW1", "SW2", "V9_SND", "VBAT_SW", "VBAT_P",
               "VBAT_RAW", "VSYS_PICO", "VBUS_C", "BAT_NEG", "FET_D",
               "PIEZO_P", "PIEZO_N"]


def width_of(net):
    if net in WIDTH:
        return WIDTH[net]
    if net in FAT:
        return 0.8
    if net == "GND":
        return 0.5
    return 0.3


# ---- board parsing -----------------------------------------------------------

def balanced(text, start):
    depth = 0
    for j in range(start, len(text)):
        if text[j] == '(':
            depth += 1
        elif text[j] == ')':
            depth -= 1
            if depth == 0:
                return j + 1
    raise ValueError("unbalanced")


def parse_board(path):
    text = open(path).read()
    pads = []  # (x, y, sx, sy, layers, netcode, tht)
    for m in re.finditer(r'\(footprint "', text):
        end = balanced(text, m.start())
        fp = text[m.start():end]
        at = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', fp)
        fx, fy, fr = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
        ca, sa = math.cos(math.radians(fr)), math.sin(math.radians(fr))
        p = 0
        while True:
            pm = re.search(r'\(pad\s+"([^"]*)"\s+(\w+)\s+\w+', fp[p:])
            if not pm:
                break
            ps = p + pm.start()
            pe = balanced(fp, ps)
            block = fp[ps:pe]
            pat = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', block)
            px, py = float(pat.group(1)), float(pat.group(2))
            gx = fx + px * ca + py * sa
            gy = fy - px * sa + py * ca
            size = re.search(r'\(size ([-\d.]+) ([-\d.]+)\)', block)
            sx, sy = float(size.group(1)), float(size.group(2))
            if abs(fr % 180) == 90:
                sx, sy = sy, sx
            net = re.search(r'\(net (\d+)', block)
            netcode = int(net.group(1)) if net else 0
            tht = pm.group(2) in ("thru_hole", "np_thru_hole")
            layers = re.search(r'\(layers ([^)]*)\)', block).group(1)
            pads.append((gx, gy, sx, sy, layers, netcode, tht))
            p = pe
    netnames = dict((int(c), n) for c, n in
                    re.findall(r'^  \(net (\d+) "([^"]*)"\)', text, re.M))
    return text, pads, netnames


# ---- grid --------------------------------------------------------------------

def cell(x, y):
    return int(round(x / G)), int(round(y / G))


class Grid:
    def __init__(self):
        # occ[layer][ix][iy] = netcode or -1 for hard obstacle, 0 free
        self.occ = [[[0] * NY for _ in range(NX)] for _ in range(2)]
        for L in range(2):
            for ix in range(NX):
                for iy in range(NY):
                    if ix < EDGE or iy < EDGE or ix >= NX - EDGE or iy >= NY - EDGE:
                        self.occ[L][ix][iy] = -1

    def block_pad(self, x, y, sx, sy, layers, netcode, tht):
        infl = 0.55
        x0, x1 = x - sx / 2 - infl, x + sx / 2 + infl
        y0, y1 = y - sy / 2 - infl, y + sy / 2 + infl
        Ls = [0, 1] if (tht or "*.Cu" in layers) else ([0] if "F.Cu" in layers else [1])
        for ix in range(max(0, int(x0 / G)), min(NX, int(x1 / G) + 2)):
            for iy in range(max(0, int(y0 / G)), min(NY, int(y1 / G) + 2)):
                cx, cy = ix * G, iy * G
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    for L in Ls:
                        cur = self.occ[L][ix][iy]
                        self.occ[L][ix][iy] = netcode if (cur == 0 and netcode) else \
                            (cur if cur == netcode else -1) if cur else -1

    def passable(self, L, ix, iy, net):
        v = self.occ[L][ix][iy]
        return v == 0 or v == net

    def mark(self, L, ix, iy, net, fat=False):
        rng = [(0, 0)] if not fat else [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]
        for dx, dy in rng:
            jx, jy = ix + dx, iy + dy
            if 0 <= jx < NX and 0 <= jy < NY and self.occ[L][jx][jy] == 0:
                self.occ[L][jx][jy] = net


MOVES = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
         (1, 1, 1.42), (1, -1, 1.42), (-1, 1, 1.42), (-1, -1, 1.42)]


def dijkstra(grid, net, starts, goals):
    """starts/goals: sets of (L, ix, iy). Returns path list or None."""
    dist = {}
    prev = {}
    pq = []
    for s in starts:
        dist[s] = 0
        heapq.heappush(pq, (0, s))
    goalset = goals
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1e18):
            continue
        if u in goalset:
            path = [u]
            while u in prev:
                u = prev[u]
                path.append(u)
            return path[::-1]
        L, ix, iy = u
        for dx, dy, c in MOVES:
            jx, jy = ix + dx, iy + dy
            if not (0 <= jx < NX and 0 <= jy < NY):
                continue
            if not grid.passable(L, jx, jy, net):
                continue
            v = (L, jx, jy)
            nd = d + c
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
        # via
        M = 1 - L
        if grid.passable(M, ix, iy, net):
            v = (M, ix, iy)
            nd = d + VIA_COST
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return None


def path_to_geometry(path, net, netname, grid):
    """Collapse path cells to segments + vias; mark cells as owned by net."""
    segs, vias = [], []
    fat = width_of(netname) >= 0.5
    w = width_of(netname)
    run_start = path[0]
    for i in range(1, len(path) + 1):
        prev = path[i - 1]
        cur = path[i] if i < len(path) else None
        ended = cur is None or cur[0] != prev[0]
        # direction change?
        if not ended and i >= 2 and cur[0] == path[i - 2][0]:
            d1 = (prev[1] - path[i - 2][1], prev[2] - path[i - 2][2])
            d2 = (cur[1] - prev[1], cur[2] - prev[2])
            if d1 != d2:
                ended = True
        if ended and prev != run_start:
            segs.append((run_start[1] * G, run_start[2] * G,
                         prev[1] * G, prev[2] * G, w, run_start[0]))
            run_start = prev
        if cur is not None and cur[0] != prev[0]:
            vias.append((prev[1] * G, prev[2] * G))
            run_start = cur
    for (L, ix, iy) in path:
        grid.mark(L, ix, iy, net, fat)
    for (vx, vy) in vias:
        for L in range(2):
            grid.mark(L, cell(vx, vy)[0], cell(vx, vy)[1], net, True)
    return segs, vias


def main():
    text, pads, netnames = parse_board("detector-hat.kicad_pcb")
    grid = Grid()
    for p in pads:
        grid.block_pad(*p)

    # group pad cells per net
    net_pads = {}
    for (x, y, sx, sy, layers, net, tht) in pads:
        if net == 0:
            continue
        ix, iy = cell(x, y)
        Ls = [0, 1] if (tht or "*.Cu" in layers) else ([0] if "F.Cu" in layers else [1])
        for L in Ls:
            net_pads.setdefault(net, []).append((L, ix, iy))

    order = [c for n in ORDER_FIRST for c, name in netnames.items() if name == n]
    order += [c for c in sorted(net_pads) if c not in order and netnames.get(c) != "GND"]
    order += [c for c, n in netnames.items() if n == "GND"]

    all_segs, all_vias, failed = [], [], []
    for net in order:
        cells = net_pads.get(net, [])
        if len(cells) < 2:
            continue
        name = netnames.get(net, "?")
        connected = {cells[0]}
        remaining = cells[1:]
        while remaining:
            path = dijkstra(grid, net, set(connected), set(remaining))
            if path is None:
                failed.append((name, len(remaining)))
                break
            endpoint = path[-1]
            segs, vias = path_to_geometry(path, net, name, grid)
            for s in segs:
                all_segs.append(s + (net,))
            for v in vias:
                all_vias.append(v + (net,))
            connected.update(path)
            remaining = [c for c in remaining if c != endpoint]

    geo = ""
    for (x1, y1, x2, y2, w, L, net) in all_segs:
        layer = "F.Cu" if L == 0 else "B.Cu"
        geo += (f'  (segment (start {x1:.2f} {y1:.2f}) (end {x2:.2f} {y2:.2f})'
                f' (width {w}) (layer "{layer}") (net {net}))\n')
    for (x, y, net) in all_vias:
        geo += (f'  (via (at {x:.2f} {y:.2f}) (size {VIA_SIZE}) (drill {VIA_DRILL})'
                f' (layers "F.Cu" "B.Cu") (net {net}))\n')

    out = text.rstrip()
    assert out.endswith(')')
    out = out[:-1] + geo + ')\n'
    open("detector-hat.kicad_pcb", "w").write(out)
    print(f"routed: {len(all_segs)} segments, {len(all_vias)} vias")
    if failed:
        print("FAILED nets:", failed)


if __name__ == "__main__":
    main()
