#!/usr/bin/env python3
"""Reshape kicad-cli's raw BOM/position exports into JLCPCB's expected CSV
column names/order. Run from kicad/, after fab_gen.sh's kicad-cli steps.
"""
import csv

with open("fab/bom-raw.csv", newline="") as f:
    rows = list(csv.DictReader(f))

with open("fab/detector-hat-bom.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Comment", "Designator", "Footprint", "LCSC"])
    for r in rows:
        footprint = r["Footprint"].split(":", 1)[-1]
        w.writerow([r["Value"], r["Reference"], footprint, r["LCSC"]])

with open("fab/positions-raw.csv", newline="") as f:
    rows = list(csv.DictReader(f))

with open("fab/detector-hat-cpl.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for r in rows:
        w.writerow([r["Ref"], r["PosX"], r["PosY"], r["Side"].capitalize(), r["Rot"]])

print("wrote fab/detector-hat-bom.csv, fab/detector-hat-cpl.csv")
