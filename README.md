# PimpingDory

Get photos, video, live picture, telemetry and thruster control out of a
**Chasing Dory** underwater drone without the vendor app.

No account, no login, no phone. The buoy exposes an unauthenticated REST API on
port 80 and pushes video and MAVLink over UDP; `scripts/DoryControl.sh` does
the talking.

Everything here was worked out from the outside and confirmed against a real
drone. Not affiliated with or endorsed by Chasing.

## Quick start

Join the drone's Wi-Fi — `Dory_xxxxx`, password `12345678`.

Anything that **listens** on a UDP port needs the macOS firewall lowered, so
run `sudo -v` first for those. Downloading does not.

```sh
sudo -v
```

### Confirmed working

Every one of these has been run against a real drone.

| command | does | confirmed |
|---|---|---|
| `--list` | show what is on the card | 2026-08-22 |
| `--retrievemedia` | download everything to `./media` | 2026-08-22, 28 files |
| `--retrievemedia <path>` | download somewhere else | 2026-08-22 |
| `--removemedia` | delete from the card, only what it verified on disk | 2026-08-23 |
| `--video` | live picture in VLC | 2026-08-24 |
| `--telemetry` | battery and voltage | 2026-08-24 |
| `--lights on` / `off` / `N` | headlights, 1–100 | 2026-08-25 |
| `--netcode` | just the handshake, and report | 2026-08-24 |
| `--control` | drive the thrusters from the keyboard | 2026-08-25, all axes made motor noise |
| `--daemon` + `--send` | hold the link open, send commands to it | 2026-08-25 |

Copy-pasteable, no trailing comments:

```sh
./scripts/DoryControl.sh --list
```

```sh
./scripts/DoryControl.sh --retrievemedia
```

```sh
./scripts/DoryControl.sh --retrievemedia ~/dive
```

```sh
./scripts/DoryControl.sh --retrievemedia --removemedia
```

```sh
./scripts/DoryControl.sh --video
```

```sh
./scripts/DoryControl.sh --telemetry
```

```sh
./scripts/DoryControl.sh --lights on
```

```sh
./scripts/DoryControl.sh --lights off
```

```sh
./scripts/DoryControl.sh --control --power 30
```

A session where the link stays up between commands — the daemon starts itself
if it is not already running:

```sh
./scripts/DoryControl.sh --send arm
```

```sh
./scripts/DoryControl.sh --send "up 2"
```

```sh
./scripts/DoryControl.sh --send status
```

```sh
./scripts/DoryControl.sh --send quit
```

### Works, but not fully proven

| command | what is unproven |
|---|---|
| `--video ./dive.mp4` | records alongside the live picture; a playable file has not been confirmed |
| `--telemetry` depth | battery works, **depth is always `None`** — see below |
| `--control` directions | the thrusters run; which one each key drives is unknown |

### Diagnostics

Not for use in the water — these live in the test script:

```sh
sudo -v && ./scripts/DoryTest.sh --sweep
```

```sh
sudo -v && ./scripts/DoryTest.sh --identify
```

```sh
sudo -v && ./scripts/DoryTest.sh --probe
```

```sh
sudo -v && ./scripts/DoryTest.sh --diagnose
```

`./scripts/DoryTest.sh --help` lists them. The full suite, with no arguments,
**ends by erasing the card**; `--keep` skips the deletes.

### Everything else

`--help` lists every option. **`--debug` narrates every decision** — each
request and reply, which host answered, which response shape matched, the exact
player command, the raw telemetry before scaling. It goes to stderr, so
`2>/dev/null` still leaves clean output, and it all lands in `<path>/_run.txt`
either way. That matters: there is no internet on the buoy's Wi-Fi, so a bad
trip has to be diagnosable afterwards from the log alone.

### Windows

```
.\scripts\DoryControl.bat --retrievemedia
```

Same options — it runs the same program. Needs Python 3, which Windows does not
ship. See `scripts/WINDOWS-NOTES.md`. **Untested on real Windows.**

## What you need

