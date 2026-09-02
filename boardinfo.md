# Reverse-Engineering Notes: CHASING DORY Main Controller / 5-Channel BLDC ESC Board

## Scope

This document consolidates the observations and inferences made from
photographs of the circular controller PCB, **plus** what has since been read
directly off the running vehicle over MAVLink (section 2a). Where the two
disagree, the vehicle wins.

The board combines:

- a main STM32F407 vehicle-control processor running **ArduSub**,
- a card socket, probably microSD (section 6),
- multiple serial/debug/test interfaces, including STM32 `BOOT0`,
- battery/power distribution,
- and five independent three-phase brushless motor controller channels, each
  with its own microcontroller and exposed programming pads.

Statements are separated into **direct observations** and **inferences**, each
carrying a confidence label. Nothing here has been electrically traced or
measured: no continuity testing, no scope, no meter. Every claim about a
*connection* is therefore inference from layout and part choice, however
confident it sounds.

---

# Confidence legend

| Label | Meaning |
|---|---|
| **CERTAIN** | Directly readable in the photographs, or follows unambiguously from a clearly identified component/connection. |
| **VERY HIGH** | Strongly supported by several independent observations, but not electrically traced or measured. |
| **HIGH** | Strong inference from component choice, repetition, layout, or known architecture. |
| **MODERATE** | Plausible and technically consistent, but alternatives remain. |
| **LOW / GUESS** | Speculative. Included because it may guide further investigation, not because it is established. |

---

# 1. Overall board identity

## Likely product

**Inference: VERY HIGH confidence**

The PCB is very likely the **main control board from a CHASING DORY underwater ROV**, rather than a conventional aerial flight controller.

Reasons:

1. The PCB is a distinctive circular/irregular OEM shape rather than a standard hobby flight-controller form factor.
2. There are **five repeated three-phase motor-control channels**, matching the five-thruster architecture of the CHASING DORY.
3. Silkscreen near the heavy wiring appears to read **`BUOY_IN`**, which fits a tethered underwater vehicle using a surface communications buoy.
4. The system voltage markings are compatible with a nominal 12 V / 3S lithium battery architecture.
5. A replacement board sold as a CHASING DORY main board appears to have the same unusual physical outline.

**Not certain because:** no explicit "CHASING DORY" model name or manufacturer logo is visible in the provided close-up photographs.

---

# 2. Main MCU

## STM32F407VGT6

**Observation: CERTAIN**

The main processor marking is readable:

`STM32F407`
`VGT6`

Therefore the main MCU is an **STMicroelectronics STM32F407VGT6** in a 100-pin LQFP package.

### Relevant capabilities

**Component specification: CERTAIN**

The STM32F407VGT6 is an ARM Cortex-M4F MCU with, among other features:

- up to 168 MHz CPU clock,
- hardware floating point,
- 1 MiB Flash,
- substantial SRAM,
- multiple UART/USART peripherals,
- SPI,
- I2C,
- CAN,
- USB OTG,
- SDIO,
- ADCs,
- many general-purpose timers and PWM outputs,
- SWD/JTAG debug support.

### Likely role

**Inference: VERY HIGH**

The STM32F407 is almost certainly the **main vehicle-control processor**.

Likely responsibilities include:

- overall vehicle state,
- attitude/depth control,
- motor command generation,
- communications,
- telemetry,
- sensor acquisition,
- power/status monitoring,
- microSD logging/configuration,
- coordination of the five independent motor-control MCUs.

---

# 2a. The firmware is known — it is ArduSub

**Observation: CERTAIN, from the vehicle rather than the photographs**

This document was written from photographs alone. It does not need to
speculate about the firmware: the running vehicle has been interrogated over
MAVLink and **all 588 parameters read off it**.

It is **ArduSub**, an ArduPilot vehicle firmware. The underwater-only
parameters settle it — they exist in no other ArduPilot build:

```
FS_LEAK_ENABLE   FS_PRESS_ENABLE   FS_TEMP_ENABLE
SURFACE_DEPTH    GND_SPEC_GRAV     MOT_1..8_DIRECTION
```

alongside eight core ArduPilot families (`AHRS_ ATC_ BRD_ COMPASS_ EK2_ INS_
RC1_ SR0_`).

This closes or narrows several questions raised later in this document:

