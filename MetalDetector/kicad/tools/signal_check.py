#!/usr/bin/env python3
"""List genuinely-open signal connections from a kicad-cli DRC json report.

KiCad's DRC is authoritative (it's what draws the ratsnest), so we parse it
instead of guessing connectivity ourselves. GND is pour-connected by design,
so unconnected_items whose endpoints are all GND (zone-lobe noise) are dropped.

Usage: python3 signal_check.py <drc.json>
"""
import json
import re
import sys


def net_of(desc):
    m = re.search(r"\[([^\]]+)\]", desc)
    return m.group(1) if m else "?"


def main():
    d = json.load(open(sys.argv[1]))
    rows = []
    for u in d.get("unconnected_items", []):
        descs = [i.get("description", "") for i in u.get("items", [])]
        nets = [net_of(s) for s in descs]
        if all(n == "GND" for n in nets):
            continue  # pour handles GND; zone-lobe noise
        net = next((n for n in nets if n != "GND"), nets[0] if nets else "?")
        pad = next((s for s in descs if s.startswith("Pad") or "Pad" in s),
                   descs[0] if descs else "")
        m = re.search(r"Pad (\S+) \S+ of (\S+)", pad)
        loc = f"{m.group(2)} pad {m.group(1)}" if m else pad
        lm = re.search(r"length ([\d.]+) mm", " ".join(descs))
        gap = f" ({float(lm.group(1)):.2f}mm short)" if lm else ""
        rows.append((net, loc, gap))

    if not rows:
        print("signal gaps (KiCad DRC): none")
    else:
        print(f"signal gaps (KiCad DRC): {len(rows)}")
        for net, loc, gap in rows:
            print(f"  {net} — {loc}{gap}")


if __name__ == "__main__":
    main()
