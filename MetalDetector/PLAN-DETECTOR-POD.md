# DIY Pulse-Induction Metal Detector Pod — Build Plan

**Current build (v3, 2026-07): self-contained pod for a stock Chasing Dory** — own 18650 battery, no data connection to the host; reports optically (WS2812 strip + OLED in the camera's view, the same channel the Dory Explore's stock detector uses) and acoustically (potted piezo for divers). Electronics = one JLCPCB-assembled Pico-carrier HAT (see "v3 specification" below; circuit in `docs/HAT-SCHEMATIC-SPEC.md`, KiCad in `kicad/`, firmware in `src/detector-firmware/`).

*Historical note: the design originally had a second "drone backend" (RS-485 bus, §6 of the shelved DIY ROV platform plan, now `../ArchiveIdeas/PLAN.md`); v3 dropped it — the HAT carries no RS-485. Re-adding it later would be a connector + firmware module, not a redesign.*

Target performance: coin-sized non-ferrous target at 15–30 cm in water (stock Dory Explore detector: ~5 cm, ferrous only).

---

## 1. Why pulse induction (PI)

- PI is the standard technology for underwater/beach detectors: largely insensitive to water, salt, and bottom mineralization, where VLF detectors need constant ground balancing.
- It detects all conductive metals (gold, silver, bronze, iron), with no discrimination — fine for "go look with the camera/net."
- Electrically simple: one coil does transmit and receive; no coil-balancing act like VLF induction-balance designs.

**How it works:** the MCU switches ~1–2 A through the coil for ~100–250 µs via a MOSFET, then cuts it. The collapsing field induces eddy currents in any nearby metal; those currents decay over tens of µs and re-induce a voltage in the coil. The receive chain amplifies the coil voltage after the flyback spike settles and measures **how slowly it decays** — metal nearby = slower decay. Repeat ~100×/s, track the baseline, report deviations as signal strength.

## 2. Two build routes — **HISTORICAL (superseded 2026-07-17 by the v3 HAT; see "v3 specification" below)**

*Kept as decision record: v3 is Route B implemented on a JLCPCB-assembled carrier board. Route A (bought front end) was retired; the Clone PI-AVR module remains the emergency plan-B only if the HAT's analog front end fails beyond respin.*

| Route | What | Cost | Effort | Recommended for |
|---|---|---|---|---|
| **A — kit front end** | Buy a **Surf PI 1.2 kit** (classic open DIY design, €15–25 on eBay/AliExpress, sold as "pulse induction detector kit"), let it do pulse + analog; Pico only *reads* its output (audio/LED drive line → ADC) and drives LED bar + sounder | €65–78 all-in (§8) | Solder a kit, small glue firmware | Getting a working pod fast; matches the project's off-the-shelf preference |
| **B — scratch, MCU-timed** | Pico generates pulse timing itself (PIO), discrete MOSFET driver, op-amp receive chain, Pico ADC samples the decay curve directly → raw decay values, tunable in firmware | €60–68 all-in (§8) | Real analog bring-up on a breadboard first | Quantitative, fully tunable detection; do it as v2 once A works |

Start with **Route A**. The Surf PI's audio output frequency/level tracks target strength; the Pico measures it and forwards it. Everything below (coil, housing, integration) is identical for both routes.

**Route A alternative front end — Clone PI-AVR (investigated 2026-07, sanctioned fallback/upgrade within the freeze):** an ATmega8A-based PI detector sold as a **fully assembled and tested module** (~€45–70 on eBay/metal-detector shops, vs €15–25 for the Surf PI solder kit). Relevant differences:
- **Auto coil tuning** — it adapts itself to the attached coil, removing the Surf PI's per-coil damping-resistor tuning step and long-term drift concerns; explicitly supports coils from 20 cm up.
- **More TX power / claimed range** (up to ~1.5 m with a 28 cm coil — marketing-optimistic, but PI power scaling is real); supply 9–15 V, so the pod's 9 V MT3608 rail works unchanged.
- **Assembled + tested** beats kit-soldering on the project's off-the-shelf preference; comes with LCD + buzzer (LCD unused in the pod or kept as a second bench display).
- **Integration is identical to Surf PI**: the Pico taps its buzzer/audio line into ADC0 — zero firmware changes; its internal auto-tune and our activity-baseline logic are complementary, not conflicting.
- Cost 2–3× the Surf PI; slightly higher current draw.

**Decision rule:** Surf PI kit stays primary (frozen, cheapest). Buy the Clone PI-AVR instead if (a) the Surf PI kit is out of stock when ordering, (b) kit soldering/tuning fails, or (c) post-freeze, more range is wanted — it is the designated "problem arose" replacement.

