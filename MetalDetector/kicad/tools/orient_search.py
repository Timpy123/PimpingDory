#!/usr/bin/env python3
"""Orientation/side search for components whose GND pads strand.

For each candidate component, try +90/+180/+270 rotation and a side-flip.
Each trial runs the real pipeline (DSN -> Freerouting -mp 400 -> SES -> fill)
and scores (stranded GND pads, Freerouting unrouted). A trial is accepted
only if it strictly reduces stranded pads, or ties and cuts unrouted by >=2
(Freerouting is noisy run-to-run, single-count differences mean nothing).

Accepted flips are persisted into pcb_gen.py's BOTTOM set, rotations into
PLACE via sync_place.py. Ends by running the full standard pipeline
(regen -> flip -> route -> stitch -> silk -> sync) and printing a summary.

Run with KiCad's python from kicad/. Takes ~20-30 min.
"""
import os
import re
import shutil
import subprocess
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stitch_islands import build, find  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kicad_paths import FR, KICAD_CLI, require   # noqa: E402
require("FR", "KICAD_CLI")
PY = sys.executable

COMPS = ["C20", "U1", "U3", "U4", "C5", "R43", "Q2"]
TRIALS = [("rot", 90), ("rot", 180), ("rot", 270), ("flip", 0)]


def run_freerouting(dsn, ses):
    try:
        r = subprocess.run([FR, "-de", dsn, "-do", ses, "-mp", "400"],
                           capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return None
    un = None
    for line in (r.stdout + r.stderr).splitlines():
        m = re.search(r"session completed.*\((\d+) unrouted", line)
        if m:
            un = int(m.group(1))
    return un


def stranded_pads(b):
    parent, units, pad_nodes = build(b)
    comps = {}
    for pk in pad_nodes:
        comps.setdefault(find(parent, pk), []).append(pk)
    if not comps:
        return 0
    return sum(len(v) for v in comps.values()) - max(len(v) for v in comps.values())


def evaluate(cfg, tag):
    shutil.copy("trial_base.kicad_pcb", "trial_work.kicad_pcb")
    b = pcbnew.LoadBoard("trial_work.kicad_pcb")
    for ref, (kind, arg) in cfg.items():
        fp = b.FindFootprintByReference(ref)
        if kind == "rot":
            fp.SetOrientationDegrees(fp.GetOrientationDegrees() + arg)
        else:
            fp.Flip(fp.GetPosition(), False)
    pcbnew.ExportSpecctraDSN(b, "trial.dsn")
    pcbnew.SaveBoard("trial_work.kicad_pcb", b)
    un = run_freerouting("trial.dsn", "trial.ses")
    if un is None:
        print(f"  {tag}: freerouting failed", flush=True)
        return (999, 999)
    b = pcbnew.LoadBoard("trial_work.kicad_pcb")
    pcbnew.ImportSpecctraSES(b, "trial.ses")
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    s = stranded_pads(b)
    print(f"  {tag}: stranded={s} unrouted={un}", flush=True)
    return (s, un)


def better(new, best):
    return new[0] < best[0] or (new[0] == best[0] and new[1] <= best[1] - 2)


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import pcb_gen  # auto-syncs live positions on import
    pcb_gen.main()

    b = pcbnew.LoadBoard("detector-hat.kicad_pcb")
    for fp in b.Footprints():
        if (fp.GetReference() in pcb_gen.BOTTOM) != fp.IsFlipped():
            fp.Flip(fp.GetPosition(), False)
    for t in list(b.Tracks()):
        b.RemoveNative(t)
    pcbnew.SaveBoard("trial_base.kicad_pcb", b)

    print("baseline:", flush=True)
    baseline = evaluate({}, "as-is")
    accepted = {}
    for ref in COMPS:
        best, best_trial = baseline, None
        for trial in TRIALS:
            cfg = dict(accepted)
            cfg[ref] = trial
            score = evaluate(cfg, f"{ref} {trial[0]}{trial[1] or ''}")
            if better(score, best):
                best, best_trial = score, trial
        if best_trial is not None:
            accepted[ref] = best_trial
            baseline = best
            print(f"ACCEPT {ref}: {best_trial} -> {best}", flush=True)
        else:
            print(f"KEEP {ref} as-is (best {baseline})", flush=True)

    print("accepted changes:", accepted, flush=True)

    # persist: apply accepted config to the base board and save as the live
    # board (auto-sync + sync_place pick rotations up from there)
    shutil.copy("trial_base.kicad_pcb", "trial_work.kicad_pcb")
    b = pcbnew.LoadBoard("trial_work.kicad_pcb")
    flips = []
    for ref, (kind, arg) in accepted.items():
        fp = b.FindFootprintByReference(ref)
        if kind == "rot":
            fp.SetOrientationDegrees(fp.GetOrientationDegrees() + arg)
        else:
            fp.Flip(fp.GetPosition(), False)
            flips.append(ref)
    pcbnew.SaveBoard("detector-hat.kicad_pcb", b, True)

    if flips:
        src = open("tools/pcb_gen.py").read()
        m = re.search(r"BOTTOM = \{[^}]*\}", src)
        cur = eval(m.group(0).split("=", 1)[1])
        for ref in flips:
            cur.symmetric_difference_update({ref})
        new = "BOTTOM = {" + ", ".join(f'"{r}"' for r in sorted(cur)) + "}"
        open("tools/pcb_gen.py", "w").write(src[:m.start()] + new + src[m.end():])
        print("BOTTOM set updated:", sorted(cur), flush=True)
    subprocess.run([PY, "tools/sync_place.py"], check=True)

    # final full pipeline on the chosen configuration
    print("final pipeline:", flush=True)
    subprocess.run([PY, "tools/pcb_gen.py"], check=True)
    b = pcbnew.LoadBoard("detector-hat.kicad_pcb")
    src = open("tools/pcb_gen.py").read()
    bottom = eval(re.search(r"BOTTOM = (\{[^}]*\})", src).group(1))
    for fp in b.Footprints():
        if (fp.GetReference() in bottom) != fp.IsFlipped():
            fp.Flip(fp.GetPosition(), False)
    for t in list(b.Tracks()):
        b.RemoveNative(t)
    pcbnew.ExportSpecctraDSN(b, "detector-hat.dsn")
    pcbnew.SaveBoard("detector-hat.kicad_pcb", b, True)
    un = run_freerouting("detector-hat.dsn", "detector-hat.ses")
    print(f"final freerouting: {un} unrouted", flush=True)
    b = pcbnew.LoadBoard("detector-hat.kicad_pcb")
    pcbnew.ImportSpecctraSES(b, "detector-hat.ses")
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard("detector-hat.kicad_pcb", b, True)
    subprocess.run([PY, "tools/stitch_islands.py"], check=True)
    subprocess.run([PY, "tools/silk.py"], check=True)
    subprocess.run([PY, "tools/sync_place.py"], check=True)
    subprocess.run([PY, "tools/check_unrouted.py"], check=True)
    subprocess.run([KICAD_CLI, "pcb", "drc", "--format", "json", "-o",
                    "../tmp/drc-orient.json", "detector-hat.kicad_pcb"])
    for f in ("trial_base.kicad_pcb", "trial_work.kicad_pcb",
              "trial.dsn", "trial.ses"):
        if os.path.exists(f):
            os.remove(f)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
