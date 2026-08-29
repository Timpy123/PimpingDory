# Metal detector pod

A **self-contained pulse-induction metal detector** for the Chasing Dory.
Its own battery, no data connection to the drone at all — it reports by being
*visible to the drone's camera*: an LED strip and a small OLED sitting in the
bottom edge of the frame.

Target: a coin-sized non-ferrous object at **15–30 cm**, against about **4 cm**
for Chasing's own detector, which is ferrous-only and sold only inside a
€480–600 bundle.

## Why it reports optically

There is no channel to report on. The Dory's compute module has ten plugs and
every one is taken: 1–5 the thrusters, 6 the breathing light, 9 the LED lights,
7–8 the tether pair. Nothing spare, and adding a conductor means opening a
pressure housing.

So the pod says nothing electrically and everything visually — the same channel
Chasing's stock detector uses, and it works because you are already watching
the camera.

## Why pulse induction

PI is the standard for underwater and beach detectors: largely indifferent to
water, salt and bottom mineralisation, where a VLF detector needs constant
ground balancing. One coil does both transmit and receive. It finds every
conductive metal with no discrimination — fine when the plan is "go look with
the camera".

The MCU switches 1–2 A through the coil for ~150 µs, cuts it, and measures how
slowly the field decays. Metal nearby decays slower. Repeat 100×/s, track the
baseline, report the deviation.

## What is here

```
PLAN-DETECTOR-POD.md     the build plan — the authoritative document
docs/HAT-SCHEMATIC-SPEC.md   the circuit
kicad/                   the HAT board: schematic, PCB, fab outputs
src/detector-firmware/   the firmware (C, pico-sdk)

toolchain.sh             fetch the ARM cross-compiler   (976 MB)
sdk.sh                   fetch the Pico SDK             (37 MB)
freerouting.sh           fetch the autorouter           (137 MB)
build.sh                 build the firmware
```

The four scripts sit at the root, not in `src/`, because `src/` is *what they
fetch* — a `rm -rf src` to start clean must not delete the tools that rebuild
it.

## Building the firmware

```sh
./toolchain.sh
./sdk.sh
./build.sh
```

macOS and Linux, Intel and ARM. Each script detects the host and picks the
right download; `build.sh` checks that everything it needs is present and names
what is missing rather than failing part-way through.

Output is `src/detector-firmware/build/detector-firmware.uf2`. To flash it,
hold BOOTSEL while plugging the Pico in and copy the `.uf2` onto the `RPI-RP2`
drive that appears. Debug console is 115200 baud on UART0 (GP0 = TX).

```sh
./build.sh --clean     throw the build directory away first
./build.sh --debug     build with debug symbols
```

**Nothing is downloaded twice.** Each script finds an existing install and asks
before replacing it; non-interactively it keeps what is there and tells you to
pass `--force`.

**None of the fetched content is in git** — 1.3 GB of vendor binaries and
upstream checkouts, all reproducible from these scripts, and two of them carry
their own `.git` directories. Pinned versions: ARM 14.2.rel1, pico-sdk 2.3.0,
Freerouting 2.2.4.

`picotool` has no script: cmake fetches it itself on the first configure.

## The board

One JLCPCB-assembled carrier for a Raspberry Pi Pico, holding the pulse
generator, the receive chain, power, and the connectors for coil, display,
strip, sounder and depth sensor. `kicad/fab/` has the gerbers, BOM and
pick-and-place files with ordering notes.

**The board is generated, not drawn.** `sch_gen.py` emits the schematic from
component tables and `pcb_gen.py` emits the PCB from a placement table, so the
source of truth is those scripts rather than the `.kicad_*` files. Moves made
by hand in the GUI are pulled back into the table with `sync_place.py` — do
that before any regeneration, or they are lost.

### The pipeline

`kicad/tools/go.sh` runs the whole thing in one shot: regenerate → flip the
bottom-side parts and rip all tracks → Freerouting → import the result and fill
zones → report stranded copper → stitch islands → silk → sync → signal check.

**It is destructive by design** — stage 2 removes every track on the board
before rerouting. Fine when that is what you want; not something to run
casually.