| parameter | value | what it settles |
|---|---|---|
| `RC_SPEED` | 490 | the STM32 drives the ESCs with **plain PWM at 490 Hz**, not a serial protocol (section 17) |
| `BRD_PWM_COUNT` | 6 | six outputs: 1-5 the thrusters, 6 the light |
| `RC6_FUNCTION` | 56 | output 6 is RCIN6 pass-through — the light |
| `COMPASS_DEV_ID` | 68873 | compass on **I2C bus 1, address 0x0D** — an HMC5883/QMC5883-class part (section 20) |
| `BATT_MONITOR` | 5 | analogue voltage **and** current sensing is configured (section 18) |
| `BATT_CAPACITY` | 3898 | the pack the firmware expects, in mAh |
| `FS_BATT_VOLTAGE` | 10.5 | low-voltage failsafe threshold, consistent with 3S (section 7) |
| `ARMING_CHECK` | 0 | pre-arm checks disabled |
| `FRAME` | 1 | VECTORED frame, and **`FRAME` not `FRAME_CONFIG`** dates it to an older ArduSub |
| `FS_PRESS_ENABLE` | 0 | an **internal** pressure failsafe exists in firmware, whether or not the sensor is fitted (section 21) |

It also reports **flight sw 1.1.6** with board, vendor and product ids all
zero — Chasing's own numbering, and a build that does not identify its board.

**Consequence for section 27:** an ArduPilot port is not a hypothetical. The
vehicle already runs one. The open question is not *whether* ArduPilot can run
on this hardware but *which* board definition Chasing used, and that is what
the zeroed board id withholds.

---

# 3. Main STM32 test pads / interfaces

The photographs show several labelled test pads around the STM32.

## Readable labels

**Observation: CERTAIN**

Visible labels include some or all of:

- `3V3`
- `PE1`
- `GND`
- `BOOT0`
- `RX1`
- `TX1`
- `RX2`
- `TX2`
- `RX3`
- `TX3`
- `RX0`
- `TX0`
- `RX`
- `TX`
- `RST`

Other pads elsewhere include:

- `SCL`
- `SDA`

### Interpretation

**Inference: VERY HIGH**

- `RXn/TXn` pairs are UART/USART test or subsystem interfaces.
- `SCL/SDA` are I2C.
- `RST` is MCU reset.
- `BOOT0` is the STM32 boot-mode strap.
- `3V3` and `GND` are logic power references.

### Why this matters

**Inference: HIGH**

These pads make the board unusually friendly to reverse engineering. They may allow:

- serial console discovery,
- firmware update/recovery,
- factory diagnostics,
- protocol sniffing,
- bootloader access.

---

# 4. STM32 SWD access

## SWD likely exists somewhere

**Inference: VERY HIGH**

The STM32F407 supports SWD through:

- PA13 = SWDIO
- PA14 = SWCLK

The photographs do not clearly show pads labelled `SWDIO` or `SWCLK`, but the traces should exist.

### Recommended investigation

**Recommendation, not an observation**

With power removed:

1. Locate PA13 and PA14 on the STM32 package.
2. Trace continuity to nearby pads/vias.
3. Identify:
   - SWDIO
   - SWCLK
   - GND
   - 3V3 reference
   - NRST
4. Connect an ST-Link without writing anything.

### Firmware-preservation warning

If readout protection is enabled, **do not perform any "unlock" or mass-erase operation** unless losing the original firmware is acceptable.

---

# 5. STM32 ROM bootloader

## BOOT0 pad

**Observation: CERTAIN**

A pad labelled `BOOT0` is visible.

### Implication

**Inference: VERY HIGH**

This can probably be used to force the STM32 into its factory ROM bootloader, depending on the state of the other boot configuration pins.

Because several UART pads are exposed, the board may be serviceable through a factory serial boot path.

### Warning

Use **3.3 V logic levels**, not 5 V TTL, unless electrical tracing proves a level translator is present.

---

# 6. Card socket — probably microSD

This section was revised after the claim was challenged. The original text read
"Observation: CERTAIN — a microSD card socket is fitted", which conflated three
separate claims that deserve three separate confidences.

## A hinged-lid metal card socket is fitted

**Observation: CERTAIN**

A metal-shelled socket with a hinged lid is present beside the STM32. The shell
carries the standard `OPEN` and `LOCK` arrows, which is the flip-top card-holder
convention: slide the lid to unlatch, flip up, seat the card, close, slide to
lock. Both markings are legible in the photographs.

## That it is specifically microSD

**Inference: HIGH, not certain**

For:

- the size relative to the STM32's 14 mm LQFP100 body is consistent with a
  microSD holder (card 11 x 15 mm, socket about 14 x 15 mm);
- the contact count appears to be 8 signal plus mechanical tabs, which matches;
- the host MCU has native SDIO, so a card interface is a natural fit.

Against certainty:

- a hinged metal lid with `OPEN`/`LOCK` is also how **SIM** and some other card
  holders are marked, and the two are similar in size;
- the pin count has not been counted reliably from the available angles;
- nothing has been traced electrically.

A SIM socket in a tethered underwater ROV with no cellular hardware would be
odd, which is why this sits at HIGH rather than MODERATE — but "odd" is not
"impossible", and OEMs do reuse a PCB across product variants.