**Route B implementation path (post-freeze, evaluated 2026-07): Clone PI-W analog front end on a custom Pico carrier board.** The Clone PI-W is open-source; its board = analog TX (MOSFET pulser) + analog RX (op-amp decay chain) + an ATmega8 doing timing/auto-tune/LED/buzzer. The right adaptation: **copy the TX/RX analog sections, delete the ATmega8** — the Pico takes over pulse timing (PIO), decay sampling (ADC), and auto-tune (the adaptive baseline), gaining raw decay-curve access → the tau/target-character display the OLED reserves. Keeping the ATmega8 next to the Pico would mean two MCUs, AVR flashing (programmer + fuses), a 5 V boundary, and still only an audio-tap interface — all cost, no gain over buying the assembled module. Board: one JLCPCB carrier ("HAT" with Pico headers) hosting front end + DRV8833 + TP4056 + MT3608 + connectors (coil, strip, OLED, Bar PCB) — ~€10–20 bare ×5, ~€40–70 with SMT assembly; MOSFET/op-amps are standard assembly parts, the legacy ATmega8 is the one scarce chip and it's the one we drop. Caveats: real KiCad effort, analog boards often need a respin, Clone PI-W docs are Russian-forum material, RX output must be scaled/clamped to the Pico's 3.3 V ADC. Does not touch frozen v2 — v2 ships with a bought front end.

