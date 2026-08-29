#!/usr/bin/env python3
"""Grid A*/Dijkstra router for the handful of nets Freerouting can't close,
run against the REAL current board (existing tracks/pads as obstacles).
Run with KiCad's python from kicad/, board already has the bulk route
imported. Adds tracks+vias directly via pcbnew and saves.
"""
import pcbnew
import heapq
import math
import sys

G = 0.2  # mm, fine grid since this only handles a few nets
NX, NY = int(42 / G) + 1, int(135 / G) + 1
VIA_COST = 40
CLR = 0.25  # mm clearance added around every obstacle

b = pcbnew.LoadBoard("detector-hat.kicad_pcb")


def cell(x, y):
    return int(round(x / G)), int(round(y / G))


class Grid:
    def __init__(self):
        self.occ = [[[0] * NY for _ in range(NX)] for _ in range(2)]
        for L in range(2):
            for ix in range(NX):
                for iy in range(NY):
                    if ix < 5 or iy < 5 or ix >= NX - 5 or iy >= NY - 5:
                        self.occ[L][ix][iy] = -1

    def block_rect(self, x0, y0, x1, y1, layers, net=0):
        x0 -= CLR; y0 -= CLR; x1 += CLR; y1 += CLR
        for ix in range(max(0, int(x0 / G)), min(NX, int(x1 / G) + 2)):
            for iy in range(max(0, int(y0 / G)), min(NY, int(y1 / G) + 2)):
                cx, cy = ix * G, iy * G
                if x0 <= cx <= x1 and y0 <= cy <= y1:
                    for L in layers:
                        cur = self.occ[L][ix][iy]
                        if cur == 0:
                            self.occ[L][ix][iy] = net if net else -1
                        elif cur != net:
                            self.occ[L][ix][iy] = -1

    def passable(self, L, ix, iy, net):
        v = self.occ[L][ix][iy]
        return v == 0 or v == net

    def mark(self, L, ix, iy, net):
        if self.occ[L][ix][iy] == 0:
            self.occ[L][ix][iy] = net


def layer_idx(fp_layer_ok_F, fp_layer_ok_B):
    Ls = []
    if fp_layer_ok_F: Ls.append(0)
    if fp_layer_ok_B: Ls.append(1)
    return Ls


grid = Grid()
net_of_code = {}
for net in b.GetNetsByName().values():
    net_of_code[net.GetNetCode()] = net.GetNetname()

# obstacles: every pad (both layers it touches), inflated
for fp in b.Footprints():
    for p in fp.Pads():
        pos = p.GetPosition()
        x, y = pos.x / 1e6, pos.y / 1e6
        hw, hh = p.GetSizeX() / 2e6, p.GetSizeY() / 2e6
        Ls = layer_idx(p.IsOnLayer(pcbnew.F_Cu), p.IsOnLayer(pcbnew.B_Cu))
        code = p.GetNetCode()
        grid.block_rect(x - hw, y - hh, x + hw, y + hh, Ls, code)

# obstacles: every existing track/via
for t in b.Tracks():
    code = t.GetNetCode()
    if isinstance(t, pcbnew.PCB_VIA):
        pos = t.GetPosition()
        x, y = pos.x / 1e6, pos.y / 1e6
        r = t.GetWidth() / 2e6
        grid.block_rect(x - r, y - r, x + r, y + r, [0, 1], code)
    else:
        s, e = t.GetStart(), t.GetEnd()
        L = 0 if t.GetLayer() == pcbnew.F_Cu else 1
        n = max(1, int(math.hypot(e.x - s.x, e.y - s.y) / (G * 1e6)))
        w = t.GetWidth() / 2e6
        for i in range(n + 1):
            x = (s.x + (e.x - s.x) * i / n) / 1e6
            y = (s.y + (e.y - s.y) * i / n) / 1e6
            grid.block_rect(x - w, y - w, x + w, y + w, [L], code)

MOVES = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
         (1, 1, 1.42), (1, -1, 1.42), (-1, 1, 1.42), (-1, -1, 1.42)]


def route(net_name, sx, sy, tx, ty):
    code = b.GetNetsByName()[net_name].GetNetCode()
    start = (0, *cell(sx, sy))
    goal = (0, *cell(tx, ty))
    # allow starting even if the exact pad cell is marked obstacle (it's our own pad)
    for L in (0, 1):
        for dx, dy in ((0, 0),):
            pass
    dist = {start: 0}
    prev = {}
    pq = [(0, start)]
    goals = {goal, (1, goal[1], goal[2])}
    starts_alt = {start, (1, start[1], start[2])}
    for s in list(starts_alt):
        if s not in dist:
            dist[s] = 0
            heapq.heappush(pq, (0, s))
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, 1e18):
            continue
        if u in goals:
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
            if not grid.passable(L, jx, jy, code):
                continue
            v = (L, jx, jy)
            nd = d + c
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
        M = 1 - L
        if grid.passable(M, ix, iy, code):
            v = (M, ix, iy)
            nd = d + VIA_COST
            if nd < dist.get(v, 1e18):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(pq, (nd, v))
    return None


def commit(net_name, path, width=0.3):
    code = b.GetNetsByName()[net_name].GetNetCode()
    net = b.GetNetsByName()[net_name]
    run_start = path[0]
    for i in range(1, len(path) + 1):
        prev = path[i - 1]
        cur = path[i] if i < len(path) else None
        ended = cur is None or cur[0] != prev[0]
        if not ended and i >= 2 and cur[0] == path[i - 2][0]:
            d1 = (prev[1] - path[i - 2][1], prev[2] - path[i - 2][2])
            d2 = (cur[1] - prev[1], cur[2] - prev[2])
            if d1 != d2:
                ended = True
        if ended and prev != run_start:
            if run_start[1:] != prev[1:]:
                t = pcbnew.PCB_TRACK(b)
                t.SetStart(pcbnew.VECTOR2I(int(run_start[1] * G * 1e6), int(run_start[2] * G * 1e6)))
                t.SetEnd(pcbnew.VECTOR2I(int(prev[1] * G * 1e6), int(prev[2] * G * 1e6)))
                t.SetWidth(int(width * 1e6))
                t.SetLayer(pcbnew.F_Cu if prev[0] == 0 else pcbnew.B_Cu)
                t.SetNet(net)
                b.Add(t)
            run_start = prev
        if cur is not None and cur[0] != prev[0]:
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I(int(prev[1] * G * 1e6), int(prev[2] * G * 1e6)))
            v.SetDrill(int(0.4e6)); v.SetWidth(int(0.8e6)); v.SetNet(net)
            b.Add(v)
            run_start = cur
    # mark occupied so later nets in this same run don't cross it
    for (L, ix, iy) in path:
        grid.mark(L, ix, iy, code)


jobs = [
    ("3V3", 4.225, 34.725, 25.8, 2.5),
    ("I2C_SCL", 6.825, 58.0, 23.26, 2.5),
    ("PIEZO_N", 20.72, 5.04, 4.225, 36.675),
]

ok = 0
for (name, sx, sy, tx, ty) in jobs:
    p = route(name, sx, sy, tx, ty)
    if p is None:
        print(f"FAILED: {name}")
        continue
    commit(name, p)
    ok += 1
    print(f"routed: {name} ({len(p)} cells)")

print(f"{ok}/{len(jobs)} routed")
pcbnew.SaveBoard("detector-hat.kicad_pcb", b)