## Whether a card is actually in it

**NOT OBSERVED**

No card is visible in any photograph, and the lid state cannot be judged
reliably from the angles available. **Do not assume the socket is populated.**

This matters more than it first appears. The product manual lists
`STORAGE 16G` under **BUOY**, not DRONE, and the media API is served from the
buoy at 192.168.1.1. So the media does not live here. A socket on the drone
board is therefore most likely one of:

- an ArduPilot dataflash log card (see section 6a) — populated;
- a firmware or calibration carrier used in manufacturing — possibly removed;
- a footprint fitted but never populated in this product — empty.

### How to settle it in a minute

1. Look at the socket. If a card is in it, the edge is visible at the slot.
2. If empty, that closes the question.
3. If populated, read it on a computer. `LOGS/` or `.BIN` files mean ArduPilot
   dataflash logging, and those logs would answer several open questions
   elsewhere in this project directly from recorded data.

## 6a. If it is a log card, that is valuable

**Inference: MODERATE, conditional on the above**

The vehicle is confirmed to run ArduSub (section 2a). ArduPilot writes
dataflash logs to SD when one is fitted, and those logs contain RC inputs,
motor outputs, attitude and depth together — which is exactly the data needed
to confirm which thruster each RC channel drives, without a physical test.

### Likely uses if populated

- vehicle logs,
- diagnostic logs,
- configuration or calibration data,
- firmware packages.

It should **not** be assumed to store camera video.

---

# 7. Battery and power system

## Heavy battery input

**Observation: CERTAIN**

Large red and black wires are soldered directly to the PCB near silkscreen including:

- `BATTERY`
- `+`
- `-`

Other nearby power labels include:

- `12V0`
- `12V_OUT`

### Battery architecture

**Inference: VERY HIGH**

The system is very likely based around a nominal **12 V / 3-cell lithium battery**.

A typical 3S lithium battery has:

- nominal voltage around 11.1 V,
- fully charged voltage of 12.6 V.

This fits:

- the `12V` silkscreen,
- the 30 V-rated motor MOSFETs,
- the likely CHASING DORY application.

### Caveat

The exact allowed input-voltage range is **not established from the photographs alone**.

Do not assume arbitrary 12 V supplies are safe without checking the actual power-regulation and protection circuitry.

---

# 8. `BUOY_IN`

## Silkscreen

**Observation: HIGH confidence**

The marking near the heavy cable appears to read:

`BUOY_IN`

Earlier it could have been mistaken for `BOOT_IN`.

### Interpretation

**Inference: VERY HIGH**

If this is a CHASING DORY board, `BUOY_IN` is logically associated with the vehicle's tether / surface buoy connection.

This may carry:

- communications,
- control data,
- telemetry,
- and possibly power or auxiliary signalling.

### Physical-layer guess

**Inference: LOW / GUESS**

Because the link is long and runs through a tether, it would be reasonable for the design to use a robust differential physical layer rather than raw 3.3 V UART.

Possible examples include:

- RS-485-like signalling,
- CAN-like differential signalling,
- a custom differential link.

No transceiver has yet been positively identified, so this remains speculative.

---

# 9. Small white 2-pin connector

## Connector

**Observation: CERTAIN**

A small white two-wire connector with red and black leads is fitted near the microSD socket.

### Exact series

**Inference: LOW / GUESS**

It resembles a small JST-family wire-to-board connector, but the exact series cannot be determined confidently from the photograph alone.

Candidates could include:

- JST-PH,
- JST-GH,
- or a compatible clone.

Measure the pin pitch before ordering mating parts.

### Relationship to I2C pads

**Observation / inference: HIGH**

The nearby `SCL` and `SDA` test pads appear separate from this 2-wire connector, so the connector itself is probably not directly an I2C connector.

---

# 10. Five motor-control channels

## Channel labels

**Observation: CERTAIN**

The PCB contains repeated sections labelled:

- `CH1`
- `CH2`
- `CH3`
- `CH4`
- `CH5`

### Architecture

**Inference: CERTAIN to VERY HIGH**

The close-ups establish that these are **five independent three-phase brushless motor controller / ESC channels**.

The previous possibility that they might be brushed H-bridges can now be rejected.

Each channel contains a repeated combination of:

- one Silicon Labs EFM8 microcontroller,
- one Fortior three-phase gate driver,
- six power MOSFETs,
- three SS34 diodes,
- supporting passives,
- local programming/debug pads.

This is a textbook distributed BLDC ESC architecture.

---

# 11. Per-channel ESC microcontroller

## Silicon Labs EFM8BB21F16G

**Observation: CERTAIN**

The small QFN/TQFP-style motor-control MCU markings include:

`BB21`
`F16G`

This identifies the part as a **Silicon Labs EFM8BB21F16G**.