**Route B HAT design decisions (settled 2026-07):**
- **Auto-tune without the ATmega8** — it was firmware, not analog, so the Pico inherits it: measure flyback settle per coil, place sampling delays adaptively, track drift. Two analog helpers complete it beyond what Clone PI-W offers: a **switchable damping network** (binary-weighted resistors on small MOSFETs — Pico selects critical damping per coil; kills Surf PI's solder-a-resistor step) and an **MCP41xx digital pot** for firmware-set RX gain. Any coil 15 cm–frame: plug, power-cycle, self-calibrated.
- **Deeper than Surf PI:** ~12 V boosted TX rail + beefier MOSFET + longer pulses; NE5534-class low-noise first RX stage; MCU multi-delay sampling (also the tau enabler).
- **Connectors — JST family, sized by current, all pre-crimped commodity cables, all JLCPCB-assemblable:** **JST-GH** (1.25 mm, latching, Pixhawk standard, ~1 A) for OLED and WS2812 (piezo + power switch moved to 1×2 corner sockets J1/J2; depth/Bar PCB dropped 2026-08-29); **JST-XH/PH** for battery and coil (charging + 1–2 A TX pulse peaks exceed GH ratings). Coil alternative: screw terminal — coil ends are enamel wire needing strip+tin regardless, the single unavoidable dab of solder in the build.
- **Solder-free goal:** JLCPCB assembles SMD + connectors + Pico female headers → order board, plug Pico H, plug pre-crimped cables.

## 3. Electronics — **superseded: the authoritative circuit is `docs/HAT-SCHEMATIC-SPEC.md` + the KiCad project in `kicad/`** (paragraph kept as background only)

- **Pulser:** IRF740/IRF840 MOSFET, gate driver from Pico GPIO (via TC4420 or transistor pair), 12 V through coil, 100–250 µs on-time, ~100 Hz repetition. Flyback clamp: the coil's own damping resistor (~470 Ω–1 kΩ, tune for critical damping — fastest settle without ringing).
- **Receive chain:** input protection (back-to-back diodes + series R), low-noise op-amp gain stage ×~1000 (NE5534/TL072 class), active after-spike blanking; Pico ADC samples the decay at fixed delays (e.g. 15/30/60 µs after switch-off).
- **Detection:** long-run baseline average per sample point; signal = deviation; report an 8-bit strength value; auto-zero drift slowly.
- **Power:** bus 12 V → local 5 V/3.3 V regulators; **LC filter + local bulk capacitance** on the 12 V input — the coil pulses must not shove current transients back into the drone's bus.

## 4. Coil

- ~20 cm diameter, **25–30 turns of 0.6 mm enameled magnet wire** (0.5 mm was the original spec; 0.6 chosen for availability and lower DCR — 0.4 mm rejected as too resistive), target ~300–500 µH, DC resistance ~1–2 Ω.
- Form: 3D-printed ring mold or a groove routed in HDPE; feed with short coax or tightly twisted pair.
- **Termination (enamel never meets a crimp):** strip/tin the magnet-wire ends in a solder blob (solderable polyurethane enamel burns off at ~400 °C; scrape first if polyimide), solder to a flexible silicone-stranded ~20 AWG pigtail, and **pot the joint inside the coil's epoxy** — magnet wire is fatigue-brittle, so all flexing must happen in the pigtail; the buried joint is also the strain relief. Pigtail lands in the HAT's screw terminal (J4); JST-XH stays battery-only, since crimps need stranded bare wire and enamel blocks a gas-tight crimp.
- **Pot the coil in epoxy** in its ring — this is its waterproofing and its mechanical protection. Leave no air voids (vacuum degas or pour thin layers).
- No electrostatic shield for v1 (adds complexity; underwater static pickup is modest). Add a graphite-paint shield grounded at one end only if erratic in tests.
- Mount the coil **as far from the drone's thrusters and any steel as the frame allows** (≥15 cm if possible) — the detector will always "see" the drone itself; that constant offset is nulled in firmware, but the closer the metal, the more sensitivity is wasted on it.

## 5. Housing and mechanical

- **Electronics pod:** 50 mm PVC pipe stub, one glued cap, one threaded plug; coil ring bolted below it on a short arm (nylon bolts near the coil!).
- **Drone version:** SP13 4-pin bulkhead (greased) for the accessory bus; pod trimmed neutral with foam.
- **Dory version:** no penetrations at all — internal 18650 cell (+ TP4056 charge board, charge port under the threaded plug), IP68 toggle switch panel-mounted in the threaded plug (was: reed+magnet — replaced 2026-07-18 by user preference), and a **clear window (pipe end cap + polycarbonate disc) showing the WS2812 strip + 0.91" OLED** (see display bullets below; the original 8–10 discrete LED bar is retired) angled up toward the Dory's camera. Must match the stock detector's mass and near-neutral buoyancy (Dory trim margins are tight); weigh the stock unit before building.
- **Mounting to the Dory (confirmed from the official quick-start guide):** the stock detector is fully self-contained — own user-installed battery behind a film tab, own long-press power button, zero wires to the drone — and slides onto a **purely mechanical bracket** on the Dory's belly, secured with screws; the net clips onto the detector body. Mimicking this is a clean 3D-printing job:
  - Measure the stock bracket and the detector's slide profile with calipers (or trace from photos with a ruler in frame); model the mating profile in CAD with ~0.2–0.3 mm clearance.
  - Print in **PETG or ASA** (PLA creeps and softens when wet-warm; fine for a fit-test print only), ≥50 % infill or solid perimeters, oriented so layer lines don't align with the pull-off load. FDM porosity is irrelevant here — a bracket may flood freely; it's not a pressure housing.
  - Stainless A2/A4 screws + nylon lock nuts; replicate the net's clip lug on the pod arm if the net is wanted.
  - Keep the stock detector unmodified — swap between stock and DIY pod is then a two-minute screw job.
- **Dory teardown — cover screws & tools (field notes, 2026-08):** the cover screws are **ST2.2 × 6.5** self-tapping Torx (DIN 7983-TX countersunk, A4 stainless) — usable as replacements; source e.g. rvspaleis.nl (`din-7983tx a4 2.2×6.5`). There is also **one tamper-resistant Torx safety screw** that needs a **T6H (security/pin-in-head Torx) bit on a ≥50 mm shaft** to reach it — a long-reach security-bit set (e.g. amazon.nl ASIN B0GXNLXH3R) covers it. Have both on hand before opening the unit. Teardown/part-replacement walkthrough: YouTube `_ONTOr11_d4` (covers most part replacements).
- **Underwater sounder (both versions):** a bare **27–35 mm piezo disc**, epoxy-potted flat against the *inside* of the housing wall (or in its own epoxy-filled window) so it couples acoustically through the wall into the water — a conventional air-cavity buzzer is nearly mute submerged, a potted disc is clearly audible to divers for tens of meters (water carries sound well). Drive it push-pull from the HAT's DRV8833 at **9 V** (its VM limit is 10.8 V — never 12) near the disc's ~3–4 kHz resonance for volume. One diver-physics note: underwater, humans can *hear* the beeps but can barely tell direction (sound is too fast for binaural cues) — the sounder says "something, nearby", the LED bar/camera remains the pointer.
- **Display upgrade path:** the extra information a PI detector can honestly show is the eddy-current **decay time constant (tau)** — distance-independent, it classifies target character (fast decay = thin/small, slow = large/high-conductivity, distinct signature = ferrous-suspect), though never metal identity ("gold vs silver" is beyond PI). Tau requires Route B (multi-delay decay sampling); the Route A kit outputs a single level only.
  - **Placement constraint: the display must not block the camera and may be at most 1 cm tall.** Everything is therefore laid out *horizontally* on the pod's top face, positioned so it appears along the **bottom edge of the camera frame** (like the stock detector's LED) — in view, never in the way.
  - *v1.1:* replace the 10 discrete LEDs with a **WS2812/NeoPixel RGB strip mounted horizontally** (€3–5, strip is ~10 mm wide → fits the 1 cm limit; one GPIO, pico-sdk PIO example exists): bar *length* = strength, color = target character (Route B) or confidence above the gate (Route A).
  - *Why the strip stays even once the OLED exists — they are different channels, not competitors:* the display is read **through water by a camera**, so brightness beats resolution. WS2812s punch through turbidity, bad angles, and video compression (the stock detector used a bare LED for this reason) and can be potted directly in epoxy — no window, no seal. The OLED is dim and fine-detailed: excellent at 40 cm in clear water, invisible in murk, and needs a sealed recess. Division of labor: **strip = attention channel** (unmissable "target, roughly this strong" in peripheral vision while piloting), **OLED = detail channel** (tau class, fine bar) for hover-and-inspect.
  - *Running both at once — side-by-side, never stacked:* LEDs in front of (or angled over) the OLED don't work — not because of occlusion but **blooming**: the camera's auto-exposure blows out the image region around a lit WS2812, washing out nearby OLED pixels. Layout: strip and OLED **side by side in the same ≤1 cm band** along the bottom of the frame (band is 15+ cm long; OLED needs 36 mm, an 8-LED strip ~60 mm) with a few cm of dark separation between them. Firmware referees: when strength is high and *stable* for ~2 s (operator hovering to inspect), auto-dim the strip to ~10 % so the OLED is readable; restore on change. The §7 field test still decides if one channel can be dropped (clear water → OLED alone; murk → strip alone).
  - *Depth on the display — **DROPPED 2026-08-29**, was an MS5837-30BA on the I2C bus (v2 spec, 2026-07-17):* the sensor's one remaining justification was depth inside recorded footage (so every LED-bar hit in a screen recording carries its depth without cross-referencing) — it was always redundant live, since the host's app shows depth on the same phone screen. **That justification is gone: the Dory reports its own depth over MAVLink.** Every `SR0_*` stream rate on the Dory's ArduSub is zero, so it sends no telemetry unasked; send `REQUEST_DATA_STREAM` for **EXTRA2** and `VFR_HUD` starts arriving — depth and heading — logged topside with timestamps, which is strictly better than an on-screen figure (machine-readable, no camera legibility limit). Dropping it removes: one I2C device, one epoxy potting job, **one wet-side penetration**, and €35 for the Blue Robotics Bar30. It also frees OLED columns 0–79 for tau detail.
  - *v2:* add a **0.91" SSD1306 OLED, 128×32** (Waveshare 0.91inch OLED Module or any SSD1306 clone — €3–8, I2C, ~20 mA; active area ~30×5.5 mm) beside/instead of the strip: a horizontal bar plus a decay-class icon. At ~40 cm camera distance and 100° FOV, 5.5 mm glyphs are ~11 px tall on the 1080p feed — bars and icons stay readable, digits are marginal, so the UI is bar+icon, not text.
    - *Pico support:* Waveshare's own demos cover STM32/Arduino/Raspberry Pi only, but that's moot — the **official `pico-examples` repo has `i2c/ssd1306_i2c`**, a pico-sdk C example for exactly this controller and resolution; the SSD1306 is among the best-supported display controllers anywhere. Any-vendor module works identically.
    - *Mounting under the 1 cm rule:* the PCB is 36×12.5 mm, but it **recesses into a slot in the pod's top face** so only the glass shows through the window — apparent height in frame ≈ the 5.5 mm active strip plus a sliver of dark bezel. OLED's >160° viewing angle also beats the LCD's STN comfortably. Taller screens (0.96" SSD1306 ≈ 11 mm, 1.8" TFT ≈ 35 mm) rejected under the height limit; e-paper rejected (refresh too slow, no backlight in dim water).
  - *Clarified intent of the 1 cm rule:* it exists to **keep the camera's usable view area large** — what counts is the display's *apparent* height in the frame, i.e. physical height at its mounting distance. Masking rows of a taller module doesn't help; the glass still occupies the frame.
  - *v2, alternative — **Waveshare LCD1602 I2C** (AiP31068, native I2C, 3.3 V, ~€6):* on the list because **vendor support is a priority** — documented wiki, ready examples (MicroPython for Pico + Arduino; the pico-sdk C driver is a ~50-line port since the AiP31068 speaks HD44780 commands over I2C). Its viewing area is 64.5×**16 mm**, so under the clarified rule it only qualifies if mounted far enough from the lens that 16 mm subtends no more than 10 mm would at the reference distance (16 mm at ~64 cm ≈ 10 mm at 40 cm) — likely impractical on a pod hanging directly under the camera. Its natural role is therefore the **bench/development display**: hung on the same I2C bus during bring-up, showing two rows of live text telemetry (level/baseline/strength) where its examples and readability shine — exactly where good support pays off. In-water display remains the WS2812 strip / 0.91" OLED. (If it ever does go in-water: a 16-char × 5-column custom-character bargraph is the camera-friendly UI, and its STN viewing angle wants to face the camera squarely.)
