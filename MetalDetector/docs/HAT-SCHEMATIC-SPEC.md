# Detector Pod v3 HAT — KiCad Schematic Specification

Input for the KiCad project in **`kicad/`** (KiCad 9; root `detector-hat.kicad_sch` with hierarchical
sheets Power / TX_Damping / RX_Chain / IO_Pico matching the sections below; renders in `kicad/render/`). Netlist-level:
every block lists components, values, packages (JLCPCB economic-assembly compatible),
and net names. Exact LCSC part numbers get picked during footprint assignment —
all parts below are standard LCSC basic/extended stock categories.

Board: 2-layer, ~65×90 mm, Pico socketed via 2×20-pin female headers (assembled).
All external connections via JST (pre-crimped cables); the coil's screw terminal is
the only field-wired joint.

---

## Sheet 1 — Power

**IN:** `VBAT` (18650, 3.0–4.2 V) via J1.

| Ref | Part | Value/Package | Function |
|---|---|---|---|
| BT1 | 18650 holder (MYOUNG BH-18650-A6AJ002), mid-board **bottom side** | THT | battery in — cell rides the board; low CG |
| J2 | power switch (IP68 toggle in the lid) via 1×2 corner socket (`REED`, GND) | 1×2 2.54 mm, bottom | high-side power switch control |
| Q1 | P-MOSFET | AO3401A, SOT-23 | high-side power switch (external toggle pulls gate low via R1 100k/R2 1k; net name `REED` kept for history) |
| U1 | TP4056 | SOP-8 | 1 A Li-ion CC/CV charger |
| U2 | DW01A + | SOT-23-6 | cell protection |
| Q2 | FS8205A | SOT-23-6 | protection FETs (pairs with DW01A) |
| J3 | 1×2 socket (`VBUS_C` 5 V, GND), fed by an external housing-mounted **micro-USB** jack; on-board USB-C + CC pulldowns R3/R4 dropped 2026-07 | 1×2 2.54 mm, bottom | charge input (under pod's threaded plug) |

> **Two charge/data paths, deliberately:** the **charge port** is an external housing-mounted
> **micro-USB** jack wired (5 V + GND) to J3 (a 1×2 socket) → TP4056; charge-only, no data,
> field-accessible under the threaded plug. The **Pico's own micro-USB** = flash/debug only, feeds
> VSYS via the D7 diode-OR, physically inside the pod → bench use only. They cannot be merged: the
> flash path cannot reach the charger (D7 blocks toward the cell), and a socketed Pico exposes USB
> data only on underside test points. Both plugged simultaneously is safe — independent paths,
> common ground.
| U3 | MT3608 | SOT-23-6 + L1 22 µH + D1 SS34 + Cin/Cout 22 µF | boost → `V12_TX` (R divider 191k/10k → 12.06 V; 190k unavailable at assembly, 2026-07) |
| U4 | MT3608 (2nd) | same | boost → `V9_SND` (9.0 V, sounder rail) |
| D7 | Schottky 3 A | SS34, SMA | VBAT(switched) → VSYS diode-OR: lets the Pico's micro-USB be plugged (flashing/debug) while the battery is connected — highest supply wins, no back-feed into the cell (per Pico datasheet "Powering Pico"). Optional upgrade: ideal-diode P-FET pair for ~0.3 V less drop |
| — | `VSYS_PICO` | net | VBAT after Q1 → **D7** → Pico VSYS pin 39 (Pico onboard reg makes 3V3) |
| — | `3V3` | net | from Pico pin 36 → OLED, digipot, logic |

**Safety notes (verified scenarios):** (1) USB plugged while battery-powered: USB VSYS (~4.7 V)
> VBAT (≤4.2 V) → D7 reverse-biases; supplies diode-OR, no cross-feed, PC port sees only logic load.
(2) Battery inserted while USB connected: switch off = cell touches only the charger tap; switch on =
normal power-up, D7 still blocks. (3) ⚠️ **The real risk is a reverse-inserted 18650**: Q1 blocks it
from the loads, but the TP4056 charger tap sits directly on the cell and dies on reverse polarity —
use holders with unmissable polarity marking; the ideal-diode upgrade closes this fully. Flashing
habit: power switch off → TX rails dead, USB powers logic only. Charging works with the pod switched off
(TP4056 is before Q1). BOOTSEL is a boot-mode button, not power.

**Power direction & battery options:** battery → HAT → Pico; never the reverse — TX pulse peaks
(1–2 A) and both boost rails need the direct cell path, and the Pico's USB diode can't carry them.
Pico USB = flashing/debug only. Battery input accepts **1S, 1S2P, or 1S3P** parallel 18650 packs
(same XH plug, same 3.0–4.2 V; more cells = proportionally more runtime). **Never series (2S = 8.4 V
exceeds VSYS 5.5 V max and the 1S TP4056).** With spare charged cells, hot-swapping through the pod's
threaded plug is the primary charging strategy; the external micro-USB/TP4056 (1 A — slow for 2P/3P) is
the overnight convenience option.

Bulk: C-bank 3× 220 µF low-ESR on `V12_TX` close to TX stage (pulse current reservoir).

## Sheet 2 — TX stage + damping

| Ref | Part | Value/Package | Function |
|---|---|---|---|
| U5 | TC4427 | SOIC-8 | MOSFET gate driver, in ← `TX_GATE` (Pico GP17) |
| Q3 | N-MOSFET 500 V+ | IRF740-class; SMD: STF10N60 or TO-252 equiv | coil switch, source→GND, drain→`COIL_A` |
| J4 | **coil dock**: 1×4 right-angle male header, south edge, pins 1+4 only (7.62 mm creepage for the 300 V flyback) → 1×4 female socket in nose end-stop → SP17-2 bulkhead | `COIL_A`/`COIL_B`; `COIL_B`→`V12_TX` | coil; horizontal (axial) mate |
| D2 | fast HV diode | MUR160/US1J | flyback path shaping |
| R10 | 1 kΩ 2 W | 2512 | base damping (always in) |
| R11–R13 | 680 Ω / 330 Ω / 150 Ω, 1206 | binary-ish damping bank across coil | selected via Q4–Q6 |
| Q4–Q6 | **HV switch — the flagged detail**: 600 V small-signal MOSFET (e.g. STN1HNK60-class) *or* photoMOS relay (TLP3906) per leg | damping select, gates/LED ← `DAMP0..2` (GP10–12) | ⚠️ must survive 300–400 V flyback; bench-validate first spin, photoMOS is the safe-but-slower fallback |

## Sheet 3 — RX chain

Signal path: `COIL_A` → R20 1 kΩ → D3/D4 clamp (BAV199 to ±rails) → C-coupled →
U6A **NE5534** (G≈×100, low-noise first stage, runs on `V9_SND`/GND with `VREF` 1.65 V bias)
→ U7 **MCP41010** digipot (SPI: `SCK` GP2, `MOSI` GP3, `CS_POT` GP6) as gain set →
U6B/TL072 second stage (G≈×10) → R21/R22 divider + D5/D6 BAT54S clamp to 0–3.3 V →
`RX_ADC` (Pico GP26/ADC0). `VREF` from 3V3 via R-divider + buffer (TL072 spare half).
RC anti-alias: 1 kΩ + 220 pF at ADC pin.

## Sheet 4 — Outputs & peripherals

| Ref | Part | Package | Nets |
|---|---|---|---|
| U8 | DRV8833 (chip) | HTSSOP-16 | piezo push-pull; VM=`V9_SND`; AIN1/2 ← GP14/15; OUT→J1 (piezo dock) |
| J1 | piezo dock: 1×2 corner socket (`PIEZO_P`, `PIEZO_N`) | 1×2 2.54 mm, bottom | sounder |
| J6 | top-side JST-GH 4-pin by R31/R32 — OLED, I²C (`3V3`/`SDA`/`SCL`/`GND`) | BM04B-GHS-TBT | window display |
| J7 | identical GH 4-pin I²C dock — **free I²C port (formerly depth meter)**, MS5837 dropped 2026-08-29; left fitted for any future I²C device | BM04B-GHS-TBT | free I²C |
| J8 | top-side JST-GH 3-pin — WS2812 strip (`VBAT_SW`, `WS_DATA`, `GND`) | BM03B-GHS-TBT | LED bar |
| J9 | JST-GH 3p | debug UART: GND, `TX` GP0, `RX` GP1 |
| R31,R32 | 4.7 kΩ | 0402/0603 | I2C pull-ups to 3V3 |
| J10,J11 | 2×20 female header 2.54 mm | — | Pico socket |

## Pico pin map (must match firmware `config.h`)

| GPIO | Net | Function |
|---|---|---|
| GP0/GP1 | UART0 | debug console |
| GP2/GP3 | SPI0 SCK/MOSI | digipot |
| GP6 | CS_POT | digipot chip select |
| GP8/GP9 | I2C0 SDA/SCL | OLED; J7 = free I²C port (formerly depth meter) |
| GP10–12 | DAMP0..2 | damping bank select |
| GP13 | WS_DATA | LED strip |
| GP14/GP15 | SND_A/B | sounder H-bridge |
| GP17 | TX_GATE | coil pulse |
| GP26 | RX_ADC | decay signal |
| pin 39 | VSYS | VBAT (switched) |
| pin 36 | 3V3 out | logic rail |

## Docking (user design, approved 2026-07-19)

Two orthogonal docks fully constrain the board (no wobble on the 135 mm lever):
**nose = horizontal** coil dock (J4, board slides axially in, ~2.5° nose-down) constrains the nose;
cradle mate is a 1×4 female socket — commodity 2.54 mm, ~30+ mating cycles, contacts 3 A.
**lid end = vertical**: the single 2×6 dock (J5) was replaced 2026-07-24 by a row of three 1×2
vertical sockets along the north edge (bottom side) that drop onto male headers potted in the cradle
— same drop-in retention as the old 2×6, now spread across three anchor points across the edge:
**J1** (left corner) = piezo (PIEZO_P/PIEZO_N), **J3** (middle) = 5 V charge input (VBUS_C/GND, from
the external micro-USB jack), **J2** (right corner) = power switch (REED/GND). The window/sensor
devices (OLED, WS2812) no longer pass through the dock — they connect on the **top**
side via J6/J7/J8 GH cables and play no structural role. Board plane raised ~2 mm in the cradle so
the mid-board cell keeps ~5 mm bottom clearance during the tilt.
Cradle print is a precision part: mandatory scrap-board test fit before potting.

## Mechanical

- **Board outline: plain rectangle (~65×90 mm).** No cutouts or peninsulas. **Since the MS5837
  was dropped (2026-08-29) nothing in the design needs water contact at all** — the pod has zero
  wet-side penetrations, so the whole housing is a plain sealed tube. (Previously the Bar PCB
  satellite was epoxy-potted into the wall with its gel port exposed; depth now comes from the
  host drone's own `VFR_HUD` over MAVLink, logged topside.)
- **Pico mounting: 4× 2.1 mm holes matching the Pico's own hole pattern (11.4 × 47 mm rectangle),**
  placed under the socket so the module is bolted through **nylon M2 standoffs** — socketed headers
  alone don't survive cable tugs. Nylon, not steel: non-conductive and no extra static target for
  the coil.
- **HAT mounting: 4× M3 corner holes** (nylon again) for the pod's 3D-printed cradle.

## Layout rules (the analog ones that matter)

1. TX loop (C-bank → Q3 → coil terminal → back) as tight as possible; star-ground the RX front end to the coil terminal, not the digital ground pour.
2. Keep U6A input traces short, guard-ring them; no digital traces under the RX chain.
3. `V12_TX` bulk caps within 10 mm of Q3 drain circuit.
4. WS2812/OLED/piezo connectors on the board edge facing the pod window.
5. Fuse VBAT at J1 (polyfuse 2 A, on board).

**Shielding — electric vs. magnetic (they invert here):**
- Outer-layer ground pours shield the inner routing from **E-fields** as usual — wanted, especially between the boost converters and the RX chain. Keep them.
- Against the **coil's B-field**, copper is not a shield but an eddy-current *target*: pours facing the coil register as constant metal (auto-zero nulls it, but it costs dynamic range and damps the coil). Rules (amended 2026-07-19 after routing): **hatch the coil-adjacent south strip (y>109); solid pours north of it** — solid fill keeps GND contiguous where eddy coupling is negligible (>10 cm from coil + auto-zeroed static target), hatch stays where it matters; **no closed conductor loops** — perimeter guard/stitching rings get a deliberate gap (a closed ring is a shorted one-turn secondary); mount the board **edge-on to the coil**; the small pour under the RX front end stays *solid* (tiny constant signature, maximal E-shield where it counts). Distance (the coil arm, 10–15 cm) remains the only real magnetic shield; the 18650 steel cans dwarf any pour as a static target and are absorbed by auto-zero.

## Known-risk register (bench-validate on spin 1)

- Damping-bank HV switching (Q4–Q6): the one genuinely novel circuit — photoMOS fallback footprint on the board ("do-not-populate" alternate).
- RX clamp recovery time after the 300 V spike vs. earliest sample delay.
- MT3608 switching noise coupling into RX (add "DNP" LC filter positions on both rails).
- ADC scaling: R21/R22 chosen so full decay dynamic range lands in 0–3.3 V — values are placeholders until first scope session.