### Relevant characteristics

**Component specification: CERTAIN**

The EFM8BB21 is an enhanced 8051-family MCU commonly used in compact ESC designs.

Relevant features include:

- high-speed 8051-compatible core,
- Flash program memory,
- ADC,
- timers/PWM,
- serial peripherals,
- Silicon Labs C2 debug/programming interface.

### Role

**Inference: CERTAIN**

Each EFM8BB21 controls one motor/ESC channel.

Likely tasks:

- commutation timing,
- PWM generation,
- back-EMF measurement,
- startup sequencing,
- motor speed/direction handling,
- fault handling,
- processing a command signal from the main STM32.

---

# 12. C2 programming/debug pads

## Labels

**Observation: CERTAIN**

Near the individual motor-control sections are pad labels such as:

- `C2CK`
- `C2D`

with corresponding channel-related groupings.

### Interpretation

**Inference: CERTAIN**

These are the **Silicon Labs C2 debug/programming interface** signals for the EFM8BB21 devices.

### Importance

Each ESC MCU may therefore be independently:

- identified,
- debugged,
- programmed,
- and possibly read out if flash security is not enabled.

### Critical warning

Do not issue an unlock operation without first establishing whether it erases protected flash.

Preserve original firmware before modifying anything.

---

# 13. Three-phase gate driver

## Fortior FD6288Q

**Observation: CERTAIN**

The repeated gate-driver IC is clearly marked:

`FORTIOR`
`FD6288Q`

### Role

**Inference: CERTAIN**

The FD6288Q is a **three-phase high/low-side MOSFET gate driver**.

It drives six N-channel MOSFETs arranged as:

- 3 high-side switches,
- 3 low-side switches.

### Per-channel signal chain

**Inference: VERY HIGH**

For each thruster, the likely path is:

`STM32F407 -> EFM8BB21 -> FD6288Q -> 6 MOSFETs -> 3-phase BLDC thruster`

This is almost certainly repeated five times.

---

# 14. Power MOSFETs

## AO4406A

**Observation: CERTAIN**

The repeated SOIC-8 power devices are marked:

`4406A`

with the Alpha & Omega Semiconductor logo.

These are **AO4406A N-channel MOSFETs**.

### Role

**Inference: CERTAIN**

They are the six power switches forming each three-phase inverter.

### Count

**Inference: VERY HIGH**

A three-phase BLDC inverter needs six MOSFETs:

- 3 high side,
- 3 low side.

Five channels therefore require:

`5 x 6 = 30 MOSFETs`

The large repeated population of AO4406A devices matches this exactly.

---

# 15. SS34 diodes

## Identification

**Observation: CERTAIN**

Large diodes are marked:

`SS34`

### Component type

**Component identification: CERTAIN**

SS34 is a 3 A / 40 V-class Schottky rectifier family.

### Function here

**Inference: HIGH**

Because three SS34s are grouped with each three-phase gate-driver section, they are most likely part of the **bootstrap supply circuits** for the three high-side gate drivers.

Each high-side N-channel MOSFET needs a gate voltage above its switching-phase node; bootstrap diodes and capacitors are commonly used to produce that floating gate-drive supply.

Other auxiliary rectification roles are possible, but the repeated one-per-phase placement makes bootstrap use the strongest explanation.

---

# 16. ESC firmware lineage

## Similarity to BLHeli_S-era hardware

**Inference: HIGH**

The combination:

- EFM8BB21,
- discrete three-phase gate driver,
- six N-channel MOSFETs,

is strongly characteristic of the **BLHeli_S generation** of hobby BLDC ESC hardware.

### Important distinction

**NOT ESTABLISHED**

This does **not** prove that the board runs BLHeli_S.

The original firmware may be:

- fully proprietary,
- based on vendor code,
- derived from a common ESC codebase,
- or heavily customized.

### Bluejay possibility

**Inference: MODERATE**

Modern open-source firmware such as **Bluejay** supports EFM8 Busy Bee ESC MCUs, including BB21-family hardware.

However, flashing Bluejay is **not safe without first mapping the hardware pins and finding or creating a compatible target**.

An incorrect target can drive a high-side and low-side MOSFET simultaneously, creating shoot-through and likely damaging the ESC.

---

# 17. Likely control link from STM32 to each EFM8

## What is known

**Observation: CERTAIN**

The STM32 and five EFM8 devices coexist on the same board.

### Command protocol

**Inference: UNKNOWN**

The exact main-MCU-to-ESC protocol has not been established.

Possible mechanisms include:

- conventional servo PWM,
- OneShot-like pulse signalling,
- DShot-like digital signalling,
- UART,
- proprietary pulse protocol,
- direct GPIO timing.

### How to determine it

**Recommended measurement**