- **Trimming procedure (both versions):** assemble the complete pod, submerge it in a bucket — it should sink *very* slowly. Add XPS foam (zip-tied or epoxied high on the pod) if it sinks fast, lead split shot (low on the pod) if it floats; iterate to barely-negative. Foam high + ballast low also keeps the pod upright. For the Dory version, first weigh the stock detector and bucket-test *it* — your pod should match its in-water behavior, not just "neutral," since the Dory's overall trim was factored around the original.

## 6. Firmware (C++, pico-sdk)

- **v3 (current, implemented in `src/detector-firmware/`):** `pi_engine` fires the coil (150 µs TX pulses at 100 Hz), captures the decay via ADC free-run, computes early/late-window integrals (strength + tau class), and auto-tunes damping code + digipot gain at boot. Route A "measure a kit's audio output" code is retired.
- **Drone backend:** RS-485 slave per `../ArchiveIdeas/PLAN.md` §5 — answers `IDENTIFY` ("metal-detector v1, strength 0–255"), streams `TEL_ACCESSORY` at ~10 Hz, `ACTION n` can trigger re-zero / sensitivity step.
- **Dory backend:** strength → LED bar (PWM the top segment for half-steps). Blink the full bar twice on power-up as a camera-visible self-test. Keep a slow "heartbeat" segment so a dead pod is distinguishable from "no metal."
- **Sounder (both backends):** detector-style audio encoding — beep cadence rises with signal strength (slow ticks → solid tone), pitch step on strong targets; startup plays a two-tone chirp as the audible self-test twin of the LED blink. Mute/unmute via a quick off-on flick of the power switch.
- Auto-zero on startup — **power on with the pod already mounted on the drone/Dory**, held away from other metal (no steel table, no tools under the coil). The host vehicle's own metal (thruster magnets, screws) is fixed relative to the coil, so it's a constant offset the zero subtracts; zeroing off-vehicle would leave the vehicle itself reading as a permanent target. Note in the web app / make it a launch-ritual habit.
- What zeroing does **not** remove: *running* thrusters produce time-varying EMI (throttle-dependent) that no static baseline can subtract — that's covered by coil standoff, firmware filtering, and the §7.3 interference test; worst case, read the detector in moments with props quiet ("hover to listen").
- Baseline also tracks slowly at runtime (temperature/battery drift). Side effect, classic for PI: a target parked under the coil for minutes fades into the baseline — detection is strongest in motion. Re-zero = power-switch off-on flick.