- **macOS or Linux**, or Windows via the `.bat`
- **Python 3** and `curl`
- **VLC** for `--video`, found automatically. Without it the script falls back
  to a browser view, which needs `ffmpeg`. With neither it says so and names
  both rather than failing obscurely.
- **sudo** for anything that listens on a UDP port — see below

## Things that will bite you

**The macOS firewall silently eats inbound UDP.** Not "blocks with an error" —
the packets simply never reach the process. A capture showed 6843 video packets
and 608 MAVLink packets arriving on the wire while the sockets bound to those
exact ports reported *silent*. So every mode that listens (`--video`,
`--telemetry`, `--control`, `--lights`) lowers the firewall for the session and
restores it on exit, which is why they want `sudo -v` first. `--list` and
`--retrievemedia` never touch it.

**Nothing is pushed at you until you ask.** The buoy relays no video and no
telemetry until a client completes a handshake on UDP 40000. Binding a socket
and waiting gets you nothing at all — this is not a fault, and it cost three
trips to the water to work out. The script does the handshake automatically;
`--no-netcode` skips it if you want to see the old behaviour.

**Filenames are never percent-encoded.** The buoy does not decode them, so
`20260717_133442(1).mp4` sent as `…%281%29.mp4` comes back `500`. Five of 24
files failed this way before it was fixed.

**Expect dropouts.** The buoy's range is about 15 m. Downloads are verified
against the size the API reports and completed files are skipped, so re-running
after a dropout resumes rather than restarts.

**`--removemedia` never deletes a file it cannot prove you have.** With
`--retrievemedia` it downloads first, re-checks each file on disk against the
reported size, and only then issues the `DELETE`. Anything that failed to
download stays on the device. On its own it is deleting your only copy — add
`--confirm` and it demands a typed confirmation.

## Driving it

`--control` sends MAVLink at 40 Hz with a 1 Hz GCS heartbeat, takes the control
role over REST, sets manual mode and arms. Keys are arrows, `w`/`s`, `q`/`e`,
`a` to arm, space for neutral, `x` to quit. `--power N` sets how hard it pushes.

**The vendor app has no failsafe at all** — on disconnect it stops sending and
that is that. This does the opposite: every key decays to neutral after 400 ms
unless repeated, and quitting sends twenty neutral frames followed by a disarm.

**Which axis moves the drone which way is still unknown** (see below). Try it in
a bucket with the tether in hand before you try it over deep water.

For a session where the link stays up between commands:

```sh
sudo -v && ./scripts/DoryControl.sh --daemon
```

```sh
./scripts/DoryControl.sh --send arm
./scripts/DoryControl.sh --send "up 2"
./scripts/DoryControl.sh --send status
./scripts/DoryControl.sh --send quit
```

`--send` starts a daemon itself if none is running.

## Testing

`scripts/DoryTest.sh` exercises everything against the real drone and writes a
timestamped log meant to be read cold. Single steps:

```sh
sudo -v && ./scripts/DoryTest.sh --sweep      # drive every axis in turn
sudo -v && ./scripts/DoryTest.sh --probe      # one arm, one up, every byte
sudo -v && ./scripts/DoryTest.sh --diagnose   # every theory at once, ~90s
```

The full suite **ends by erasing the card**; `--keep` skips the deletes.

## How it fits together

```
DoryControl.sh   ─┐
                  ├─→  scripts/dorycontrol.py    all the logic
DoryControl.bat  ─┘    (Windows goes via DoryControl.ps1)
```

The launchers do one job each: gather the network facts, export them, hand
over. Two hand-maintained implementations drift, and the drift only shows up at
the water where neither can be debugged.

## Hardware

- **Drone** — camera, 5 thrusters, 15 m max depth, ~60 min runtime. Tethered to
  the buoy; no Wi-Fi of its own.
- **Buoy** — floats, relays Wi-Fi, and **holds the 16 GB of media**. It is the
  thing to talk to.
- JPEG 1920x1080 stills, MP4 H.264 1080p30 video.

## Dead ends, recorded so nobody retries them

- **The app** needs account registration and login, and login needs an internet
  connection the buoy's Wi-Fi does not have.