Use a logic analyser while operating one motor at low power and probe the EFM8 input lines.

Record:

- idle state,
- startup sequence,
- command pulse/frame rate,
- signal amplitude,
- direction changes,
- throttle changes.

---

# 18. Current sensing

## What is visible

**Observation: UNCERTAIN**

No obvious large five-channel current-shunt arrangement has been identified from the provided top-side close-ups.

### Inference

**Inference: MODERATE**

The ESCs may have limited or no per-motor current measurement.

Battery-level current measurement could exist elsewhere.

### Recommended improvement

A modern redesign would benefit from **per-thruster current sensing**.

Benefits:

- jam detection,
- fouling detection,
- motor health monitoring,
- thrust estimation,
- power limiting,
- fault isolation,
- better telemetry.

---

# 19. Main oscillator

## Crystal / oscillator

**Observation: CERTAIN**

A small metal/gold crystal or oscillator package is located beside the STM32.

### Frequency

**Inference: UNKNOWN**

The marking has not yet been read clearly.

An 8 MHz crystal would be plausible for an STM32F407 design, but this is only a common-value guess and **must not be assumed**.

Measure it or read the marking.

---

# 20. Sensors: IMU, pressure/depth, compass

## Current observation

**Observation: HIGH confidence**

No obvious, positively identified IMU, barometer/depth sensor, or magnetometer has been identified on the photographed side of this PCB.

### Possible explanations

**Inference: MODERATE**

One or more sensors may be:

- on the reverse side,
- on another PCB connected by ribbon/flex,
- near the mechanically central taped/marked region,
- on a dedicated camera/sensor assembly.

### Why remote sensors would make sense

**Inference: HIGH**

Keeping inertial sensors away from:

- 30 MOSFETs,
- five motor inverters,
- high-current copper,
- switching edges,

is electrically and mechanically sensible.

A separate sensor board could provide cleaner inertial data.

---

# 21. Gold square / central hole feature

## Observation

**Observation: CERTAIN**

A square gold feature with a central circular opening is present near the upper-center region, with passives and traces around it.

### Function

**Inference: LOW / GUESS**

Possible interpretations include:

- bottom-port pressure-sensor interface,
- mechanical pressure opening,
- RF/contact structure,
- calibration/test feature,
- mechanical/electrical fixture point.

A bottom-port pressure-sensor opening is an attractive possibility for an underwater vehicle, but there is not enough evidence to identify it confidently.

---

# 22. Unidentified 16-pin IC

## Visible marking

**Observation: HIGH confidence**

A relatively large 16-pin IC is marked approximately:

`HB1621S`

with a code resembling:

`1927`

### Date-code interpretation

**Inference: MODERATE**

`1927` could plausibly be:

- year 2019,
- week 27.

This is a common semiconductor date-code format.

### Exact device identity

**Status: UNKNOWN**

No reliable IC identification was established from the marking.

Searches for `HB1621S` tend to return an unrelated RC servo rather than a semiconductor datasheet.

Possible explanations:

- one or more characters are being misread,
- it is a regional/vendor-specific part,
- it uses a house code,
- it is custom-marked.

### Possible role

**Inference: LOW / GUESS**

Possible functions include:

- communications interface,
- bus buffer,
- multiplexer,
- line driver,
- memory/interface device,
- custom ASIC.

No assignment should be considered reliable without tracing pins or obtaining a better marking.

---

# 23. Approximate product era

## Date estimate

**Inference: HIGH**

The component choices and visible lot/date markings fit roughly the **late-2010s / around-2019 design era**.

Evidence includes:

- STM32F407 generation,
- EFM8BB21 ESC architecture,
- AO4406A MOSFETs,
- a possible `1927` date code,
- apparent match to the CHASING DORY platform introduced around that period.

---

# 24. Design quality assessment

## Positive aspects

**Engineering assessment: HIGH confidence**

The board shows several signs of deliberate and competent design:

- five repeated modular ESC channels,
- one local MCU per thruster,
- dedicated gate-driver ICs,
- substantial power-distribution copper,
- many test points,
- exposed C2 programming points,
- exposed STM32 BOOT0/reset/UART access,
- microSD storage,
- labelled power rails,
- clear channel markings.

The distributed architecture means the STM32 does not need to perform five real-time sensorless motor-commutation loops itself.

That is a strong architectural choice.

---

# 25. Potential weaknesses / upgrade opportunities

These are design recommendations, not assertions that the original board is faulty.

## 25.1 MOSFET modernization

**Assessment: HIGH**

AO4406A was reasonable for its era, but modern 30–40 V MOSFETs can offer substantially lower RDS(on), better thermal packages, and improved efficiency.

Potential benefits:

- less heat,
- less voltage drop,
- higher continuous-current margin,
- improved sealed-enclosure thermal performance.