### v3 specification (2026-07-17, supersedes the v2 freeze — user decision: build the HAT)

v1/v2's bought front ends (Surf PI kit, Clone PI-AVR module) and the loose power/driver modules (DRV8833, TP4056, MT3608, perfboard) are **retired** — all of it moves onto one JLCPCB-assembled **Pico carrier HAT** (Route B: the Pico is the detector). Schematic spec: `docs/HAT-SCHEMATIC-SPEC.md`. Display/sensor/sounder decisions from v2 carry over unchanged.

- **Detection:** Route B on the HAT — Pico-timed TX pulses, direct decay sampling (ADC free-run), firmware auto-tune (settle measurement + MOSFET-switched damping bank + digipot RX gain), tau/target-character classification live.
- **MCU:** plain Pico (RP2040), socketed on the HAT.
- **Displays, side by side in the ≤1 cm band:** 8-pixel WS2812 strip (attention channel, auto-dims to 10 % on 2 s stable signal) + 0.91" SSD1306 128×32 OLED (detail channel, recessed, only glass in frame). LCD1602 = bench telemetry only. Discrete 10-LED bar from v1 is retired.
- **Sensors: none on the pod — depth comes from the host drone.** (MS5837-30BA dropped 2026-08-29, see the depth bullet in §5.)
- **Sounder:** potted piezo + DRV8833 push-pull, cadence/pitch encoding, unchanged from v1.
- **OLED layout (128×32):** left cols 0–79 **free since the depth sensor was dropped (2026-08-29) — reserved for tau detail** (decay-class readout; depth/temp digits that used to live here are gone, depth now logged topside from the drone's own `VFR_HUD`). Right cols 84–127: 14-px strength bar (rows 0–13), tau-class icon slot (rows 17–31). Heartbeat dot in the separator column. **Rejected: 1-px bars** — one OLED pixel is sub-pixel on the camera feed at mount distance and below diver acuity; information nobody can resolve is not information.
- **Power/housing/mount/trim:** as specified in §5/§8 (18650 + TP4056, reed switch, PVC pod, potted coil, printed bracket, XPS/lead trim).

### Build environment — how to recreate `src/` from empty

**Four scripts at the folder root do all of this** (added 2026-08-29; the
manual `git clone`/`curl` recipe they replaced is preserved in the version
history). See `README.md`.

```sh
./toolchain.sh    ARM cross-compiler 14.2.rel1     -> src/arm-gnu-toolchain-*
./sdk.sh          pico-sdk 2.3.0                    -> src/pico-sdk
./freerouting.sh  Freerouting 2.2.4 (KiCad routing) -> src/Freerouting.app
./build.sh        configure + build the firmware
```

macOS and Linux, Intel and ARM: each detects the host and picks the matching
download. Each finds an existing install and asks before replacing it, so
re-running is safe. Versions are pinned in the scripts, so a rebuild years from
now produces the same binary.

`picotool` needs no script — cmake fetches it on the first configure into
`src/picotool/`, most of which is build state rather than a checkout. That is
also why it is not a git submodule, and why `pico-sdk` is not either: this
folder is not its own repository, so a submodule would bind the parent repo's
history to a 37 MB upstream checkout it has no use for. The scripts give the
same pinning without that.

**Host prerequisites** (outside `src/`, likely already present):
- macOS: Xcode Command Line Tools (`xcode-select --install`), CMake ≥ 3.13,
  python3, git.
- Linux: `apt install build-essential cmake python3 git` — the host compiler
  builds the SDK's `pioasm`/`picotool` helpers.

`build.sh` checks for all of these and names whatever is missing instead of
failing part-way through a build.

Layout once fetched:

```
src/
├── arm-gnu-toolchain-14.2.rel1-<host>-arm-none-eabi/   ./toolchain.sh
├── pico-sdk/            2.3.0; submodules NOT initialised (USB stdio is off)
├── picotool/            cmake fetches this itself
├── Freerouting.app/     ./freerouting.sh
└── detector-firmware/   this firmware: CMakeLists.txt, config.h, main.c, ...
```

**None of the fetched content is in git** — 1.3 GB, none of it authored here.

Output: `src/detector-firmware/build/detector-firmware.uf2`. **Flash:** hold
BOOTSEL while plugging the Pico into USB, then copy the `.uf2` onto the
`RPI-RP2` drive that appears. Debug console: 115200 baud on UART0 (GP0 = TX).

The firmware pins the SDK location relative to itself (`../pico-sdk`) in
`CMakeLists.txt`, so no `PICO_SDK_PATH` environment variable is needed.
**v3 firmware scope:** Pico-native PI engine (TX gate GP17, decay on ADC0/GP26,
damping select GP10–12, digipot on SPI0), boot autotune + 2 s auto-zero + slow
baseline, WS2812 strip on GP13 with inspect auto-dim, SSD1306 OLED + MS5837 on
I2C0 (GP8/GP9) showing depth/temp/strength/tau, DRV8833 piezo push-pull on
GP14/GP15, self-test + telemetry on the debug UART (GP0). Pin map — which
**must match `docs/HAT-SCHEMATIC-SPEC.md`** — and all tuning constants live in
`config.h`.

## 7. Test protocol

0. **Cap/switch pressure soak:** assembled threaded plug with the IP68 toggle installed, in a water-filled pressure vessel (or weighted to depth) — verify no ingress and, critically, that pressure cannot flip the toggle. Gate for trusting the switch below snorkel depth; fallback if it weeps: dive-light style plug-tightening actuator (zero penetrations).

1. **Bench air test:** coin at ruler distances; log strength vs distance; expect 15–30 cm for a €2 coin, more for larger targets.
2. **Bucket test:** same targets underwater (fresh + salted water); PI should barely change.
3. **Interference test (critical):** pod mounted on the drone/Dory, thrusters running — record baseline noise at each throttle level. If noise swamps signal: increase coil standoff, add firmware notch (sample between motor PWM edges), or accept "hover to listen" operation.
4. **Field test:** planted targets (coin, ring, iron bar) on a sandy bottom at known spots; verify against camera + LED/app.

## 8. Parts list — **superseded by the v3 order list below** (the old Route A/B table with the Surf PI kit, discrete LED bar, and loose modules is retired; single source of truth is the order list)

### Order list (v3 HAT build, with spares — ~€145–190)

Search terms as you'd paste them into AliExpress/eBay; local hardware store for PVC/epoxy/screws.

Availability checked 2026-07-17, **revised for v3** (front-end kits and loose power/driver modules retired — that circuitry now lives on the HAT). **Sourcing policy: real shops with warranty/returns; no eBay/marketplaces** unless flagged ⚠️. NL/EU shops: TinyTronics, Kiwi Electronics (official RPi reseller), BerryBase, Conrad/Reichelt, nkon.nl, RobotShop EU / Blue Robotics, Gamma/Praxis/Hornbach.

| Item (search term) | Spec to verify | Qty | ~€ | Real-shop source |
|---|---|---|---|---|
| **HAT PCB, assembled** (per `docs/HAT-SCHEMATIC-SPEC.md`) | JLCPCB economic SMT assembly; min 2 assembled of 5 boards | 2 asm | 50–80 | ✅ JLCPCB (real vendor, remakes defective boards) |
| **3× male 1×2 pin header 2.54 mm** (mate J1 piezo, J2 power-switch, J3 5V-charge corner/edge sockets) + **1×4 female socket** (nose, mates board's right-angle coil header) | plug/dock mating halves | 3 + 3 spares | 3 | ✅ TinyTronics / Conrad |
| **micro-USB breakout jack** (housing-mounted; 5V + GND out) → wires to J3 | external charge port (no on-board USB now; TP4056 charges from the 5V) | 1 | 2 | ✅ TinyTronics / Kiwi Electronics |
| **pre-crimped JST-GH cables: 1× 4-pin** (J6 OLED) **+ 2× 3-pin** (J8 WS2812 strip, J9 debug) | mate the top-side GH docks; cut & splice per harness note below | 3–5 | 6 | ✅ TinyTronics / Pixhawk-cable vendors |
| silicone hookup wire 26 AWG (piezo + power-switch pigtails to the J1/J2 male headers; coil) | loom | — | 6 | ✅ TinyTronics |
| **Weipu SP17-2** panel socket + cable plug pair | coil bulkhead in the nose cap; 500 V/10 A/IP68 rated | 1 pair | 10–15 | ✅ TME / Conrad / SOS Solutions |
| "Raspberry Pi Pico H" | RP2040, pre-soldered headers; not W/2 | 2 | 12 | ✅ Kiwi Electronics / BerryBase / TinyTronics |
| "0.91 inch OLED module 128x32 I2C SSD1306" | I2C 4-pin, 3.3 V | 2 | 6–10 | ✅ TinyTronics / BerryBase |
| "WS2812B 8 bit LED stick" | rigid 8-LED PCB stick | 2 | 4 | ✅ TinyTronics / BerryBase |
| "piezo element 27mm" (or 35 mm) | bare brass disc | 2+ | 3 | ✅ TinyTronics / Conrad / Reichelt |
| Brand 18650: "Samsung INR18650-35E"/"LG MJ1"/"NCR18650GA" | genuine cells | 1–2 | 6–14 | ✅ nkon.nl |
| MYOUNG BH-18650-A6AJ002 18650 holder (LCSC C19184085) | THT, mid-board bottom, JLC-assembled | 1 | 3 | ✅ LCSC / TinyTronics / Conrad |
| miniature **IP68 sealed toggle switch** with silicone boot (APEM/Bulgin class) | panel-mount in the threaded plug; **toggle, not pushbutton** (boot pushbuttons self-press at ~1.5 bar) | 1 | 8–15 | ✅ Conrad / RS Components |
| "enameled copper wire **0.6mm**" 100 g | coil (~28 turns, 20 cm ring → ~1.1 Ω — in the 1–2 Ω window; 0.4 mm rejected: ~2.4 Ω throttles the TX pulse) | 1 | 6 | ✅ Conrad / Reichelt / TinyTronics |
| 50 mm PVC pipe + end cap + threaded cleanout plug | pressure-type fittings | 1 set | 5 | ✅ Gamma / Praxis / Hornbach |
| Polycarbonate sheet 2–3 mm | window | 1 | 3 | ✅ Gamma / Hornbach |
| Clear slow-cure epoxy ~250 g + 5-min epoxy | potting/window/piezo | 1+1 | 12 | ✅ Hornbach / Polyestershoppen.nl |
| Lead split shot + XPS foam | trim | — | 4 | ✅ fishing shop / Gamma |
| "A4 stainless screw assortment M3 M4" + nylon lock nuts | bracket | 1 box | 8 | ✅ Hornbach / Conrad |
| "nylon standoff screw nut assortment M2 M3" | Pico-to-HAT bolting (2.1 mm holes, 11.4×47 mm pattern) + HAT-to-cradle; nylon = no eddy target | 1 box | 6 | ✅ TinyTronics / Conrad |
| Neutral-cure silicone + silicone grease | sealing | 1+1 | 6 | ✅ Gamma / Hornbach |
| PETG/ASA filament (~50 g used) | bracket print | if needed | 0–20 | ✅ 123-3D.nl / TinyTronics |
| "CP2102 USB UART TTL adapter 3.3V" | debug console | 1 | 3 | ✅ TinyTronics / BerryBase |
| Waveshare "LCD1602 I2C Module" | bench telemetry (optional) | 0–1 | 6 | ✅ BerryBase / Waveshare shop |

### Interconnect map (what plugs into what, and how)

Harness pattern: **cut a pre-crimped GH cable in half → two pigtails → solder-splice to the part's wires/pads → heat-shrink.** No crimp tool; a soldering iron is needed for the ~6 splice jobs below ("solder-free" applies to the board, not the harness).

| HAT conn | Type | Connects to | Joining method | Use |
|---|---|---|---|---|
| BT1 | 18650 clips, soldered mid-board **bottom side** | the cell itself | cell snaps in; pull-ribbon for removal | main power; low CG for trim |
| J3 | 1×2 socket 2.54 mm at the north edge (between J1 and J2) | external housing-mounted micro-USB jack, 5V+GND pigtail | male 1×2 header plugs in | charging (USB-C + CC resistors R3/R4 dropped) |
| J4 coil dock | 1×4 right-angle male header, south edge, **outer pins only (7.62 mm gap — safe for the 300 V flyback**; adjacent 2.54 mm pins are only ~250 V-rated) → nose 1×4 female socket → **SP17-2 bulkhead** (500 V/10 A/IP68) | coil pigtail outside; board docks by sliding in | horizontal header mate | coil |
| J6 | top-side GH 4-pin (by R31/R32) | OLED, glued above the board | GH cable plugs in from above | display, wired straight up to the window |
| J7 | top-side GH 4-pin (by R31/R32) | **free I²C port (formerly depth meter)** — MS5837 dropped 2026-08-29; left fitted for any future I²C device | — | free I²C |
| J8 | top-side GH 3-pin (by R31/R32) | WS2812 strip, glued above the board | GH cable plugs in from above | LED bar |
| J1, J2 | 1×2 sockets 2.54 mm at board corners | J1 piezo, J2 power switch | male 1×2 header pigtails plug in | sounder + power switch |
| J9 | GH 3p | CP2102 adapter (bench) | pigtail → DuPont | debug console |
| Pico socket | 2×20 | Pico H, **top side** with all connectors | plug + nylon M2 standoffs | MCU; micro-USB = flashing |

Per-connector pin map (J5 2×6 dock retired 2026-07-24): **J1** 1 PIEZO_P · 2 PIEZO_N · **J2** 1 REED(switch) · 2 GND · **J3** 1 VBUS_C(5 V from ext micro-USB) · 2 GND · **J6** (and free **J7**) 1 3V3 · 2 SDA · 3 SCL · 4 GND · **J8** 1 VBAT_SW · 2 WS_DATA · 3 GND.
**Standing rule: the OLED and the WS2812 LED PCB are wall-mounted at the window, never board-soldered.**

Confirmed TinyTronics picks (2026-07): Pico H, WS2812B 8-LED stick (black), 35 mm piezo with soldered wires, 0.91" OLED 128×32 I2C, SynFlex W210 0.6 mm 250 g (polyurethane enamel — solderable, tin-in-blob works), alarm-style reed door switch + magnet.

**Removed in v3** (absorbed by the HAT): Surf PI kit, Clone PI-AVR module, DRV8833 module, TP4056 module, MT3608 modules, perfboard/hand-wiring. **Total: ~€145–190** (HAT assembly replaces ~€30 of modules/kits and removes nearly all hand-soldering; the enamel coil ends remain the one soldered joint). Warnings: -30BA not -02BA; marketplace 18650s are routinely counterfeit.

## 9. Comparison: stock Chasing detector vs this DIY pod

Public documentation of the stock unit is thin: LED alert and "22 mm coin at 4 cm" are published; the diver-audible beeper is per owner observation (not in the public specs found); technology, power source, and adjustability are undocumented. "Advantage" = which one you'd rather have for that row.

| Feature | Stock Chasing detector | DIY pod (this plan) | Advantage |
|---|---|---|---|
| Price | only inside the Dory Explore bundle (~€480–600); not sold separately | ~€145–190 in parts (v3 HAT, incl. spares) | **DIY** |
| Time to working unit | zero — arrives working | 3–5 evenings + tests | **Stock** |
| Detection range | 22 mm coin at ~4 cm | coin-class target at 15–30 cm (PI, 20 cm coil) | **DIY** (the headline win) |
| Metal types | "ferrous" per press coverage | all conductive: gold, silver, bronze, iron | **DIY** |
| Technology | undocumented (pinpointer-class) | pulse induction — documented, understood, tunable | **DIY** |
| Visual alert | single flashing red LED (binary: metal / no metal) | WS2812 strip (strength/color) + OLED (depth, temp, tau class) | **DIY** |
| Diver-audible sound | yes (owner-observed) | yes — potted piezo disc, beep cadence encodes strength, mutable | **tie**, DIY richer encoding |
| Machine-readable output | none — eyes on video only | RS-485 `TEL_ACCESSORY` data on the DIY drone backend (Dory backend: optical only, like stock) | **DIY** (platform-dependent) |
| Sensitivity adjustment / re-zero | none documented | firmware-tunable; re-zero via `ACTION`/power-cycle | **DIY** |
| EMI coexistence with thrusters | factory-engineered and validated for the Dory | unknown until §7.3 test; may need standoff / hover-to-listen | **Stock** |
| Trim / buoyancy match | factory-matched to the Dory | manual bucket-trim procedure (§5) required | **Stock** |
| Waterproofing & reliability | factory-sealed, warranty, IP-rated with the Dory | DIY potting + soak tests, no warranty | **Stock** |
| Zeroing ritual | none — switch on and go | must power on mounted, clear of foreign metal | **Stock** |
| Net mount | stock net clips on | clip interface must be replicated if the net is wanted | **Stock** |
| Size / weight | compact, engineered | bulkier pod (50 mm PVC + 20 cm coil ring) | **Stock** |
| Repairability | sealed unit — replace on failure | every part replaceable, coil rewindable | **DIY** |
| Works on other platforms | Dory-only mount | dual backend: DIY drone (RS-485) *and* Dory (optical/audio) | **DIY** |
| Behavior data for tuning | black box | full decay-curve access (v3 PI engine) | **DIY** |

**Score-keeping summary:** the stock unit wins every "it just works" row (integration, trim, EMI, sealing, zero effort); the DIY pod wins every *performance and openness* row — and the range row alone (4 cm vs 15–30 cm) decides the matter for actual treasure hunting, since a 4 cm range effectively requires dragging the coil on the target.

## 10. Stages (v3)

1. Order everything (order list above) + submit the HAT to JLCPCB once layout is done.
2. Bench bring-up, HAT + Pico, no coil: rails (12 V / 9 V / 3V3), OLED, strip, sounder — firmware degrades gracefully, so each subsystem can be checked alone.
3. Coil wound + potted -> autotune session with the scope on RX: verify damping selection, settle time, gain walk; calibrate `FULL_SCALE_SIGNAL` and tau thresholds against test targets (coin, ring, iron).
4. Air + bucket detection tests (§7.1-7.2); record numbers in this file.
5. Pod build: housing, windows, trim (§5); Dory bracket printed and fitted.
6. On-Dory interference test (§7.3) and field test (§7.4).