- **SSH.** Port 22 is open on the ROV but the daemon is ancient and modern
  OpenSSH refuses to negotiate. It works with `-o
  KexAlgorithms=+diffie-hellman-group1-sha1 -o HostKeyAlgorithms=+ssh-rsa -o
  Ciphers=+aes128-cbc`, but the root password is unknown. Unnecessary anyway.
- `nmap` finds only 22 and 80 open.
- The manual documents **no** USB or computer transfer. App-only, officially.

---

# Still to do

## The axis mapping — derived, not yet watched

**Solved on paper.** It is ArduSub, and ArduSub's RC channel to axis mapping is
fixed in the firmware, not configurable. The array index below is RC channel
N+1, so index 0 is RC1:

| slot | axis | typed command | key |
|---|---|---|---|
| 4 | **forward / back** | `forward` `back` (`f` `b`) | ↑ ↓ |
| 2 | **vertical** — `up` means towards the surface | `up` `down` (`u` `d`) | `w` `s` |
| 3 | **yaw**, turn left and right | `left` `right` (`l` `r`) | ← → |
| 0 | roll | `rollleft` `rollright` | `q` `e` |
| 1 | pitch | `pitchup` `pitchdown` | `r` `f` |
| 5 | *lateral* in stock ArduSub — **repurposed by Chasing as the lights** | `--lights` | — |

Commands are named for what they do, so `--send "up 2"` ascends. The arrow keys
in `--control` follow the joystick convention instead — pushing the stick away
from you is forwards — which is why ↑ is forward there and `w` is up.

Two independent confirmations: `FRAME = 1` is ArduSub's VECTORED frame, and the
vendor app has a dial whose button logs "Pitch = 0" and sends exactly channel
index 1 — ArduSub's pitch channel. If one channel lands where ArduSub says it
should, the rest follow.

**The old guesses were wrong in a way that mattered.** Slot 0 was labelled
"fwd/back" (it is roll), slot 1 "vertical" (it is pitch), slot 2 "pitch" (it is
vertical) — and **nothing drove slot 4 at all**, the one axis that actually
moves the drone forwards. That is why the earlier sweeps made motor noise
without obviously going anywhere.

**Still to do:** watch it. The mapping is derived from the firmware's own
parameters, not from seeing the drone move.

```sh
sudo -v && ./scripts/DoryTest.sh --sweep
```

Ten axes, 8s each with 3s gaps, arming and disarming itself. In a bucket
with the tether in hand. If forward really is forward, the table above is
correct and this section can go.

One thing to expect: **pitch is inverted** — the app sends `3000 - value` on
that channel.

## It runs ArduSub — confirmed 2026-08-25

`./scripts/DoryTest.sh --identify` pulled all **588 parameters** off the
vehicle. The underwater-only ones settle it — they exist in no other ArduPilot
build:

```
FS_LEAK_ENABLE    FS_PRESS_ENABLE   FS_TEMP_ENABLE
SURFACE_DEPTH     GND_SPEC_GRAV     MOT_1..8_DIRECTION
```

alongside eight core ArduPilot families (`AHRS_ ATC_ BRD_ COMPASS_ EK2_ INS_
RC1_ SR0_`).

It reports **flight sw 1.1.6**, which is Chasing's own numbering — ArduPilot's
own would be 3.x or 4.x — with board, vendor and product ids all zero. It uses
**`FRAME`, not `FRAME_CONFIG`**, so it is an *older* ArduSub: that parameter was
renamed in later releases.

Values worth knowing, all from the dump:

| parameter | value | meaning |
|---|---|---|
| `ARMING_CHECK` | 0 | **pre-arm checks are disabled** — which is why arming works with no GPS and no calibration |
| `FS_GCS_ENABLE` | 2 | GCS-loss failsafe is **active**, hence `MYGCS: 255, heartbeat lost` when the heartbeat stops |
| `FS_LEAK_ENABLE` | 0 | leak failsafe off |
| `SURFACE_DEPTH` | -10 | 10 cm counts as the surface |
| `BATT_MONITOR` | 5 | analogue voltage and current |
| `FRAME` | 1 | thruster layout |
| `MOT_1..8_DIRECTION` | ±1 | **eight** thruster channels, though the drone has five |