### Caveat

A replacement cannot be chosen from RDS(on) alone.

Important parameters include:

- gate charge,
- gate threshold,
- drain voltage rating,
- avalanche capability,
- SOA,
- thermal impedance,
- package/pinout,
- FD6288 drive capability.

---

## 25.2 Gate-driver modernization

**Assessment: MODERATE-HIGH**

A modern redesign could use three-phase drivers with more diagnostics and protection, such as:

- programmable deadtime,
- programmable slew rate,
- stronger fault reporting,
- integrated current-sense amplifiers,
- improved undervoltage handling,
- shoot-through diagnostics,
- overcurrent interfaces.

The existing FD6288Q is still a valid architecture.

---

## 25.3 Per-motor current measurement

**Recommendation: HIGH**

Add explicit current sensing on each thruster.

This would enable:

- stalled-propeller protection,
- fouling detection,
- degraded-motor diagnostics,
- power budgeting,
- current limiting,
- per-motor telemetry.

This is probably one of the highest-value functional upgrades.

---

## 25.4 Improved transient protection

**Recommendation: HIGH**

A redesign should verify or add:

- input TVS protection,
- reverse-polarity protection,
- eFuse or fuse protection,
- sufficient bulk capacitance,
- clean separation of power and logic return currents.

With five BLDC inverters on one battery rail, bus transients can be substantial.

---

## 25.5 Better debug connectors

**Recommendation: HIGH**

Instead of test pads only, a revised PCB could include unpopulated standardized headers for:

- STM32 SWD,
- EFM8 C2,
- UART console,
- CAN,
- I2C.

A compact 10-pin Cortex debug footprint would make STM32 development much easier.

---

## 25.6 USB-C

**Recommendation: MODERATE**

A modern redesign could expose USB-C for:

- DFU,
- firmware update,
- logging,
- diagnostics,
- serial communication.

Only USB 2.0 is needed.

---

## 25.7 Improved sensor isolation

**Recommendation: HIGH if sensors share this PCB**

If inertial sensors are on the same PCB, improve:

- distance from motor phases,
- dedicated low-noise power,
- filtering,
- ground return,
- mechanical vibration isolation.

If the sensors are already on a separate board, the original designers may already have addressed this well.

---

## 25.8 CAN or robust differential internal links

**Recommendation: MODERATE**

For future distributed subsystems, CAN or another robust differential bus could improve noise immunity compared with long single-ended serial links.

Whether this is useful depends on the existing tether and subsystem architecture.

---

# 26. Should the STM32F407 be replaced?

## Existing MCU adequacy

**Assessment: HIGH**

The STM32F407 remains perfectly capable of:

- attitude loops,
- depth loops,
- mixer calculations,
- communications,
- basic filtering,
- logging,
- system supervision.

Replacing it is not automatically necessary.

## When a newer MCU helps

**Recommendation: MODERATE**

An STM32H743/H753-class redesign could provide:

- much more CPU performance,
- more RAM,
- larger modern middleware headroom,
- more advanced navigation filters,
- heavier DSP,
- larger sensor suites,
- improved networking options.

For ordinary DORY-style vehicle control, the STM32F407 is unlikely to be the main performance bottleneck.

---

# 27. ArduPilot reuse — it already runs ArduSub

## This is not hypothetical

**Observation: CERTAIN** — see section 2a.

The vehicle runs **ArduSub**, established by reading all 588 parameters off it
over MAVLink. The STM32F407 is not merely "a class of MCU used by open
autopilot firmware" — it is running that firmware now.

The open question is therefore narrower than a port: **which board definition
did Chasing build against?** `AUTOPILOT_VERSION` returns board, vendor and
product ids of zero, and `BRD_SERIAL_NUM` is 0, so the build does not say.

### But this board is not a drop-in target

**CERTAIN**

A custom hardware definition would be required.

You would need to map:

- oscillator frequency,
- flash geometry,
- IMU bus and chip selects,
- depth/barometer sensor,
- compass,
- UARTs,
- I2C,
- microSD,
- voltage/current ADCs,
- LEDs,
- motor-command outputs,
- power-enable GPIOs,
- tether interface,
- any camera/auxiliary board connections.

### The ESC complication is smaller than it looks

The five thrusters are driven through separate EFM8 ESC MCUs — but the
interface between them and the STM32 is **plain PWM at 490 Hz**
(`RC_SPEED = 490`), not a proprietary serial protocol. Any ArduPilot build
already speaks that. Section 17's open question about the command protocol is
answered by the parameter, not by tracing.

Replacing the ESC firmware is a separate and independent option (section 16),
not a prerequisite.

---

# 28. Likely block diagram

**Inference: VERY HIGH overall**

