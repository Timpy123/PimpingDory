# DoryControl on Windows

```
.\scripts\DoryControl.bat --retrievemedia
.\scripts\DoryControl.bat --retrievemedia .\media --removemedia
.\scripts\DoryControl.bat --video
.\scripts\DoryControl.bat --telemetry
.\scripts\DoryControl.bat --netcode
.\scripts\DoryControl.bat --list --debug
```

`--usage` lists everything. The option set is identical to macOS because it
comes from the same file.

## How it fits together

```
DoryControl.bat   finds PowerShell, bypasses the execution policy
  └─ DoryControl.ps1   gathers the network facts, exports DORY_* vars
       └─ dorycontrol.py   ALL the logic — shared with macOS
```

`DoryControl.sh` on macOS is the same shape: launcher, then the same
`dorycontrol.py`.

**This replaced a 1376-line hand-written PowerShell port.** Within a week that
port was three days behind: no netcode handshake (so `--video` could never
work), no `--control`, no `--daemon`, no `--timeout`, and it still accepted
`--force`/`--yes`/`--no-scan` long after those were deleted. Two
implementations drift, and the drift only shows up at the water where neither
can be debugged. Fix `dorycontrol.py` and both platforms get it.

## Requirements

- **Python 3.** Windows does not ship it: `winget install Python.Python.3.12`,
  and tick *Add python.exe to PATH*. The launcher tries `python3`, `python`
  and `py`, and rejects the Windows Store stub (it exits 9009 and opens the
  Store rather than running anything).
- **VLC**, for `--video`. Found automatically at
  `%ProgramFiles%\VideoLAN\VLC\vlc.exe` and the `(x86)` variant.
- **ffmpeg**, only for the browser fallback when VLC is absent.

## Deliberate differences from macOS

| | macOS | Windows |
|---|---|---|
| network facts | `ifconfig`, `ipconfig getifaddr`, `netstat -rn`, `arp -an` | `Get-NetIPAddress`, `Get-NetRoute`, `Get-NetNeighbor`, with `ipconfig`/`arp -a` fallbacks |
| SSID | usually `<redacted>` — needs Location permission | `netsh wlan show interfaces` gives the real SSID, so `--checkwifi` is **better** here |
| firewall | globally disabled for the session, restored on exit | **not touched** — see below |
| VLC flags | `--macosx-control-itunes=0` | `--no-one-instance` |
| `--diagnose` capture | `tcpdump` | none; run Wireshark alongside |
| `--daemon` / `--send` | Unix socket | needs Windows 10 1803+ and Python 3.9+ for `AF_UNIX`; says so plainly otherwise |

### The firewall, and why Windows is left alone

On macOS the application firewall silently drops inbound UDP. That cost a full
day on 2026-08-24: a capture showed 6843 video packets and 608 MAVLink packets
arriving on the wire while the sockets bound to those exact ports reported
*silent*. No error, nothing. So the macOS launcher disables it for the session
and restores it after.

Windows Defender Firewall fails differently — it **prompts** the first time
Python binds a listening port, and it blocks per-application rather than
globally. Turning a whole profile off would be a far bigger hammer than the Mac
needs, so the Windows launcher does not touch it. It warns instead.

**When the prompt appears, allow Python and tick *Private networks*.** If it is
dismissed, `--video` and `--telemetry` will look exactly like a drone that is
not sending. To fix it afterwards:

```
Windows Security → Firewall & network protection → Allow an app through firewall
```

## Testing — none of this has ever run on Windows

Not one line of the launcher has executed on a Windows machine. The
`dorycontrol.py` half is the code that works on macOS, so the risk is
concentrated in `DoryControl.ps1`: the network facts and the argument parsing.

Work through it in this order, since each depends on the last:

| command | expected |
|---|---|
| `DoryControl.bat --usage` | the option list, exit 0 |
| `DoryControl.bat` | same list on stderr, exit 2 |
| `DoryControl.bat --bogus` | `unknown option`, exit 2 |
| `DoryControl.bat --list --debug` | `iface`/`ssid`/`gateway`/`arp` lines that are not empty, then the file list |
| `DoryControl.bat --netcode --debug` | `state: connected`, and the buoy answering `{"id":1,"ackTo":0}` |
| `DoryControl.bat --video` | a VLC window with live picture |
| `DoryControl.bat --video .\dive.mp4` | window **and** a playable file |
| `DoryControl.bat --telemetry` | depth and battery updating |
| `DoryControl.bat --retrievemedia .\scratch --debug` | everything downloads, including the `(1)` filenames |
| `DoryControl.bat --retrievemedia .\scratch` again | every file skipped as already present |
| `DoryControl.bat --probe --debug` | STEP 0 through STEP 5, one arm and one up |
| `DoryControl.bat --api` | every endpoint the app knows about, answered or not. Needs no firewall change — it listens on nothing |
| `DoryControl.bat --lights on` then `--lights off` | the headlights change and the command exits. Nothing arms |
| `DoryControl.bat --identify` | firmware string, then all 588 parameters |

Things most likely to be wrong, all in the `.ps1`:

- `Get-NetNeighbor` needs the ping sweep to have populated the table first.
  If `arp` comes back empty, host discovery falls back to the fixed candidate
  list, which still finds `192.168.1.1`.
- `Get-NetIPAddress` ordering — the first non-loopback address is assumed to
  be the Wi-Fi one. On a machine with Ethernet or a VPN up, it may not be.
- `netsh wlan show interfaces` output is localised; the SSID regex may not
  match on a non-English Windows.
- `curl` ships with Windows 10+, but `-C -` resume behaviour on an interrupted
  download is unverified.

Test into `.\scratch`, never `.\media` — that is where real dive footage goes.

## Carried over unchanged, do not re-derive

Host discovery order and the `192.168.1.1` finding; never percent-encode a
filename; the response-shape unwrapping; size verification and resume;
delete-only-what-is-verified; RTP/H.264 on UDP 5600 behind the netcode
handshake on UDP 40000; MAVLink on 14550 with the control role, the 1 Hz GCS
heartbeat and channel 5 as a gain. All of it is in `CLAUDE.md`, and all of it
is in `dorycontrol.py` already — it is shared code, not a port.
