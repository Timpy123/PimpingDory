import os
#!/usr/bin/env python3
"""Trial one J5 pin map: patch netlist, rebuild board, route, report.

Usage: pinmap_trial.py <candidate-index> [passes]
Candidate 0 = current map (baseline). Prints: CAND n unrouted=U vias=V
Run from kicad/.

Footprint numbering (PinSocket_2x06): columns are pin pairs (1,2)(3,4)...(11,12);
odd pins = north row (y2.5), even = south row (y5.0). After the bottom-side flip
column 1 sits at x=25.8 (east) and column 6 at x=13.1 (west).
"""
import re
import subprocess
import sys

# nets to place: 9 signals + 3 extra GND
# column geometry: c1 east ... c6 west; west columns face most targets
# (I2C pullups, piezo driver, WS resistor, switch circuit all sit west/mid).

CANDIDATES = {
    # 0: current (baseline)
    0: {1: "3V3", 2: "I2C_SDA", 3: "I2C_SCL", 4: "GND", 5: "PIEZO_P", 6: "PIEZO_N",
        7: "GND", 8: "VBAT_SW", 9: "WS_DATA", 10: "GND", 11: "REED", 12: "GND"},
    # 1: signals west->east by traffic; piezo pair shares column 4; GND fills east
    1: {11: "I2C_SDA", 12: "I2C_SCL", 9: "3V3", 10: "WS_DATA",
        7: "PIEZO_P", 8: "PIEZO_N", 5: "VBAT_SW", 6: "GND",
        3: "REED", 4: "GND", 1: "GND", 2: "GND"},
    # 2: as 1 but VBAT_SW east (bottom-north switch circuit is mid-x), REED west
    2: {11: "I2C_SDA", 12: "I2C_SCL", 9: "3V3", 10: "WS_DATA",
        7: "PIEZO_P", 8: "PIEZO_N", 5: "REED", 6: "GND",
        3: "VBAT_SW", 4: "GND", 1: "GND", 2: "GND"},
    # 3: I2C center, power rails at ends, piezo column 5
    3: {1: "VBAT_SW", 2: "GND", 3: "WS_DATA", 4: "REED",
        5: "I2C_SDA", 6: "I2C_SCL", 7: "3V3", 8: "GND",
        9: "PIEZO_P", 10: "PIEZO_N", 11: "GND", 12: "GND"},
    # 4: mirror of current (everything flipped east<->west)
    4: {11: "3V3", 12: "I2C_SDA", 9: "I2C_SCL", 10: "GND", 7: "PIEZO_P", 8: "PIEZO_N",
        5: "GND", 6: "VBAT_SW", 3: "WS_DATA", 4: "GND", 1: "REED", 2: "GND"},
    # 5: north row = digital (SDA SCL WS 3V3 REED GND), south row = power/analog
    5: {1: "I2C_SDA", 3: "I2C_SCL", 5: "WS_DATA", 7: "3V3", 9: "REED", 11: "GND",
        2: "GND", 4: "GND", 6: "VBAT_SW", 8: "GND", 10: "PIEZO_P", 12: "PIEZO_N"},
    # 6: like 5, rows swapped
    6: {2: "I2C_SDA", 4: "I2C_SCL", 6: "WS_DATA", 8: "3V3", 10: "REED", 12: "GND",
        1: "GND", 3: "GND", 5: "VBAT_SW", 7: "GND", 9: "PIEZO_P", 11: "PIEZO_N"},
    # 7: piezo east column 1 (loom exit), I2C west, GND spine center
    7: {1: "PIEZO_P", 2: "PIEZO_N", 3: "VBAT_SW", 4: "WS_DATA",
        5: "GND", 6: "GND", 7: "GND", 8: "REED",
        9: "3V3", 10: "GND", 11: "I2C_SDA", 12: "I2C_SCL"},
    # 8: grounds as EMI separators between every signal group
    8: {1: "VBAT_SW", 2: "WS_DATA", 3: "GND", 4: "GND",
        5: "PIEZO_P", 6: "PIEZO_N", 7: "GND", 8: "GND",
        9: "I2C_SDA", 10: "I2C_SCL", 11: "3V3", 12: "REED"},
    # 9: sorted by target y: north-targets (REED/VBAT/3V3) east, mid (I2C) center,
    #    south-targets (piezo drv, WS) west
    9: {1: "REED", 2: "VBAT_SW", 3: "3V3", 4: "GND",
        5: "I2C_SDA", 6: "I2C_SCL", 7: "GND", 8: "GND",
        9: "WS_DATA", 10: "GND", 11: "PIEZO_P", 12: "PIEZO_N"},
    # 10: current but piezo pair moved to one column (5,6), WS/REED west
    10: {1: "3V3", 2: "GND", 3: "I2C_SDA", 4: "I2C_SCL", 5: "PIEZO_P", 6: "PIEZO_N",
         7: "VBAT_SW", 8: "GND", 9: "GND", 10: "WS_DATA", 11: "REED", 12: "GND"},
}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_paths import FR, KICAD_PY as KJP, require   # noqa: E402
require("KICAD_PY", "FR")


def apply_map(cand):
    """Rewrite J5 node pin assignments in netlist.net."""
    text = open("netlist.net.orig").read()
    # strip existing J5 nodes
    text = re.sub(r'\n\s*\(node \(ref "J5"\) \(pin "\d+"\)[^)]*\)', "", text)
    # insert node into each net block
    for pin, net in cand.items():
        pat = r'(\(net \(code "\d+"\) \(name "' + re.escape(net) + r'"\) \(class "[^"]*"\))'
        m = re.search(pat, text)
        assert m, net
        text = text.replace(m.group(1), m.group(1) +
                            f'\n      (node (ref "J5") (pin "{pin}") (pintype "passive"))', 1)
    open("netlist.net", "w").write(text)


def run(idx, passes):
    apply_map(CANDIDATES[idx])
    subprocess.run(["python3", "tools/pcb_gen.py"], capture_output=True, check=True)
    flip = ("import pcbnew,os,sys\nos.chdir('.')\nsys.path.insert(0,'tools')\nimport pcb_gen\n"
            "b=pcbnew.LoadBoard('detector-hat.kicad_pcb')\n"
            "for r in sorted(pcb_gen.BOTTOM):\n"
            "    f=b.FindFootprintByReference(r)\n"
            "    if f and f.GetLayerName()!='B.Cu':\n"
            "        rot=f.GetOrientationDegrees(); f.Flip(f.GetPosition(),True); f.SetOrientationDegrees(rot)\n"
            "b.BuildListOfNets()\n"
            "import pcbnew as p\np.ExportSpecctraDSN(b,'trial.dsn')\n")
    subprocess.run([KJP, "-c", flip], capture_output=True, check=True)
    out = subprocess.run([FR, "-de", "trial.dsn", "-do", "trial.ses",
                          "-mp", str(passes)], capture_output=True, text=True, timeout=900)
    m = re.search(r'\((\d+) unrouted', out.stdout + out.stderr)
    unrouted = int(m.group(1)) if m else -1
    if unrouted == -1 and "0 unrouted" not in out.stdout:
        m2 = re.search(r'session completed.*', out.stdout + out.stderr)
        unrouted = 0 if (m2 and "unrouted" not in m2.group(0)) else -1
    vias = open("trial.ses").read().count("(via ") if unrouted >= 0 else -1
    print(f"CAND {idx} unrouted={unrouted} vias={vias}", flush=True)


if __name__ == "__main__":
    idx = int(sys.argv[1])
    passes = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    run(idx, passes)