### Every tool in `kicad/tools/`

| tool | what it does |
|---|---|
| **`go.sh`** | the whole reroute pipeline, 8 stages. **Rips all tracks first** |
| `sch_gen.py` | emit the schematic from the component/label tables |
| `pcb_gen.py` | emit the PCB from the `PLACE` floorplan table |
| `sync_place.py` | pull GUI moves back into `pcb_gen.py`'s table so they survive a regen |
| `route.py` | grid A* autorouter, routes every net including GND |
| `route_remainder.py` | grid A*/Dijkstra for the few nets Freerouting cannot close, against the real board |
| `check_unrouted.py` | name the genuinely unrouted nets — DRC's own list is noisy with GND zone fragments |
| `signal_check.py` | list genuinely-open signal connections from a `kicad-cli` DRC report |
| `stitch_islands.py` | join isolated GND pour islands with the fewest vias, only where an island exists |
| `silk.py` | pin-1 dots, battery polarity, board name. Re-run after any regen — it wipes them |
| `heat_check.py` | flag heat sources sitting too close to heat-sensitive parts, including stacked through the FR4 |
| `orient_search.py` | try rotations and flips of chosen parts, route each, keep the best |
| `pinmap_trial.py` | try connector pin assignments and route each to compare |
| `fab_gen.sh` | build the JLCPCB package: gerbers zip, BOM, pick-and-place |
| `make_jlc_csv.py` | reshape `kicad-cli`'s raw exports into JLCPCB's column names |
| `backup.sh` | timestamped tarball of `kicad/` into `../tmp/backups` |
| `kicad_paths.sh` | find KiCad and Freerouting on this machine. Sourced by the shell tools, never run |
| `kicad_paths.py` | the same, imported by the Python tools |

Most take KiCad's own Python, and are run **from `kicad/`**, not from
`tools/` — for example `tools/go.sh` or `python3 tools/pcb_gen.py`.

### Paths, and other machines

The tools used to hardcode `/Applications/KiCad/KiCad.app/...`, correct on one
Mac and wrong everywhere else. They now resolve through `kicad_paths.sh` and
`kicad_paths.py`, which look in the usual macOS and Linux locations and fail
with something actionable if a piece is missing. Override any of them in the
environment:

```sh
KICAD_CLI=/path/to/kicad-cli KICAD_PY=/path/to/python3 tools/go.sh
```

| variable | what it points at | Linux |
|---|---|---|
| `KICAD_CLI` | `kicad-cli`, for gerber/drill/DRC export | `apt install kicad` |
| `KICAD_PY` | a python that can `import pcbnew` | `apt install kicad python3-pcbnew` |
| `KICAD_FP` | KiCad's stock footprint libraries | `/usr/share/kicad/footprints` |
| `FR` | Freerouting | `./freerouting.sh` |

**Untested on Linux.** The path resolution is written for it and the pipeline
itself is platform-neutral, but nobody has run it there.

## Status

Plan written, firmware written, board laid out. **Nothing has been built or
tested in water.** The test protocol is §7 of the plan; the interference test
against running thrusters is the one that decides whether this works on this
drone at all.

## Open questions worth answering early

- **The drone has a magnetometer.** It runs ArduSub with a compass on I²C and
  reports heading in telemetry. A coil pulsing 1–2 A a few centimetres away is
  a large alternating field next to it, and nothing compensates for that.
  Heading may be unusable while the detector runs. Measurable now: run
  `../scripts/DoryControl.sh --telemetry` and watch `hdg` with the coil
  pulsing.
- **Size.** The Dory is 247 × 188 × 92 mm, 1.1 kg, five thrusters, and **no
  lateral thruster** — it cannot crab sideways to hold station. A 50 mm pod
  plus a 20 cm coil ring below it is a lot of drag on a small platform. A
  cardboard-and-lead mockup of the final envelope, flown before any epoxy is
  mixed, answers this cheaply.
- **Thrusters must not be run dry.** The manual is explicit that it can seize
  the motors, so the interference test has to happen in water.