`media/params.txt` holds the lot. **Keep it** — it is the only record of how
this vehicle is configured, and there is no way to recover it.

## Can it be reflashed?

**Unknown, and untried. Do not attempt without a recovery path.**

Worth establishing, in this order, and none of it needs the vehicle armed:

1. **What it says it is.** `AUTOPILOT_VERSION` (msg 148) via
   `COMMAND_LONG`/`MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES` (520) would give
   flight-sw version, board type and capability flags. The app already reads a
   version field it never displays, so the vehicle answers something.
2. **Which parameters exist.** `PARAM_REQUEST_LIST` (21) dumps every parameter
   with its name. Stock ArduSub names (`FRAME_CONFIG`, `SERVO*_FUNCTION`,
   `BRD_*`) would settle the question in one packet dump, and the parameter set
   is also what a reflash would have to preserve.
3. **Where the firmware lives.** The buoy is a Linux box with SSH on the ROV at
   `192.168.1.88` (see Dead ends). The flight controller is a separate MCU
   behind it, so any reflash is likely *through* the buoy, not directly.
4. **Whether there is a stock target at all.** ArduSub builds are per-board. If
   the board is a Chasing design rather than a Pixhawk variant, there may be no
   upstream build that runs on it, and the thruster mapping and the light
   channel would be lost even if one did.

**The realistic risk:** an underwater drone with no recovery path is a brick,
and the vendor app is the only official way back. Read parameters first, keep a
full dump, and treat writing anything as a separate decision.

## Depth never arrives

`--telemetry` shows battery (`94%, 12.22V`) but depth stays `None`. **`VFR_HUD`
(msg 74) is never sent at all**, and that is the message depth is supposed to
come from. The message ids actually arriving are `{24: 143, 0: 18, 253: 4,
147: 4}` — msg 24 is `GPS_RAW_INT` and is 80% of the traffic, which is odd for
something underwater and is the obvious place to look.

Easiest test: run `--telemetry` with the drone actually submerged and see
whether msg 74 appears. If it does not, depth is coming from somewhere else and
msg 24 is the candidate.

## Windows — never run on Windows at all

`DoryControl.bat` → `DoryControl.ps1` → `dorycontrol.py`. The `.py` is the code
that works on macOS, so the risk is concentrated in the 280-line `.ps1`: the
network facts and the argument parsing.

`scripts/WINDOWS-NOTES.md` has the commands in dependency order and lists what
is most likely wrong — `Get-NetIPAddress` ordering on a machine with Ethernet
or a VPN up, the localised `netsh wlan` output, and `curl -C -` resume.

## Updates/Upgrades TODO

Hardware. None of this is started.

1. **1/4 inch female sockets on the hull** for mounting a light rig — the
   standard 1/4"-20 tripod thread, so anything off the shelf fits.

2. **Light rig** — aluminium frame, 1/4 inch bolts and nuts, two **Workkus
   DL07** lights, with closed-cell PVC for buoyancy to offset the added mass.

3. **Battery** — replace the cells in the **19386-EE-1P3S21700** pack.
   Candidates:
   - **Vapcell 21700 Li-Ion**
   - **Keeppower 21700 6000 mAh**

   The pack is 1P3S: three cells in series, one parallel string.

4. **Motors** — replace with more powerful ones. Five thrusters as standard.

5. **Camera** — replace with a higher-resolution one. Standard is 1080p30
   H.264 video and 1920x1080 stills.

6. **Storage** — open the buoy and see whether the 16 GB is an SD card on the
   board or soldered eMMC. If it is a card, `dd` it onto a bigger one and see
   whether the firmware accepts the result.

   Useful to know before opening anything: the manual (p.9) lists
   `STORAGE 16G` under BUOY, not DRONE, so the buoy is the thing to open. The
   REST API has `GET /v1/tfcard/sdquery` and `POST /v1/tfcard/format` — "tfcard"
   is TransFlash, the old name for microSD, which is a hint that it is a card
   rather than eMMC. `--list` already reports what the API says about capacity.