```text
                         +----------------------+
                         |    Main battery      |
                         |   ~3S / nominal 12 V |
                         +----------+-----------+
                                    |
                         +----------v-----------+
                         | Power distribution   |
                         | regulators/protection|
                         +----------+-----------+
                                    |
                +-------------------+-------------------+
                |                                       |
        +-------v--------+                       +------v------+
        | STM32F407VGT6  |                       | 12 V motor  |
        | main controller|                       | power bus   |
        +-------+--------+                       +------+------+
                |                                       |
       +--------+---------+                             |
       |        |         |                             |
       |        |         |                             |
    microSD    UARTs     I2C                            |
       |        |         |                             |
       |        |         |                             |
       +--------+---------+-----------------------------+
                |
      +---------+---------+---------+---------+---------+
      |                   |                   |
      v                   v                   v
+-----------+        +-----------+       +-----------+
| EFM8 BB21 |  ...   | EFM8 BB21 | ...   | EFM8 BB21 |
| ESC MCU 1 |        | ESC MCU n |       | ESC MCU 5 |
+-----+-----+        +-----+-----+       +-----+-----+
      |                    |                   |
+-----v-----+        +-----v-----+       +-----v-----+
| FD6288Q   |        | FD6288Q   |       | FD6288Q   |
| 3-phase   |        | 3-phase   |       | 3-phase   |
| gate drv  |        | gate drv  |       | gate drv  |
+-----+-----+        +-----+-----+       +-----+-----+
      |                    |                   |
  6x AO4406A           6x AO4406A          6x AO4406A
      |                    |                   |
   Thruster 1           Thruster n          Thruster 5
```

---

# 29. Recommended reverse-engineering sequence

## Phase 1: preserve the original firmware

**Recommended priority: CRITICAL**

1. Do not perform firmware updates.
2. Do not issue "unlock" commands.
3. Do not mass erase anything.
4. Identify STM32 SWD access.
5. Check STM32 readout-protection state.
6. Dump flash if readable.
7. Check one EFM8 through C2.
8. Dump its flash if possible without erase.
9. Repeat for all five ESC MCUs if their contents differ.

---

## Phase 2: map one ESC channel completely

Because all five channels are repeated, reverse engineering one channel provides most of the design.

Map:

1. EFM8 power pins.
2. C2CK / C2D.
3. EFM8-to-FD6288 input pins.
4. EFM8 BEMF / phase-sense inputs.
5. EFM8 command input from STM32.
6. FD6288 bootstrap networks.
7. FD6288 gate outputs.
8. Six AO4406A MOSFET connections.
9. Motor U/V/W output paths.
10. Any current or voltage feedback.

---

## Phase 3: identify the STM32-to-ESC protocol

Use a logic analyser while commanding one motor.

Determine:

- protocol voltage,
- frame rate,
- pulse timing,
- bidirectional or unidirectional behaviour,
- direction encoding,
- arm/disarm sequence,
- failsafe behaviour.

---

## Phase 4: investigate `BUOY_IN`

Trace:

- cable pins,
- protection components,
- transceiver IC,
- connection to STM32 UART/SPI/CAN/etc.

Capture traffic while the vehicle communicates normally.

This may reveal the complete tether protocol.

---

## Phase 5: inspect the reverse side / connected PCB

Look specifically for:

- IMU,
- pressure/depth sensor,
- compass,
- tether transceiver,
- voltage regulators,
- current shunts,
- camera/video processor,
- flash/EEPROM,
- USB circuitry,
- battery-management circuitry.

---

# 30. What is known vs guessed — concise summary

## Certain

- Main MCU is **STM32F407VGT6**.
- There are **five channels CH1–CH5**.
- Each channel contains an **EFM8BB21F16G**.
- Each channel contains a **Fortior FD6288Q**.
- Power MOSFETs are marked **`AP 4406A` / `GL9C1E`** in SO-8. The `4406A` die is
  standard; the vendor prefix reads as a script `AP` in the photographs, so
  AO4406A (Alpha & Omega) and AP4406A are both plausible and the attribution is
  **not** settled.
- Large diodes are **SS34**.
- `C2CK/C2D` are EFM8 C2 programming/debug pads.
- A hinged-lid metal **card socket** is fitted (that it is microSD specifically
  is HIGH, not certain; whether a card is *in* it is **not observed** —
  section 6).
- STM32 `BOOT0`, `RST`, UART-related pads, 3.3 V and GND test points are exposed.
- The firmware is **ArduSub**, read off the vehicle as 588 parameters
  (section 2a). Flight sw reports 1.1.6, board/vendor/product ids all zero.
- The board has heavy battery wiring and 12 V-related silkscreen.
- The motor sections are **three-phase BLDC ESCs**, not brushed H-bridges.

## Very high confidence

