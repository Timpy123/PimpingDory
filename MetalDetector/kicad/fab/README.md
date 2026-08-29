# JLCPCB upload package — UnderwaterMetalDetector V1.0

## Files
- `detector-hat-gerbers.zip` — PCB fabrication (gerbers + Excellon drill)
- `detector-hat-bom.csv` — assembly BOM (Comment/Designator/Footprint/LCSC)
- `detector-hat-cpl.csv` — pick-and-place positions (92 parts, both sides)

## Ordering flow (jlcpcb.com → Order now)
1. Upload the gerber zip. Board: 42×135 mm, 2 layer, 1.6 mm, any color.
   Defaults are fine; set "Remove Order Number" → "Specify location" (JLC
   places its order code on a silk spot of their choosing otherwise).
2. Enable **PCB Assembly**: assembly is **both sides** (SMD top and bottom).
   Economic assembly is single-side — this board needs Standard.
   2 assembled of 5 boards is the usual cheapest split.
3. Upload BOM + CPL when prompted.
4. **Part matching:** most connectors have an empty LCSC column on purpose —
   JLC's matcher proposes parts from Comment+Footprint. Confirm each line.
   **No hand-soldering: if a part has no JLC match, swap the footprint to a
   stocked equivalent and re-run `tools/fab_gen.sh` — never leave it for a
   hand joint.** Watch these:
   - STF10N60 (Q3, TO-252): any 500–600 V, ≥7 A N-MOSFET in TO-252/DPAK is fine.
   - STN1HNK60 (Q4/Q5/Q6, SOT-223): 600 V N-MOSFET; the SOT-223 tab (pad 4) is
     the drain and is net-tied — keep any alternate's tab = drain.
   - NE5534 (U6), TL072 (U9), MCP41010 (U7), TC4427 (U5), DRV8833PWP (U8):
     match exactly.
   - 220uF 25V (C7/C8/C9, 8×10.5 SMD electrolytic): pick a low-ESR series.
   - BT1 = MYOUNG BH-18650-A6AJ002 18650 holder (THT, LCSC C19184085).
   - **Charging is external now — there is NO USB connector on the board.**
     J3 is just a 1×2 2.54 mm socket for a 5 V pigtail from a housing-mounted
     micro-USB jack (bought separately, not in this BOM). CC resistors are gone.
   - Connectors to confirm stock on (all THT, JLC-assembleable):
     - J1, J2, J3 — PinSocket 1×02 2.54 mm vertical (piezo / power-switch / 5V).
     - J6, J7 — JST-GH BM04B-GHS-TBT (4-pin, top side). J6 = OLED; J7 is a
       free I²C port (formerly depth meter, dropped 2026-08-29) — still fitted.
     - J8 — JST-GH BM03B-GHS-TBT (3-pin, WS2812 strip).
     - J9 — JST-GH SM03B-GHS-TB (3-pin debug, LCSC C54582898).
     - J4 — PinHeader 1×04 2.54 mm right-angle (coil dock, outer pins only).
5. J10/J11 = the two 1×20 female headers of the Pico socket — JLC assembles
   them (THT). After delivery you only plug in the Pico H. If the matcher
   offers no 1×20, take 2× per board of any 2.54 mm female header ≥20 pos.

## Reproducing these files
From `kicad/`: run `tools/go.sh` (regenerates the board, routes, stitches GND,
silk, checks) for a current routed board, then `tools/fab_gen.sh` — it drives
`kicad-cli pcb export gerbers/drill/pos` + `kicad-cli sch export bom` and
`tools/make_jlc_csv.py` to produce the gerber zip + JLC-format BOM/CPL here.