- There are five complete independent ESCs.
- Each ESC uses:
  `EFM8BB21 -> FD6288Q -> six AO4406A MOSFETs`.
- The board is the central motor/control PCB of a five-thruster underwater vehicle.
- The board is very likely from a **CHASING DORY**.
- The main supply is likely 3S lithium / approximately 12 V nominal.
- `BUOY_IN` relates to the tethered surface buoy.
- The STM32 coordinates the five local ESC processors.

## High confidence

- SS34 diodes are primarily bootstrap diodes for the high-side gate drivers.
- The ESC architecture is closely related to BLHeli_S-era hardware design.
- The design dates from roughly the late 2010s.
- The STM32 has enough performance for the vehicle's original control role.
- The board was designed as proprietary/OEM hardware, not as a general hobby flight controller.

## Moderate confidence

- The card socket uses native STM32 SDIO rather than SPI.
- IMU/depth/compass sensors are on the reverse or another connected PCB.
- The unknown `1927` marking is a 2019 week-27 date code.
- Bluejay or another modern EFM8 ESC firmware could potentially be adapted.
- A newer STM32H7 would be useful mainly for advanced autonomy, not basic operation.

## Low-confidence guesses / unresolved

- Exact identity and function of the `HB1621S`-marked 16-pin IC.
- Exact tether electrical protocol.
- Exact two-pin white connector family.
- Exact STM32 crystal frequency.
- Whether the factory ESC firmware is BLHeli_S-derived.
- Whether the gold square/hole is related to a pressure sensor.
- Exact location of the IMU/depth sensor.
- Whether the card socket is populated, and with what.

## Resolved since this document was first written

Answered from the vehicle's own parameters rather than from the photographs
(section 2a):

- **Motor-command protocol between STM32 and EFM8** — plain PWM at 490 Hz
  (`RC_SPEED = 490`).
- **Compass** — I2C bus 1, address 0x0D, HMC5883/QMC5883 class
  (`COMPASS_DEV_ID = 68873`).
- **Current sensing** — configured and present (`BATT_MONITOR = 5`).
- **Power architecture** — 3898 mAh expected, 10.5 V low-voltage failsafe,
  consistent with the 3S reading.
- **Firmware** — ArduSub, an older build using `FRAME` rather than
  `FRAME_CONFIG`.
- **Output allocation** — six PWM outputs, 1-5 thrusters, 6 the light.

---

# 31. Useful component references

These links are references for identified components and platform information.

- STMicroelectronics STM32F407VG:
  https://www.st.com/en/microcontrollers-microprocessors/stm32f407vg.html

- ST STM32 system-memory boot mode application note AN2606:
  https://www.st.com/resource/en/application_note/an2606-stm32microcontroller-system-memory-boot-mode-stmicroelectronics.pdf

- Silicon Labs EFM8BB21:
  https://www.silabs.com/mcu/8-bit-microcontrollers/efm8-busy-bee/device.EFM8BB21F16G-QFN20

- Fortior FD6288:
  https://fortiortech.com/en/product/hvic/hvic/fd6288

- Alpha & Omega AO4406A datasheet:
  https://www.aosmd.com/sites/default/files/res/data_sheets/AO4406A.pdf

- Bluejay ESC firmware:
  https://github.com/mathiasvr/bluejay

- CHASING DORY specifications:
  https://www.chasing.com/en/chasing-dory-specs.html

- Example CHASING DORY replacement main-board listing:
  https://www.blueskiesdroneshop.com/products/chasing-dory-main-board

- ArduPilot STM32 board-porting guide:
  https://ardupilot.org/dev/docs/porting.html

- PX4 board-porting documentation:
  https://docs.px4.io/main/en/hardware/porting_guide

---

# 32. Final assessment

The board is best understood as a **combined underwater-vehicle controller and five-channel BLDC motor controller**, not merely as a flight controller.

The central architecture is:

- **STM32F407VGT6** main controller,
- **five EFM8BB21F16G ESC processors**,
- **five FD6288Q three-phase gate drivers**,
- **thirty AO4406A N-channel MOSFETs**,
- repeated **SS34 bootstrap/rectifier networks**,
- microSD,
- exposed UART/I2C/debug/test pads,
- nominal ~12 V battery distribution,
- and a likely tether/buoy interface.

The strongest product-level identification is **CHASING DORY**, but this should remain labelled **VERY HIGH confidence rather than absolute certainty** until a board part number, product silkscreen, or matching reverse-side layout is confirmed.

The best next technical steps are:

1. preserve the STM32 and EFM8 firmware,
2. identify STM32 SWD,
3. dump firmware if unprotected,
4. map one ESC channel completely,
5. sniff the STM32-to-ESC command protocol,
6. reverse engineer `BUOY_IN`,
7. inspect the reverse side and all connected PCBs for sensors and communications hardware.

