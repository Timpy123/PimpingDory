#!/usr/bin/env python3
"""The whole of DoryControl. Platform launchers gather the network facts,
export them as DORY_* environment variables, and run this.

It lives in one file on purpose. Two hand-maintained implementations drift,
and the drift only shows up at the water where neither can be debugged --
the Windows port was three days behind within a week of being written.
Everything platform-specific is isolated in the launchers, or behind the
IS_MAC / IS_WIN checks below.

  scripts/DoryControl.sh   macOS and Linux launcher
  scripts/DoryControl.bat  Windows launcher (via DoryControl.ps1)
"""
import json, os, shutil, socket, ssl, struct, subprocess, sys, threading, time
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

USAGE = r"""DoryControl -- Chasing Dory over its private REST API

  --retrievemedia [path]   download everything on the device into [path]
                           (default: ./media)
  --removemedia            delete media off the device (frees the 16 GB).
                           With --retrievemedia it downloads first and only
                           deletes files it has verified on disk, including
                           ones that were already there. On its own it deletes
                           without keeping a copy, and asks first.
  --video [file]           live camera. With a path, also record to it
                           (.ts survives an abrupt stop; .mp4 needs a clean
                           quit). Plays in VLC, or the browser without it.
  --telemetry              live depth and battery readout. On its own it just
                           prints; with --video it runs alongside the picture.
  --control                DRIVE THE THRUSTERS. Keyboard, 40 Hz MAVLink.
                           The axis mapping is ArduSub's, read off the vehicle
                           itself, but it has not yet been watched in water:
                           try it in a bucket with the tether in hand first.
                           Keys decay to neutral after 400ms; quitting sends
                           neutral and a disarm. --power N (default 40) sets
                           how hard it pushes.
  --control <keys>         drive axes without a keyboard, --timeout seconds
                           each, then stop. A comma-separated list runs in ONE
                           session: one GCS heartbeat, one arm, each input in
                           turn. That matters -- a separate process per axis
                           leaves a gap the drone reports as
                           "MYGCS: 255, heartbeat lost", and a vehicle in GCS
                           failsafe will not arm.
                             a                     arm only, nothing moves
                             forward back  (f b)   slot 4
                             up down       (u d)   slot 2, vertical
                             left right    (l r)   slot 3, yaw
                             rollleft rollright    slot 0
                             pitchup pitchdown     slot 1
                           e.g. --control up --timeout 5
                                --control a,up,down,left,right --timeout 4
  --lights [on|off|N]      the headlights. On its own it sets them and exits:
                             ./scripts/DoryControl.sh --lights on
                             ./scripts/DoryControl.sh --lights off
                           Nothing is armed and every stick stays neutral, so
                           the drone cannot move. Alongside another mode it
                           just sets the level for that run. N is 1-100;
                           1 is off and 41 is what the app calls on
                           the vendor app. Channel 5 carries it.
  --timeout N              stop after N seconds instead of running until
                           ctrl-C. Applies to --control, --telemetry,
                           --netcode and the --video listen.
  --list                   show what is on the device and exit
  --netcode                run only the buoy handshake and report. This is
                           what asks the drone to start pushing video and
                           telemetry; --video, --telemetry and --control all
                           do it themselves first.
  --daemon                 hold the link open and take commands. One
                           process owns the control role, the GCS heartbeat and
                           the 40 Hz RC stream for its whole life, which is what
                           the drone actually needs -- a CLI that connects and
                           exits per command tears all three down and nothing
                           moves. Commands arrive on a Unix socket.
  --send "<cmd>"           send one command to a running daemon and print the
                           reply. arm | disarm | up|down|left|right|w|s|q|e
                           [seconds] | sweep [seconds] | neutral | power N |
                           lights on|off|N | mode N | status | quit.   e.g.  --send "up 2"
                           `sweep` runs every axis in turn -- 8s each with a
                           3s gap by default -- which is the axis-mapping
                           session in one command.
  --sock <path>            where that socket lives (default: <media>/dory.sock)
  --no-netcode             skip that handshake (what every run before
                           2026-08-23 did, and nothing ever arrived)

  --host <ip[:port]>       try this host first (default: 192.168.1.1, the
                           address the buoy actually answers on). The rest of
                           the known addresses are still tried if it does not
                           answer, which is what recovered the day .88 broke.
  --scan                   if nothing known answers, sweep the whole /24.
                           Off by default; it is slow.
  --checkwifi              refuse to run unless this looks like the Dory Wi-Fi.
                           Off by default, so it just gets on with it.
  --confirm                ask before deleting. Off by default. Worth adding
                           for a bare --removemedia, which deletes your only
                           copy.
  --debug                  print every decision as it is made: the resolved
                           options, each HTTP request and reply, which
                           response shape matched, every curl and player
                           command, and the raw telemetry values before
                           scaling. Everything it prints also goes to
                           <path>/_run.txt.
  -h, --help, --usage      this

Diagnostics — these are NOT for use in the water. They live in the test
script: ./scripts/DoryTest.sh --sweep | --probe | --diagnose | --findlink

Examples
  ./scripts/DoryControl.sh --retrievemedia
  ./scripts/DoryControl.sh --retrievemedia ./media --removemedia
  ./scripts/DoryControl.sh --video
  ./scripts/DoryControl.sh --video ./dive.mp4 --telemetry
  ./scripts/DoryControl.sh --telemetry
  ./scripts/DoryControl.sh --control --power 30"""

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

if os.environ.get("DORY_USAGE_ONLY"):
    # Both launchers call this rather than carrying their own copy.
    sys.stdout.write(USAGE.replace(
        "./scripts/DoryControl.sh",
        ".\\scripts\\DoryControl.bat" if IS_WIN else "./scripts/DoryControl.sh"))
    sys.exit(0)

LOGPATH  = os.environ["DORY_LOG"]
LOG      = open(LOGPATH, "a")
RETRIEVE = os.environ.get("DORY_RETRIEVE") or ""
REMOVE   = os.environ.get("DORY_REMOVE") == "1"
LIVE     = os.environ.get("DORY_LIVE") == "1"
LIVEFILE = os.environ.get("DORY_LIVEFILE") or ""
LIST     = os.environ.get("DORY_LIST") == "1"
TELEM    = os.environ.get("DORY_TELEM") == "1"
CONTROL  = os.environ.get("DORY_CONTROL") == "1"
SELFTEST = os.environ.get("DORY_SELFTEST") == "1"
NETCODE  = os.environ.get("DORY_NETCODE") != "0"
NETCODE_ONLY = os.environ.get("DORY_NETCODE_ONLY") == "1"
FINDLINK = os.environ.get("DORY_FINDLINK") == "1"
PROBE = os.environ.get("DORY_PROBE") == "1"
IDENTIFY = os.environ.get("DORY_IDENTIFY") == "1"
DIAGNOSE = os.environ.get("DORY_DIAGNOSE") == "1"
DAEMON  = os.environ.get("DORY_DAEMON") == "1"
SENDCMD = os.environ.get("DORY_SENDCMD") or ""
CONTROL_KEY = (os.environ.get("DORY_CONTROL_KEY") or "").strip().lower()
def _lights(v):
    """1 is off, 41 is what the app calls on."""
    v = (v or "").strip().lower()
    if v in ("", "off", "0", "no"):
        return 1
    if v in ("on", "yes", "full"):
        return 41
    try:
        return max(1, min(100, int(v)))
    except ValueError:
        return 1

LIGHTS = _lights(os.environ.get("DORY_LIGHTS"))
LIGHTS_ONLY = os.environ.get("DORY_LIGHTS_ONLY") == "1"
try:
    GAP = float(os.environ.get("DORY_GAP") or 3.0)
except ValueError:
    GAP = 3.0
try:
    TIMEOUT = float(os.environ.get("DORY_TIMEOUT") or 0) or None
except ValueError:
    TIMEOUT = None
POWER    = int(os.environ.get("DORY_POWER") or 40)
DEBUG    = bool(os.environ.get("DORY_DEBUG"))
YES      = bool(os.environ.get("DORY_YES"))

def log(msg=""):
    LOG.write(msg + "\n"); LOG.flush()

def say(msg=""):
    print(msg, flush=True); log(msg)

def dbg(msg=""):
    """Only under --debug. Goes to stderr so it never pollutes stdout that
    something else might be reading, and to the log so a debug run stays
    readable after the fact."""
    if DEBUG:
        print(f"  \u00b7 {msg}", file=sys.stderr, flush=True)
        log(f"  · {msg}")

# ------------------------------------------------------------ listening ports
# Ports are bound before the handshake, not after: the buoy can start relaying
# the moment it accepts us, and a datagram sent to a port nothing is listening
# on is gone. One socket per port for the life of the process, shared by
# whichever of sniff/telemetry/control wants to read it.
PREBOUND = {}

def bind_udp(port, rcvbuf=0, broadcast=False):
    s = PREBOUND.get(port)
    if s is not None:
        return s
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Deliberately NOT SO_REUSEPORT: with it a second copy of this script binds
    # happily and then silently receives nothing, because the kernel gives each
    # datagram to only one socket. Failing loudly beats a readout stuck at zero.
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if rcvbuf:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
    if broadcast:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind(("0.0.0.0", port))
    PREBOUND[port] = s
    dbg(f"bound 0.0.0.0:{port}")
    return s

def release_udp(port):
    s = PREBOUND.pop(port, None)
    if s is not None:
        s.close()
        dbg(f"released 0.0.0.0:{port}")

def port_holder(port):
    """Name whatever already has the port. Guessing at this wasted a trip."""
    try:
        return subprocess.run(["lsof", "-nP", f"-iUDP:{port}"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""

# ======================================================== the buoy handshake
# Nothing is pushed at us until a client has completed a handshake with the
# buoy on UDP 40000. That is why three trips to the water saw 0 packets on
# both 5600 (video) and 14550 (MAVLink) while HTTP listed files fine: the
# script was listening to a relay nobody had asked to start.
#
# The app does it through a native netcode library. That library is
# netcode.io with the crypto taken out -- its only imports are sockets, malloc
# and CRC32, no libsodium anywhere -- so it can be replayed from Python. Every
# constant below was read out of the arm64 binary rather than guessed:
#
#   version    "CI 1.0.0". The client copies 31 bytes and so overruns into the
#              next string, but the server checks version[8] == 0 and then
#              strcmp()s, so only the bytes up to the NUL matter.
#   protocol   542134337, the app's own protocol id, sent in request and
#              response.
#   framing    prefix byte = type | (sequence_bytes << 4), then that many
#              bytes of sequence little-endian, then the body, then CRC32 over
#              everything before it. Request (type 0) is the exception: no
#              sequence, 31 version bytes instead.
#   crc32      the standard reflected table, seeded with 0 and with NO final
#              inversion -- so it is NOT zlib.crc32.
#   sizes      5/25/29/13 plus sequence bytes for denied/challenge/response/
#              keep-alive. They are what confirmed each body layout below.
#   exchange   request -> challenge(u64 A, u64 B, u32 C) -> response(protocol,
#              A, B, C echoed in that order) -> keep-alive means connected.
#              Then a payload packet carries the JSON
#              {"id":0,"address":"192.168.1.88:1000"} naming the ROV to relay.
#
# The handshake is on for anything that listens. --no-netcode turns it off,
# which is exactly what every earlier run did, and nothing ever arrived.
NETCODE_PORT    = 40000
NETCODE_VERSION = b"CI 1.0.0" + b"\x00" * 23
NETCODE_PROTO   = 542134337
ROV_STREAM_ADDR = "192.168.1.88:1000"

_CRCTBL = []

def nc_crc(data, crc=0):
    if not _CRCTBL:
        for i in range(256):
            c = i
            for _ in range(8):
                c = (c >> 1) ^ (0xEDB88320 if c & 1 else 0)
            _CRCTBL.append(c)
    for b in data:
        crc = _CRCTBL[(crc ^ b) & 0xFF] ^ (crc >> 8)
    return crc & 0xFFFFFFFF

def nc_seqlen(seq):
    n = 1
    while seq >> (8 * n):
        n += 1
    return min(n, 8)

def nc_request():
    b = b"\x00" + NETCODE_VERSION + struct.pack("<I", NETCODE_PROTO)
    return b + struct.pack("<I", nc_crc(b))

def nc_packet(ptype, body, seq):
    n = nc_seqlen(seq)
    b = bytes([ptype | (n << 4)]) + seq.to_bytes(8, "little")[:n] + body
    return b + struct.pack("<I", nc_crc(b))

def nc_parse(data):
    """None for anything that is not a well-formed packet with a good CRC, so
    an unrelated service on 40000 cannot be mistaken for the buoy."""
    if len(data) < 6:
        return None
    ptype = data[0] & 0x0F
    n = data[0] >> 4
    if not 1 <= ptype <= 6 or not 1 <= n <= 8 or len(data) < 1 + n + 4:
        return None
    if nc_crc(data[:-4]) != struct.unpack("<I", data[-4:])[0]:
        return None
    return ptype, int.from_bytes(data[1:1 + n], "little"), data[1 + n:-4]

class Netcode:
    """Runs the handshake and then keeps it alive. Non-blocking: call update()
    often, or let start() run it on its own thread."""
    NAMES = {-2: "no reply", -1: "denied by the buoy", 0: "disconnected",
             1: "sending connection request", 2: "sending challenge response",
             3: "connected"}
    TYPES = {1: "denied", 2: "challenge", 3: "response", 4: "keep-alive",
             5: "payload", 6: "disconnect"}

    def __init__(self, host, port=NETCODE_PORT):
        self.host, self.port = host, port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.setblocking(False)
        self.myport = self.sock.getsockname()[1]
        self.state, self.seq, self.last_send = 1, 0, 0.0
        self.chal = None
        self.announced = False
        self.last_announce = 0.0
        self.rx = self.tx = 0
        self.replies = []
        self.accepted = False
        self._stop = threading.Event()
        self._thread = None
        dbg(f"netcode: {host}:{port} from local port {self.myport}, "
            f"protocol {NETCODE_PROTO}")

    def _next(self):
        self.seq += 1
        return self.seq - 1

    def _send(self, data):
        try:
            self.sock.sendto(data, (self.host, self.port))
            self.tx += 1
        except OSError as e:
            dbg(f"netcode: send failed: {e}")

    def _set_state(self, new):
        if new != self.state:
            dbg(f"netcode: {self.NAMES.get(self.state, self.state)} -> "
                f"{self.NAMES.get(new, new)}")
            log(f"   netcode state {self.state} -> {new}")
            self.state = new

    def announce(self):
        """Tell the buoy which ROV to relay. This is the packet that is meant
        to open the taps; everything before it is just getting a session."""
        body = json.dumps({"id": 0, "address": ROV_STREAM_ADDR},
                          separators=(",", ":")).encode()
        self._send(nc_packet(5, body, self._next()))
        self.last_announce = time.time()
        if not self.announced:
            dbg(f"netcode: announced {body.decode()}")
        self.announced = True

    def update(self):
        while True:
            try:
                data, src = self.sock.recvfrom(2048)
            except (BlockingIOError, OSError):
                break
            self.rx += 1
            p = nc_parse(data)
            if not p:
                dbg(f"netcode: {len(data)}B from {src[0]}:{src[1]} is not a "
                    f"netcode packet, ignored")
                continue
            ptype, _, body = p
            # Keep-alives arrive ten times a second. Announcing every one
            # buries the output that matters, so say the first two and then
            # keep quiet; the count goes in the summary either way.
            if ptype == 4:
                self.ka = getattr(self, "ka", 0) + 1
                if self.ka <= 2:
                    dbg(f"netcode: <- keep-alive ({len(body)}B body)")
                elif self.ka == 3:
                    dbg("netcode: <- keep-alive (further ones not logged)")
            else:
                dbg(f"netcode: <- {self.TYPES.get(ptype, ptype)} ({len(body)}B body)")
            if ptype == 1:
                self._set_state(-1)
            elif ptype == 2 and self.state == 1 and len(body) == 20:
                self.chal = struct.unpack("<QQI", body)
                self._set_state(2)
            elif ptype == 4 and self.state == 2:
                self._set_state(3)
            elif ptype == 5:
                self.replies.append(body)
                try:
                    msg = json.loads(body.decode("utf-8", "replace"))
                except Exception:
                    msg = None
                dbg(f"netcode: buoy says {body[:120]!r}")
                log(f"   netcode payload {body[:200]!r}")
                # Message ids: 0 tryConnect, 1 accepted, 2 error.
                if isinstance(msg, dict) and msg.get("ackTo") == 0 \
                        and msg.get("id") == 1:
                    self.accepted = True
            elif ptype == 6:
                self._set_state(0)
        now = time.time()
        if now - self.last_send >= 0.1:
            self.last_send = now
            if self.state == 1:
                self._send(nc_request())
            elif self.state == 2:
                a, b, c = self.chal
                self._send(nc_packet(3, struct.pack("<IQQI", NETCODE_PROTO,
                                                    a, b, c), self._next()))
            elif self.state == 3:
                self._send(nc_packet(4, struct.pack("<II", 0, 0), self._next()))
                # The app repeats tryConnect every 0.5s until the buoy answers
                # {"id":1,"ackTo":0}, so one shot is not
                # enough -- a dropped announce would leave a live session that
                # relays nothing, which looks exactly like the old bug.
                if not self.accepted and now - self.last_announce >= 0.5:
                    self.announce()

    def connect(self, timeout=6.0):
        """Block until connected (and announced) or the timeout runs out."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.update()
            if self.state == 3 and self.announced:
                return True
            if self.state == -1:
                return False
            time.sleep(0.02)
        if self.state == 1 and self.rx == 0:
            self._set_state(-2)
        return False

    def start(self):
        """Keep the session alive in the background. The buoy drops a client
        that stops sending, and a dropped session means the stream stops."""
        def run():
            while not self._stop.is_set():
                self.update()
                time.sleep(0.02)
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)
        try:
            self._send(nc_packet(6, b"", self._next()))
        except Exception:
            pass
        self.sock.close()

def netcode_hosts():
    """The app hardcodes 192.168.1.1:40000, so that is first.
    The ROV is tried after it only if .1 said nothing at all -- which address
    answers is the one thing about this device that has already moved once."""
    first = (os.environ.get("DORY_HOST") or "192.168.1.1").split(":")[0] or "192.168.1.1"
    out = [first]
    for h in ("192.168.1.1", "192.168.1.88"):
        if h not in out:
            out.append(h)
    return out

def nc_attempt(host, timeout=None):
    nc = Netcode(host)
    ok = nc.connect(timeout if timeout is not None else (TIMEOUT or 4.0))
    return nc, ok

def open_session(quiet=False):
    """Returns a live Netcode, or None if no host completed the handshake.
    Callers listen either way: being wrong about this should cost a warning,
    not the picture."""
    if not NETCODE:
        dbg("netcode: disabled with --no-netcode; listening to a relay that "
            "was never asked to start")
        return None
    tried = []
    for host in netcode_hosts():
        if not quiet:
            say(f"asking {host} to start the stream ...")
        nc, ok = nc_attempt(host)
        if ok:
            if not quiet:
                say(f"buoy session up on {host} (local port {nc.myport})")
            nc.start()
            return nc
        tried.append((host, Netcode.NAMES.get(nc.state, nc.state), nc.rx))
        log(f"   netcode {host}: state={nc.state} rx={nc.rx} tx={nc.tx}")
        nc.stop()
        # A reply of any kind means this is the right host and the wrong
        # conversation; no point trying the next address.
        if tried[-1][2]:
            break
    say(f"No buoy session: the handshake on UDP {NETCODE_PORT} did not complete.")
    for host, why, rx in tried:
        say(f"  {host:<15} {why}" + ("" if rx else "  (nothing came back at all)"))
    if all(rx == 0 for _, _, rx in tried):
        say("Nothing answered on that port, so either this firmware does not")
        say("have the relay or the buoy is not one of these hosts.")
    say("Listening anyway, in case it streams without being asked.")
    return None

def netcode_only():
    ok_any = False
    for host in netcode_hosts():
        say(f"handshake with {host}:{NETCODE_PORT} ...")
        nc, ok = nc_attempt(host)
        say(f"  sent {nc.tx}, received {nc.rx}")
        say(f"  state: {Netcode.NAMES.get(nc.state, nc.state)}")
        for r in nc.replies:
            say(f"  buoy: {r[:200].decode('utf-8', 'replace')}")
        got = nc.rx
        nc.stop()
        if ok:
            ok_any = True
            say("Handshake complete and the ROV announced. Video and telemetry")
            say("should be arriving now; --video --telemetry shows both.")
            break
        if got:
            break
    return 0 if ok_any else 1

# ============================================================== live video ===
# The drone pushes RTP/H.264 to UDP 5600 and the app just binds and listens:
# CameraControlActivity.java:841 builds H264Code(ctx, i6.d.f37283i) with
# the port is 5600, and the app opens a
# DatagramSocket on it with broadcast enabled. Its depacketiser
# is a textbook RTP depacketiser -- 12-byte header, extension via bit 0x10,
# NAL type 28 = FU-A, emitting 00 00 00 01 start codes. So ffmpeg can read it
# directly from an SDP; nothing custom is needed.
VIDEO_PORT = 5600

def sniff(seconds=None):
    seconds = seconds if seconds is not None else (TIMEOUT or 8)
    """Listen on the video port before handing it to ffmpeg. This is what
    says whether the drone is streaming at all, and at what payload type."""
    try:
        s = bind_udp(VIDEO_PORT, rcvbuf=1048576, broadcast=True)
    except OSError as e:
        say(f"Cannot listen on UDP {VIDEO_PORT}: {e}")
        who = port_holder(VIDEO_PORT)
        if who:
            say("Something else already has that port:")
            for line in who.splitlines():
                say("   " + line)
            say(f"Free it with:  lsof -tnP -iUDP:{VIDEO_PORT} | xargs kill -9")
        return None
    s.settimeout(1.0)
    say(f"listening for video on UDP {VIDEO_PORT} ...")
    deadline, packets, senders, ptypes = time.time() + seconds, 0, set(), {}
    while time.time() < deadline:
        try:
            data, addr = s.recvfrom(2048)
        except socket.timeout:
            continue
        packets += 1
        senders.add(addr[0])
        if len(data) > 1:
            pt = data[1] & 0x7F
            ptypes[pt] = ptypes.get(pt, 0) + 1
        if packets >= 60:
            break
    # Not closed here: the player takes the port next, and the gap between a
    # close and its bind is exactly where a stream gets lost.
    log(f"   video: {packets} packets, senders={sorted(senders)}, types={ptypes}")
    dbg(f"video: {packets} packets, senders={sorted(senders)}, payload types={ptypes}")
    if not packets:
        say(f"No video arriving on UDP {VIDEO_PORT}.")
        say("The drone has to be powered and awake, and you have to be on its")
        say("Wi-Fi. Nothing was received in 8s.")
        return None
    # Video is payload type 96; the app routes anything that is not 97 to the
    # H.264 path and 97 to audio.
    video_pt = next((pt for pt in sorted(ptypes, key=lambda k: -ptypes[k])
                     if pt != 97), 96)
    say(f"{packets} packets from {', '.join(sorted(senders))}, payload type {video_pt}")
    return video_pt

# ============================================================== telemetry ===
# Depth and battery are MAVLink, not REST -- the REST endpoints that look like
# they would carry this (/v1/charge, /v1/control, /v1/lift) are a power-bank
# toggle, phone-to-phone arbitration, and a bait-boat call respectively.
# The link binds 0.0.0.0:14550 and learns its peer from the first packet in
# so listening sends nothing at all -- this cannot disturb
# the drone.
#   depth   VFR_HUD msg 74, field alt, 3rd float, payload offset 8
#   battery BATTERY_STATUS msg 147, battery_remaining, last byte (35)
# SYS_STATUS is a red herring: its handler reads one field and drops it
# and discards it.
MAVLINK_PORT = 14550
FWBIN = "/usr/libexec/ApplicationFirewall/socketfilterfw"

def mav_frames(buf):
    """Yield (msgid, payload) for MAVLink v1 (0xFE) and v2 (0xFD), and return
    whatever tail could not be parsed yet."""
    i = 0
    while i < len(buf):
        b = buf[i]
        if b == 0xFE and len(buf) >= i + 8:
            ln = buf[i + 1]
            end = i + 6 + ln + 2
            if len(buf) < end:
                break
            yield buf[i + 5], buf[i + 6:i + 6 + ln]
            i = end
        elif b == 0xFD and len(buf) >= i + 12:
            ln = buf[i + 1]
            incompat = buf[i + 2]
            end = i + 10 + ln + 2 + (13 if incompat & 0x01 else 0)
            if len(buf) < end:
                break
            msgid = buf[i + 7] | (buf[i + 8] << 8) | (buf[i + 9] << 16)
            yield msgid, buf[i + 10:i + 10 + ln]
            i = end
        else:
            i += 1
    return buf[i:]

# ================================================================ control ===
# Thruster control is MAVLink RC_CHANNELS_OVERRIDE (msg 70) at 40 Hz, PWM
# 1100/1500/1900, sent to the same peer the telemetry comes from
# Identity is sysid 255 / compid 190, the standard GCS pair the app uses.
#
# READ THIS BEFORE USING IT. Which slot is physically forward, yaw or vertical
# is NOT recorded anywhere in the vendor app -- it is Chasing's own wiring, and
# slot 5 carrying a 1..100 value proves it is not stock ArduSub. So the labels
# below are the app's wiring, not confirmed axes. Find out in a bucket with the
# tether in your hand, not in open water.
#
# The app has NO failsafe: on disconnect it calls shutdownNow() and sends
# nothing. This does the opposite -- every key decays back to
# neutral after 400 ms unless repeated, and quitting sends a burst of neutral
# and then a disarm.
CRC_EXTRA = {0: 50, 11: 89, 20: 214, 21: 159, 22: 220,
             70: 124, 76: 152}   # from the app's own table
# Only needed to read the drone's answers; nothing here is ever sent.
MAV_RESULT = {0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED",
              3: "UNSUPPORTED", 4: "FAILED", 5: "IN_PROGRESS",
              6: "CANCELLED", 7: "COMMAND_LONG_ONLY", 8: "COMMAND_INT_ONLY"}
SEVERITY = {0: "EMERGENCY", 1: "ALERT", 2: "CRITICAL", 3: "ERROR",
            4: "WARNING", 5: "NOTICE", 6: "INFO", 7: "DEBUG"}
GCS_SYSID, GCS_COMPID = 255, 190
PWM_NEUTRAL, PWM_MIN, PWM_MAX = 1500, 1100, 1900
RC_IGNORE = 65535
HOLD_MS = 400                        # how long a keypress stays applied

# Slot -> (label, key pair). The labels are guesses; the run log records what
# you actually saw move.
# ArduSub's RC channel -> axis mapping, which is FIXED IN THE FIRMWARE and not
# configurable. Confirmed 2026-08-25 by reading 588 parameters off the vehicle:
# it is ArduSub (leak, internal-pressure and internal-temperature failsafes,
# SURFACE_DEPTH, GND_SPEC_GRAV, MOT_n_DIRECTION), FRAME = 1 = VECTORED.
#
# Independently confirmed on slot 1: the app has a dial whose button logs
# "Pitch = 0" and sends exactly channel index 1. That is ArduSub's pitch
# channel, which means ArduSub's standard order applies to the rest too.
#
# The array index here is RC channel N+1, i.e. index 0 is RC1.
#
#   0  roll       1  pitch      2  throttle (vertical)
#   3  yaw        4  forward    5  lateral -- REPURPOSED BY CHASING AS LIGHTS
#
# The old labels in this table were guesses and were wrong: slot 0 was called
# "fwd/back" (it is roll), slot 1 "vertical" (it is pitch), slot 2 "pitch"
# (it is vertical). Worse, nothing drove slot 4 at all -- the one axis that
# actually moves the drone forwards.
AXES = {
    4: ("forward / back", "arrows up/down, or forward/back"),
    3: ("yaw, turn left/right", "arrows left/right, or left/right"),
    2: ("vertical, up towards the surface", "w / s, or up/down"),
    0: ("roll", "q / e, or rollleft/rollright"),
    1: ("pitch (inverted in the app)", "r / f, or pitchup/pitchdown"),
}

def mav_heartbeat(seq):
    """A GCS heartbeat, exactly as the app sends it.

    THIS is what was missing when the drone answered every arm with DISARMED
    on 2026-08-24. The app runs `new z6.c(1, g())` -- a scheduler firing once
    a SECOND -- and every tick sends a
    HEARTBEAT with type 6 (MAV_TYPE_GCS) and autopilot 0, from sysid 255 /
    compid 190. ArduPilot-derived firmware treats a GCS that is not beating as
    absent: it will not arm for it, and it discards RC_CHANNELS_OVERRIDE.
    We were sending perfect RC frames into a link the drone did not consider
    alive.

    Payload is 9 bytes in this order: custom_mode as
    a uint32 first, then type, autopilot, base_mode, system_status,
    mavlink_version -- the app leaves the last three at 0."""
    body = struct.pack("<IBBBBB", 0, 6, 0, 0, 0, 0)
    return mav_pack(0, body, seq)

class Heartbeat:
    """Beats at 1 Hz on its own thread for as long as the control link is up."""
    def __init__(self, sock, peer):
        self.sock, self.peer = sock, peer
        self.seq, self.sent = 0, 0
        self._stop = threading.Event()
        self._t = None

    def start(self):
        def run():
            while not self._stop.is_set():
                try:
                    self.sock.sendto(mav_heartbeat(self.seq), self.peer)
                    self.seq = (self.seq + 1) & 0xFF
                    self.sent += 1
                except OSError:
                    pass
                self._stop.wait(1.0)
        self._t = threading.Thread(target=run, daemon=True)
        self._t.start()
        dbg(f"heartbeat: 1 Hz to {self.peer[0]}:{self.peer[1]}, "
            f"type 6 (GCS) sysid {GCS_SYSID}/{GCS_COMPID}")
        return self

    def stop(self):
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.5)
        dbg(f"heartbeat: stopped after {self.sent}")

def rc_frame(power_pct, overrides=None):
    """The app's baseline RC frame, rebuilt exactly.

    This is where the 2026-08-24 run went wrong. We were sending channels 0-3
    and leaving 4, 5 and 7 at 65535 = "ignore". The app never does that:

        iArr[0..4] = 1500          five channels centred, not four
        iArr[5]    = f9184d        a GAIN in 1..100 -- not a PWM value; i()
                                   clamps it to that range, and it is why
                                   CLAUDE.md notes slot 5 rules out ArduSub
        iArr[6]    = 65535         the only channel genuinely left alone
        iArr[7]    = 1500          Dory only (i6.a.C() == 100 or 104)

    Channel 5 is the LIGHT BRIGHTNESS, 1..100 -- not a thrust gain, which is
    what this comment said until 2026-08-25. The app's own light button proves
    it: it reads channel 5 back, and if it is > 30 it sends
    F(5, -100) to clamp it to 1 and calls that OFF; otherwise F(5, -100) then
    F(5, 40), landing on 41, and calls that ON. So 1 is off and the app never
    sends 0. --lights sets it; --power drives the stick deflection instead."""
    frame = [RC_IGNORE] * 8
    for ch in (0, 1, 2, 3, 4):
        frame[ch] = PWM_NEUTRAL
    frame[5] = max(1, min(100, int(LIGHTS)))
    frame[7] = PWM_NEUTRAL
    for ch, pwm in (overrides or {}).items():
        frame[ch] = pwm
    return frame

def mav_crc(payload, msgid):
    """X25 over len,seq,sysid,compid,msgid,payload then the per-message extra."""
    crc = 0xFFFF
    for b in payload:
        tmp = (b ^ (crc & 0xFF)) & 0xFF
        tmp = (tmp ^ (tmp << 4)) & 0xFF
        crc = ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF
    tmp = (CRC_EXTRA[msgid] ^ (crc & 0xFF)) & 0xFF
    tmp = (tmp ^ (tmp << 4)) & 0xFF
    return ((crc >> 8) ^ (tmp << 8) ^ (tmp << 3) ^ (tmp >> 4)) & 0xFFFF

def mav_pack(msgid, payload, seq):
    hdr = bytes([len(payload), seq & 0xFF, GCS_SYSID, GCS_COMPID, msgid])
    crc = mav_crc(hdr + payload, msgid)
    return b"\xfe" + hdr + payload + crc.to_bytes(2, "little")

def rc_override(channels, tgt_sys, tgt_comp, seq):
    import struct
    body = b"".join(struct.pack("<H", c) for c in channels)
    return mav_pack(70, body + bytes([tgt_sys, tgt_comp]), seq)

def set_mode(custom_mode, tgt_sys, seq):
    """SET_MODE (msg 11), as the app builds it: target_system, base_mode = 1
    (MAV_MODE_FLAG_CUSTOM_MODE_ENABLED), custom_mode --
    ROV_STABILIZE(0), ROV_DEPTH_HOLD(2), ROV_MANUAL(19). Wire order is
    custom_mode as a uint32 first, then the two uint8s."""
    body = struct.pack("<IBB", custom_mode, tgt_sys, 1)
    return mav_pack(11, body, seq)

def arm_disarm(arm, tgt_sys, tgt_comp, seq):
    import struct
    body = struct.pack("<7f", 1.0 if arm else 0.0, 0, 0, 0, 0, 0, 0)
    body += struct.pack("<H", 400) + bytes([tgt_sys, tgt_comp, 0])
    return mav_pack(76, body, seq)

def control_selftest(seconds=None):
    seconds = seconds if seconds is not None else (TIMEOUT or 12)
    """Prove the control transport without moving anything.

    Sends NEUTRAL frames only (1500 on every driven slot), never arms, and
    never touches the keyboard -- so it is safe to run unattended and from a
    script. What it establishes: that the drone is talking MAVLink to us, what
    system/component id it uses, and that our frames leave the machine. It
    cannot prove the drone acted on them; only a thruster moving does that."""
    import struct
    try:
        sock = bind_udp(MAVLINK_PORT)
    except OSError as e:
        say(f"Cannot listen on UDP {MAVLINK_PORT}: {e}")
        for line in port_holder(MAVLINK_PORT).splitlines():
            say("   " + line)
        return 1
    sock.settimeout(1.0)

    say(f"control selftest: neutral frames only, no arming, {seconds}s")
    hb = None
    peer, tgt_sys, tgt_comp, seq, sent = None, 1, 1, 0, 0
    seen = {}
    deadline = time.time() + seconds
    last_tx = 0.0
    while time.time() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
            if peer is None:
                peer = addr
                say(f"  drone at {addr[0]}:{addr[1]}")
            for msgid, payload in mav_frames(data):
                seen[msgid] = seen.get(msgid, 0) + 1
                if msgid == 0 and len(data) > 4:
                    tgt_sys, tgt_comp = data[3], data[4]
        except socket.timeout:
            pass
        now = time.time()
        if peer and hb is None:
            hb = Heartbeat(sock, peer).start()
        if peer and now - last_tx >= 0.025:
            frame = rc_frame(POWER)
            sock.sendto(rc_override(frame, tgt_sys, tgt_comp, seq), peer)
            seq = (seq + 1) & 0xFF; sent += 1; last_tx = now

    log(f"   control selftest: peer={peer} target={tgt_sys}/{tgt_comp} "
        f"sent={sent} received={seen}")
    if peer is None:
        say(f"  FAILED: nothing arrived on UDP {MAVLINK_PORT} in {seconds}s.")
        say("  Without a packet from the drone there is no address to send to,")
        say("  so nothing was transmitted. Is it powered and linked to the buoy?")
        return 1
    say(f"  sent {sent} neutral RC frames to {peer[0]}:{peer[1]}, "
        f"target system {tgt_sys}/{tgt_comp}")
    say(f"  received by message id: {seen}")
    say("  transport works. Whether the drone acts on it is untested — that")
    say("  needs --control and something to watch move.")
    return 0

# One key -> (slot, direction). Same mapping the interactive loop uses, so a
# scripted run and a hand-driven one exercise exactly the same thing.
# Named after what they DO, not after which key sends them. "up" used to mean
# slot 4, forward -- the joystick convention, where pushing the stick away from
# you is forwards. That is indefensible in a command you type: `--send "up 2"`
# has to make the drone go up.
DRIVE_KEYS = {
    "forward":   (4, +1), "back":      (4, -1),
    "up":        (2, +1), "down":      (2, -1),   # vertical, towards/from air
    "left":      (3, -1), "right":     (3, +1),   # yaw
    "rollleft":  (0, -1), "rollright": (0, +1),
    "pitchup":   (1, +1), "pitchdown": (1, -1),
    "a": (None, 0),                               # arm only, move nothing
    # Short forms, for typing.
    "f": (4, +1), "b": (4, -1),
    "u": (2, +1), "d": (2, -1),
    "l": (3, -1), "r": (3, +1),
}

def http_json(url, body=None, timeout=4):
    """Small self-contained HTTP helper. The real request() lives in the HTTP
    section a thousand lines below, and the control paths exit before the
    interpreter ever gets there."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        req.add_header("Content-Type", "application/json")
    req.add_header("Connection", "close")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(400).decode("utf-8", "replace").strip()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw
    except urllib.error.HTTPError as e:
        return e.code, e.read(200).decode("utf-8", "replace").strip()
    except Exception as e:
        return 0, str(e)

def claim_control(host=None, tries=5):
    """POST /v1/control {"control":"obtain"} -- take the control role.

    This is what the app does the instant it connects, and it RETRIES ONCE A
    SECOND until the reply comes back with controlrole true, only then
    treating itself as in control. Everything else it sends assumes that role.

    Without it we are a passive observer: the vehicle has no reason to stream
    telemetry to us and no reason to act on anything we send. That fits every
    symptom -- HTTP fine, video fine once asked for, and MAVLink silent with
    not one COMMAND_ACK in five runs."""
    host = host or (os.environ.get("DORY_HOST") or "192.168.1.1").split(":")[0]
    url = f"http://{host}/v1/control"
    for i in range(tries):
        st, body = http_json(url, {"control": "obtain"})
        got = None
        if isinstance(body, dict):
            d = body.get("data", body)
            if isinstance(d, dict):
                got = d.get("controlrole")
        dbg(f"control claim {i + 1}/{tries}: {st} {body}")
        if got:
            say(f"  control role obtained from {host}")
            return True
        time.sleep(1.0)
    say(f"  could NOT obtain the control role from {host}: {st} {body}")
    return False

def mav_hdr(data):
    """Decode a MAVLink frame header without assuming v1. We have been reading
    sysid/compid from data[3]/data[4], which is only correct for v1 (0xFE).
    In v2 (0xFD) they sit at data[5]/data[6] -- if the drone speaks v2 then
    every target id we have ever sent has been wrong, and that alone would
    explain four runs with no COMMAND_ACK."""
    if not data:
        return None
    if data[0] == 0xFE and len(data) >= 6:
        return dict(ver=1, ln=data[1], seq=data[2], sysid=data[3],
                    compid=data[4], msgid=data[5])
    if data[0] == 0xFD and len(data) >= 10:
        return dict(ver=2, ln=data[1], seq=data[4], sysid=data[5],
                    compid=data[6],
                    msgid=data[7] | (data[8] << 8) | (data[9] << 16))
    return None

def identify():
    """Ask the flight controller what it is. Read-only, nothing is armed.

    Two questions, both answerable without touching a thruster:

      1. AUTOPILOT_VERSION (msg 148) -- what it claims to be: firmware
         version, board and vendor ids, and the capability bitmask. Requested
         with COMMAND_LONG / MAV_CMD_REQUEST_AUTOPILOT_CAPABILITIES (520).
      2. PARAM_REQUEST_LIST (msg 21) -- every parameter it holds, by name.
         Stock ArduSub names (FRAME_CONFIG, SERVO*_FUNCTION, BRD_*) would
         settle whether this is ArduPilot in one dump, and that dump is also
         what any reflash would have to preserve.

    The full parameter list goes to a file. Do not delete it: it is the only
    record of how this vehicle was set up, and there is no way to get it back
    if a reflash goes wrong."""
    import select, struct
    try:
        # A big buffer matters here and nowhere else: the vehicle answers
        # PARAM_REQUEST_LIST with hundreds of packets as fast as it can, and
        # the default receive buffer overflows. The first run of this got 14
        # of 588 -- scattered indices, which is the signature of drops rather
        # than a short list.
        sock = bind_udp(MAVLINK_PORT, rcvbuf=4 * 1024 * 1024)
    except OSError as e:
        say(f"Cannot bind UDP {MAVLINK_PORT}: {e}")
        for line in port_holder(MAVLINK_PORT).splitlines():
            say("   " + line)
        return 1
    sock.settimeout(1.0)
    claim_control()

    say(f"waiting for the drone on UDP {MAVLINK_PORT} ...")
    peer, tgt_sys, tgt_comp = None, 0, 0
    t0 = time.time()
    while peer is None and time.time() - t0 < 15:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        h = mav_hdr(data)
        if not h:
            continue
        peer = addr
        if h["msgid"] == 0:
            tgt_sys, tgt_comp = h["sysid"], h["compid"]
    if peer is None:
        say("Nothing arrived. Is the drone powered and the firewall down?")
        return 1
    say(f"drone at {peer[0]}:{peer[1]}, sysid {tgt_sys} compid {tgt_comp}")

    hb = Heartbeat(sock, peer).start()
    time.sleep(1.5)

    def payload_of(data, h):
        return data[6:6 + h["ln"]] if h["ver"] == 1 else data[10:10 + h["ln"]]

    # ---------------------------------------------------------- 1. version
    say("")
    say("=" * 68)
    say("1  AUTOPILOT_VERSION — what does it say it is?")
    say("=" * 68)
    CAPS = {
        0: "MISSION_FLOAT", 1: "PARAM_FLOAT", 2: "MISSION_INT",
        3: "COMMAND_INT", 4: "PARAM_UNION", 5: "FTP",
        6: "SET_ATTITUDE_TARGET", 7: "SET_POSITION_TARGET_LOCAL_NED",
        8: "SET_POSITION_TARGET_GLOBAL_INT", 9: "TERRAIN",
        10: "SET_ACTUATOR_TARGET", 11: "FLIGHT_TERMINATION",
        12: "COMPASS_CALIBRATION", 13: "MAVLINK2", 14: "MISSION_FENCE",
        15: "MISSION_RALLY", 16: "FLIGHT_INFORMATION",
    }
    body = struct.pack("<7f", 1, 0, 0, 0, 0, 0, 0)
    body += struct.pack("<H", 520) + bytes([tgt_sys, tgt_comp, 0])
    got_ver = False
    for attempt in range(3):
        sock.sendto(mav_pack(76, body, attempt), peer)
        end = time.time() + 3
        while time.time() < end and not got_ver:
            if not select.select([sock], [], [], 0.2)[0]:
                continue
            try:
                data, _ = sock.recvfrom(4096)
            except OSError:
                continue
            h = mav_hdr(data)
            if not h:
                continue
            pl = payload_of(data, h)
            if h["msgid"] == 148 and len(pl) >= 60:
                caps, uid = struct.unpack_from("<QQ", pl, 0)
                fsw, msw, osw, board = struct.unpack_from("<IIII", pl, 16)
                vend, prod = struct.unpack_from("<HH", pl, 32)
                def ver(v):
                    return f"{(v >> 24) & 255}.{(v >> 16) & 255}.{(v >> 8) & 255}"
                say(f"  flight sw      {ver(fsw)}   (raw 0x{fsw:08x})")
                say(f"  middleware sw  {ver(msw)}")
                say(f"  os sw          {ver(osw)}")
                say(f"  board version  0x{board:08x}")
                say(f"  vendor id      {vend}    product id {prod}")
                say(f"  uid            0x{uid:016x}")
                say(f"  capabilities   0x{caps:016x}")
                for bit, name in CAPS.items():
                    if caps & (1 << bit):
                        say(f"                   {name}")
                log(f"   AUTOPILOT_VERSION caps=0x{caps:x} fsw=0x{fsw:x} "
                    f"board=0x{board:x} vendor={vend} product={prod}")
                got_ver = True
            elif h["msgid"] == 77 and len(pl) >= 3:
                cmd, res = struct.unpack_from("<HB", pl, 0)
                if cmd == 520:
                    say(f"  COMMAND_ACK 520 -> {MAV_RESULT.get(res, res)}")
        if got_ver:
            break
        say(f"  no answer (attempt {attempt + 1}/3)")
    if not got_ver:
        say("  It never sent AUTOPILOT_VERSION. Either it does not implement")
        say("  the message, or it does not implement command 520. That is")
        say("  itself informative: stock ArduPilot answers both.")

    # ------------------------------------------------------- 2. parameters
    say("")
    say("=" * 68)
    say("2  PARAM_REQUEST_LIST — every parameter it holds")
    say("=" * 68)
    params, byindex, total = {}, {}, None

    def soak(seconds, quiet=False):
        """Read as fast as the socket will give it up. No per-packet select
        timeout: a burst of PARAM_VALUE arrives faster than a 0.3s poll can
        keep up with, and every missed poll is a dropped parameter."""
        nonlocal total
        end, last_rx = time.time() + seconds, time.time()
        while time.time() < end:
            r = select.select([sock], [], [], 0.05)[0]
            if not r:
                if time.time() - last_rx > 4:
                    return False          # it has stopped sending
                continue
            # Drain everything queued before going back to select.
            while True:
                try:
                    data, _ = sock.recvfrom(4096)
                except (BlockingIOError, socket.timeout, OSError):
                    break
                last_rx = time.time()
                h = mav_hdr(data)
                if not h or h["msgid"] != 22:
                    break
                pl = payload_of(data, h)
                if len(pl) < 25:
                    break
                val, count, index = struct.unpack_from("<fHH", pl, 0)
                name = pl[8:24].split(b"\x00")[0].decode("ascii", "replace")
                if name:
                    total = count
                    params[name] = (val, pl[24], index)
                    byindex[index] = name
                    if not quiet and len(params) % 100 == 0:
                        say(f"  ... {len(params)} of {count}")
                break
        return True

    sock.setblocking(False)
    sock.sendto(mav_pack(21, bytes([tgt_sys, tgt_comp]), 0), peer)
    say("  asked for the full list ...")
    soak(45)
    say(f"  first pass: {len(params)} of {total}")

    # Fill the gaps. PARAM_REQUEST_READ (msg 20) asks for one parameter by
    # index, which is the only reliable way to get the ones that were dropped:
    # payload is param_index (int16) then target_system, target_component,
    # then a 16-byte name that is ignored when the index is >= 0.
    if total and len(params) < total:
        missing = [i for i in range(total) if i not in byindex]
        say(f"  {len(missing)} missing; asking for those by index "
            f"(this is the slow part)")
        rounds = 0
        while missing and rounds < 6:
            rounds += 1
            for i in missing:
                # Wire layout: MAVLink sorts fields by size, so the int16
                # index leads, then the two ids, then the 16-byte name --
                # which is ignored when the index is >= 0.
                body = struct.pack("<h", i) + bytes([tgt_sys, tgt_comp]) + b"\x00" * 16
                try:
                    sock.sendto(mav_pack(20, body, i & 0xFF), peer)
                except OSError:
                    pass
                if i % 40 == 0:
                    soak(0.4, quiet=True)
                else:
                    time.sleep(0.004)
            soak(12, quiet=True)
            was, missing = len(missing), [i for i in range(total) if i not in byindex]
            say(f"  round {rounds}: {len(params)} of {total} "
                f"({was - len(missing)} recovered)")
            if was == len(missing):
                break
    hb.stop()

    if not params:
        say("  NOTHING came back. It does not answer PARAM_REQUEST_LIST,")
        say("  which stock ArduPilot always does.")
        return 1

    out = os.path.join(os.path.dirname(LOGPATH), "params.txt")
    with open(out, "w") as f:
        f.write(f"# {len(params)} of {total} parameters, {time.strftime('%F %T')}\n")
        for n in sorted(params):
            v, t, i = params[n]
            f.write(f"{n:<20} {v!r:<24} type={t} index={i}\n")
    say(f"  got {len(params)} of {total}, written to {out}")

    # The names are the tell. Stock ArduSub has all of these.
    # Prefixes, not exact names. The first run of this looked for ArduSub's
    # names (FRAME_CONFIG, SURFACE_DEPTH, PILOT_SPEED_UP), found none, and
    # reported "not ArduPilot" -- while the parameters it HAD collected were
    # AHRS_TRIM_X, EK2_GPS_DELAY, INS_USE2, COMPASS_ODI_Y and FRAME, which are
    # unmistakably ArduPilot. Note FRAME rather than FRAME_CONFIG: that is
    # ArduCopter's name, so this is a Copter-derived build, not Sub.
    # Two attempts at this were wrong before it settled. First I looked for
    # NEW ArduSub names (FRAME_CONFIG, JS_, PILOT_SPEED_UP), found none, and
    # said "not ArduPilot" -- while the dump was full of AHRS_/EK2_/INS_.
    # Then I matched shared Copter prefixes (PILOT_, WPNAV_, PSC_) and said
    # ArduCopter -- but ArduSub is a Copter FORK and shares nearly all of them.
    #
    # Only the parameters that exist in Sub and nowhere else decide it. Those
    # are the ones about being underwater.
    CORE = ["AHRS_", "INS_", "COMPASS_", "EK2_", "EK3_", "ATC_", "RC1_",
            "SERVO", "BRD_", "SR0_"]
    SUB_ONLY = ["FS_LEAK_ENABLE", "FS_PRESS_ENABLE", "FS_TEMP_ENABLE",
                "SURFACE_DEPTH", "GND_SPEC_GRAV", "MOT_1_DIRECTION"]
    core = sorted({p for p in CORE if any(n.startswith(p) for n in params)})
    subs = sorted(p for p in SUB_ONLY if p in params)
    say("")
    say(f"  ArduPilot core families   {len(core)}/{len(CORE)}   {' '.join(core)}")
    say(f"  ArduSub-only parameters   {len(subs)}/{len(SUB_ONLY)}   {' '.join(subs)}")
    say("")
    if len(core) >= 4 and len(subs) >= 3:
        say("  -> ArduSub. The underwater-only parameters settle it: leak,")
        say("     internal pressure and temperature failsafes, surface depth")
        say("     and water specific gravity exist in no other ArduPilot build.")
        if "FRAME_CONFIG" not in params and "FRAME" in params:
            say("     It uses FRAME rather than FRAME_CONFIG, so it is an OLDER")
            say("     ArduSub -- the parameter was renamed in later releases.")
    elif len(core) >= 4:
        say(f"  -> ArduPilot ({len(core)} core families) but not Sub. Read the dump.")
    else:
        say(f"  -> only {len(core)} ArduPilot families. Inconclusive.")

    # The handful that change how the vehicle behaves, called out by name.
    say("")
    say("  worth knowing:")
    for n, why in (("ARMING_CHECK", "0 = pre-arm checks disabled"),
                   ("FS_GCS_ENABLE", "GCS-loss failsafe action"),
                   ("FS_LEAK_ENABLE", "leak failsafe"),
                   ("SURFACE_DEPTH", "depth treated as the surface, cm"),
                   ("BATT_MONITOR", "battery monitor type"),
                   ("FRAME", "frame/thruster layout")):
        if n in params:
            say(f"    {n:<16} {params[n][0]:<12} {why}")
    mots = sorted(n for n in params if n.startswith("MOT_") and n.endswith("_DIRECTION"))
    if mots:
        dirs = " ".join(f"{n.split('_')[1]}:{params[n][0]:+.0f}" for n in mots)
        say(f"    {len(mots)} thruster directions   {dirs}")
    say(f"  Read {out} for the whole set. KEEP IT: it is the only record of")
    say("  how this vehicle is configured, and a reflash would need it.")
    log(f"   identify: {len(params)}/{total} params, ArduPilot markers {hits}/9")
    return 0

def probe():
    """One arm, one up, everything printed. No loops, no cleverness.

    The point is a single short transcript that shows exactly what leaves this
    machine and exactly what comes back, so the next question is answered by
    reading rather than by another theory."""
    import select, struct
    def hx(b, n=48):
        return " ".join(f"{x:02x}" for x in b[:n]) + (" ..." if len(b) > n else "")

    try:
        sock = bind_udp(MAVLINK_PORT)
    except OSError as e:
        say(f"Cannot bind UDP {MAVLINK_PORT}: {e}")
        for line in port_holder(MAVLINK_PORT).splitlines():
            say("   " + line)
        return 1
    sock.settimeout(1.0)

    # Talk to the ROV before listening. Not as a health check -- ARP is a
    # cache and proves nothing after a Wi-Fi switch -- but because every run
    # that ever produced telemetry had HTTP traffic to .88 before the MAVLink
    # listen, and the bare probe had none. If contact is what starts the
    # stream, this is the difference.
    say("=" * 68)
    say("STEP 0  make contact with the ROV at 192.168.1.88")
    say("=" * 68)
    for host in ("192.168.1.88", "192.168.1.1"):
        try:
            cmd = (["ping", "-n", "1", "-w", "1000", host] if IS_WIN
                   else ["ping", "-c", "1", "-W", "1000", host])
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            ok = ("1 packets received" in r.stdout or "bytes from" in r.stdout
                  or "Reply from" in r.stdout)
            say(f"  ping {host:<14} {'reply' if ok else 'no reply'}")
        except Exception as e:
            say(f"  ping {host:<14} failed: {e}")
        # Not request(): that lives in the HTTP section further down and the
        # probe exits before the interpreter ever reaches it. Inline and
        # self-contained here.
        try:
            with urllib.request.urlopen(f"http://{host}/v1/status", timeout=3) as r:
                body = r.read(200).decode("utf-8", "replace").strip()
                say(f"  GET  http://{host}/v1/status -> {r.status} {body[:60]}")
        except urllib.error.HTTPError as e:
            say(f"  GET  http://{host}/v1/status -> {e.code} "
                f"{e.read(60).decode('utf-8', 'replace').strip()}")
        except Exception as e:
            say(f"  GET  http://{host}/v1/status -> no answer ({e})")
    say("")
    say("  claiming the control role, as the app does on connect:")
    claim_control()
    say("")

    say("=" * 68)
    say("STEP 1  listen 5s, decode every frame header")
    say("=" * 68)
    peer, seen, vers = None, {}, set()
    ids = {}
    t0 = time.time()
    while time.time() - t0 < 5:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        peer = peer or addr
        h = mav_hdr(data)
        if h:
            vers.add(h["ver"])
            ids[h["msgid"]] = ids.get(h["msgid"], 0) + 1
            key = (h["ver"], h["sysid"], h["compid"], h["msgid"])
            if key not in seen:
                seen[key] = True
                say(f"  v{h['ver']}  sysid={h['sysid']:<3} compid={h['compid']:<3} "
                    f"msgid={h['msgid']:<4} len={h['ln']}")
                say(f"      {hx(data)}")
    if peer is None:
        say("  NOTHING ARRIVED on UDP 14550.")
        if IS_MAC and os.path.exists(FWBIN) and \
                subprocess.run([FWBIN, "--getglobalstate"], capture_output=True,
                               text=True).stdout.find("State = 1") >= 0:
            say("")
            say("  THE MACOS FIREWALL IS ON, and that alone is enough to")
            say("  explain this: it drops inbound UDP to this process without")
            say("  a trace. Verified 2026-08-24 -- 608 MAVLink packets on the")
            say("  wire while this socket saw none. Fix it and re-run:")
            say(f"     sudo {FWBIN} --setglobalstate off")
            return 1
        # The buoy and the ROV are two devices. The buoy answers Wi-Fi, HTTP
        # and the netcode handshake on its own; none of that means the drone
        # is powered. ARP is the quickest way to tell them apart.
        say("  STEP 0 above says whether the ROV answered. If it replied to")
        say("  ping or HTTP then it is up and simply not sending MAVLink,")
        say("  which is the fault worth chasing. ARP on its own proves")
        say("  nothing here: it is a cache, and it is empty for a minute or")
        say("  two after switching onto this Wi-Fi.")
        return 1
    say(f"  peer={peer[0]}:{peer[1]}  framing=v{sorted(vers)}  counts={ids}")

    hh = None
    for (ver, sysid, compid, msgid) in seen:
        if msgid == 0:
            hh = (ver, sysid, compid)
    if hh:
        say(f"  HEARTBEAT is v{hh[0]} from sysid={hh[1]} compid={hh[2]}")
        tgt_sys, tgt_comp = hh[1], hh[2]
    else:
        say("  NO HEARTBEAT SEEN — nothing to target.")
        tgt_sys, tgt_comp = 1, 1
    say(f"  -> we will target sysid={tgt_sys} compid={tgt_comp}")

    def drain(secs, tag):
        end = time.time() + secs
        got = 0
        while time.time() < end:
            if not select.select([sock], [], [], 0.1)[0]:
                continue
            try:
                data, src = sock.recvfrom(4096)
            except OSError:
                continue
            h = mav_hdr(data)
            if not h:
                continue
            got += 1
            m = h["msgid"]
            if m == 77 and len(data) > 9:
                pl = data[6:6 + h["ln"]] if h["ver"] == 1 else data[10:10 + h["ln"]]
                if len(pl) >= 3:
                    cmd, res = struct.unpack_from("<HB", pl, 0)
                    say(f"  [{tag}] COMMAND_ACK cmd={cmd} result={res} "
                        f"({MAV_RESULT.get(res, res)})")
                    say(f"        {hx(data)}")
            elif m == 253:
                pl = data[6:6 + h["ln"]] if h["ver"] == 1 else data[10:10 + h["ln"]]
                txt = pl[1:51].split(b"\x00")[0].decode("utf-8", "replace")
                if txt:
                    say(f"  [{tag}] STATUSTEXT sev={pl[0]} {txt}")
            elif m == 0:
                pl = data[6:6 + h["ln"]] if h["ver"] == 1 else data[10:10 + h["ln"]]
                if len(pl) >= 7:
                    say(f"  [{tag}] HEARTBEAT base_mode=0x{pl[6]:02x} "
                        f"{'ARMED' if pl[6] & 0x80 else 'disarmed'} "
                        f"custom_mode={struct.unpack_from('<I', pl, 0)[0]}")
        return got

    say("")
    say("=" * 68)
    say(f"STEP 2  send 3 GCS heartbeats to {peer[0]}:{peer[1]}, watch for a reaction")
    say("=" * 68)
    for i in range(3):
        pkt = mav_heartbeat(i)
        say(f"  TX heartbeat #{i}: {hx(pkt)}")
        try:
            sock.sendto(pkt, peer)
        except OSError as e:
            say(f"  SEND FAILED: {e}")
        drain(1.0, "hb")

    say("")
    say("=" * 68)
    say("STEP 3  one ARM")
    say("=" * 68)
    pkt = arm_disarm(True, tgt_sys, tgt_comp, 10)
    say(f"  TX arm: {hx(pkt, 40)}")
    say(f"      msgid=76 target_sys={tgt_sys} target_comp={tgt_comp} "
        f"cmd=400 param1=1.0")
    sock.sendto(pkt, peer)
    n = drain(4.0, "arm")
    say(f"  {n} frames back in 4s")

    say("")
    say("=" * 68)
    say("STEP 4  one UP, 2s of RC at 40 Hz")
    say("=" * 68)
    frame = rc_frame(POWER, {0: 1620})
    say(f"  channels: {frame}")
    pkt = rc_override(frame, tgt_sys, tgt_comp, 0)
    say(f"  TX rc: {hx(pkt, 40)}")
    end, seq = time.time() + 2.0, 0
    while time.time() < end:
        sock.sendto(rc_override(frame, tgt_sys, tgt_comp, seq), peer)
        seq = (seq + 1) & 0xFF
        time.sleep(0.025)
    say(f"  sent {seq} RC frames")
    drain(2.0, "rc")

    say("")
    say("=" * 68)
    say("STEP 5  neutral and disarm")
    say("=" * 68)
    for i in range(10):
        sock.sendto(rc_override(rc_frame(POWER), tgt_sys, tgt_comp, i), peer)
        time.sleep(0.025)
    sock.sendto(arm_disarm(False, tgt_sys, tgt_comp, 200), peer)
    drain(2.0, "end")
    say("")
    say("Done. If STEP 3 and 4 show no COMMAND_ACK and no ARMED, nothing we")
    say("send is reaching the flight controller.")
    return 0

# ================================================================ daemon ===
# One process owns the link; every command reuses it.
#
# This is the shape the drone actually wants. Everything it needs is
# CONTINUOUS -- the control role, a 1 Hz GCS heartbeat, and 40 Hz RC frames --
# and a CLI that connects, arms, moves and exits tears all three down between
# commands. Nine separate --control invocations produced nine GCS failsafes and
# not one turn of a thruster.
#
# The daemon holds the UDP link, the netcode session, the control role, the
# heartbeat and the RC stream for its whole life. Commands arrive over a Unix
# domain socket -- bidirectional, so a command gets a real answer back
# (ARMED, DENIED, a PreArm reason) rather than being fired into the dark.
# It also means exactly one process owns UDP 14550 by design, which is the
# structural fix for the orphaned interpreters that ate two test runs.
#
# Safety, because an armed drone with nobody watching is the hazard here:
#   - every movement command carries a duration and expires on its own
#   - no command at all for DEADMAN seconds -> neutral, link stays up
#   - quitting sends neutral x20 and a disarm, always

DEADMAN = 3.0          # seconds of silence before everything centres
MAX_HOLD = 20.0        # longest a single command may hold an axis

def sock_path():
    return os.environ.get("DORY_SOCK") or \
        os.path.join(os.path.dirname(LOGPATH), "dory.sock")

def daemon():
    import select, struct, threading as th

    if not hasattr(socket, "AF_UNIX"):
        # Windows 10 1803+ has AF_UNIX, but only in recent Pythons; say so
        # rather than dying on an AttributeError.
        say("This build of Python has no AF_UNIX, so --daemon cannot run.")
        say("Use --control instead, or a Python 3.9+ on Windows 10 1803+.")
        return 2
    path = sock_path()
    if os.path.exists(path):
        # A stale socket from a killed daemon; if nobody answers, clear it.
        probe_s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe_s.settimeout(0.5)
            probe_s.connect(path)
            probe_s.close()
            say(f"A daemon is already running on {path}.")
            say("Stop it with:  ./scripts/DoryControl.sh --send quit")
            return 1
        except OSError:
            os.unlink(path)
        finally:
            try:
                probe_s.close()
            except OSError:
                pass

    try:
        sock = bind_udp(MAVLINK_PORT)
    except OSError as e:
        say(f"Cannot bind UDP {MAVLINK_PORT}: {e}")
        for line in port_holder(MAVLINK_PORT).splitlines():
            say("   " + line)
        return 1
    sock.settimeout(1.0)

    say("claiming the control role ...")
    claim_control()

    say(f"waiting for the drone on UDP {MAVLINK_PORT} ...")
    peer, tgt_sys, tgt_comp = None, 0, 0
    t0 = time.time()
    while peer is None and time.time() - t0 < 15:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        h = mav_hdr(data)
        if not h:
            continue
        peer = addr
        if h["msgid"] == 0:
            tgt_sys, tgt_comp = h["sysid"], h["compid"]
    if peer is None:
        say("Nothing arrived. Is the firewall down and the drone powered?")
        return 1
    say(f"drone at {peer[0]}:{peer[1]}, sysid {tgt_sys} compid {tgt_comp}")

    st = dict(armed=False, want_arm=False, power=POWER,
              slot=None, pwm=PWM_NEUTRAL, until=0.0,
              last_cmd=time.time(), depth=None, batt=None,
              text="", running=True, sent=0)
    lock = th.Lock()

    hb = Heartbeat(sock, peer).start()

    def rc_loop():
        seq = 0
        while st["running"]:
            now = time.time()
            with lock:
                # Two independent expiries: the command's own duration, and
                # the dead-man that catches a client which stops talking.
                if st["slot"] is not None and now >= st["until"]:
                    st["slot"], st["pwm"] = None, PWM_NEUTRAL
                if now - st["last_cmd"] > DEADMAN and st["slot"] is not None:
                    st["slot"], st["pwm"] = None, PWM_NEUTRAL
                over = {} if st["slot"] is None else {st["slot"]: st["pwm"]}
                frame = rc_frame(st["power"], over)
            try:
                sock.sendto(rc_override(frame, tgt_sys, tgt_comp, seq), peer)
                seq = (seq + 1) & 0xFF
                st["sent"] += 1
            except OSError:
                pass
            time.sleep(0.025)

    def rx_loop():
        while st["running"]:
            if not select.select([sock], [], [], 0.2)[0]:
                continue
            try:
                data, _ = sock.recvfrom(4096)
            except OSError:
                continue
            h = mav_hdr(data)
            if not h:
                continue
            pl = data[6:6 + h["ln"]] if h["ver"] == 1 else data[10:10 + h["ln"]]
            m = h["msgid"]
            if m == 0 and len(pl) >= 7:
                st["armed"] = bool(pl[6] & 0x80)
            elif m == 74 and len(pl) >= 20:
                st["depth"] = abs(struct.unpack_from("<f", pl, 8)[0])
            elif m == 147 and len(pl) >= 36:
                rem = struct.unpack_from("<b", pl, 35)[0]
                st["batt"] = 0.0 if rem <= 15 else ((rem - 15) / 85.0) * 100.0
            elif m == 77 and len(pl) >= 3:
                cmd, res = struct.unpack_from("<HB", pl, 0)
                st["text"] = f"ACK {cmd} {MAV_RESULT.get(res, res)}"
                log(f"   daemon ACK {cmd} {res}")
            elif m == 253 and len(pl) >= 2:
                t = pl[1:51].split(b"\x00")[0].decode("utf-8", "replace")
                if t and "heartbeat lost" not in t:
                    st["text"] = t
                    log(f"   daemon says {t}")

    th.Thread(target=rc_loop, daemon=True).start()
    th.Thread(target=rx_loop, daemon=True).start()

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    os.chmod(path, 0o600)
    srv.listen(4)
    srv.settimeout(0.5)
    say("")
    say(f"ready. socket: {path}")
    say("  ./scripts/DoryControl.sh --send arm")
    say("  ./scripts/DoryControl.sh --send 'up 2'")
    say("  ./scripts/DoryControl.sh --send status")
    say("  ./scripts/DoryControl.sh --send quit")
    say("ctrl-C also stops it, neutral and disarmed.")

    def handle(line):
        global LIGHTS
        parts = line.split()
        if not parts:
            return "?"
        cmd, args = parts[0].lower(), parts[1:]
        if cmd in ("quit", "stop-daemon"):
            st["running"] = False
            return "stopping"
        if cmd == "status":
            with lock:
                held = "neutral" if st["slot"] is None else \
                       f"slot {st['slot']} at {st['pwm']}"
            return (f"armed={st['armed']} {held} power={st['power']} "
                    f"lights={LIGHTS} "
                    f"depth={st['depth']} batt={st['batt']} "
                    f"rc_sent={st['sent']} hb={hb.sent} last={st['text']!r}")
        if cmd == "arm":
            sock.sendto(arm_disarm(True, tgt_sys, tgt_comp, 0), peer)
            time.sleep(0.5)
            return f"arm sent, drone reports {'ARMED' if st['armed'] else 'DISARMED'}" \
                   + (f" — {st['text']}" if st["text"] else "")
        if cmd == "disarm":
            with lock:
                st["slot"], st["pwm"] = None, PWM_NEUTRAL
            time.sleep(0.2)
            sock.sendto(arm_disarm(False, tgt_sys, tgt_comp, 0), peer)
            return "disarm sent"
        if cmd == "mode":
            m = int(args[0]) if args else 19
            sock.sendto(set_mode(m, tgt_sys, 0), peer)
            return f"SET_MODE {m} sent"
        if cmd in ("lights", "light"):
            if args:
                a = args[0].lower()
                LIGHTS = 1 if a in ("off", "0") else \
                         41 if a in ("on",) else max(1, min(100, int(a)))
            return (f"lights={LIGHTS} "
                    f"({'off' if LIGHTS <= 30 else 'on'}) — channel 5")
        if cmd == "power":
            if args:
                st["power"] = max(1, min(100, int(args[0])))
            return f"power={st['power']}"
        if cmd == "sweep":
            # Every axis in turn, with a gap between, so it is obvious which
            # command moved what. This is the axis-mapping session in one line.
            # Eight seconds by default: long enough to walk round the drone
            # and see which thruster is actually turning. Two was long enough
            # to hear something and not long enough to locate it.
            secs = min(MAX_HOLD, float(args[0])) if args else 8.0
            if not st["armed"]:
                return "sweep: send arm first — the drone reports DISARMED."
            out = []
            for k in ("forward", "back", "up", "down", "left", "right",
                  "rollleft", "rollright", "pitchup", "pitchdown"):
                slot, sign = DRIVE_KEYS[k]
                span = int(400 * max(1, min(100, st["power"])) / 100.0)
                with lock:
                    st["slot"] = slot
                    st["pwm"] = max(PWM_MIN, min(PWM_MAX, PWM_NEUTRAL + sign * span))
                    st["until"] = time.time() + secs
                    st["last_cmd"] = time.time()
                say("")
                say(f"  >>> {k.upper():<5} slot {slot} at {st['pwm']} — "
                    f"RUNNING {secs:g}s, WATCH WHICH MOTOR")
                while time.time() < st["until"] and st["running"]:
                    st["last_cmd"] = time.time()
                    time.sleep(0.05)
                with lock:
                    st["slot"], st["pwm"] = None, PWM_NEUTRAL
                    st["last_cmd"] = time.time()
                out.append(f"{k}=slot{slot}")
                say("      neutral — 3s gap before the next one")
                t_gap = time.time() + 3.0
                while time.time() < t_gap and st["running"]:
                    st["last_cmd"] = time.time()
                    time.sleep(0.05)
            return ("sweep done: " + " ".join(out)
                    + ". Write down what each key moved.")
        if cmd in ("neutral", "centre", "center"):
            with lock:
                st["slot"], st["pwm"] = None, PWM_NEUTRAL
                st["last_cmd"] = time.time()
            return "neutral"
        if cmd in DRIVE_KEYS:
            secs = min(MAX_HOLD, float(args[0])) if args else 1.0
            slot, sign = DRIVE_KEYS[cmd]
            span = int(400 * max(1, min(100, st["power"])) / 100.0)
            with lock:
                st["slot"] = slot
                st["pwm"] = PWM_NEUTRAL if slot is None else \
                    max(PWM_MIN, min(PWM_MAX, PWM_NEUTRAL + sign * span))
                st["until"] = time.time() + secs
                st["last_cmd"] = time.time()
            if not st["armed"]:
                with lock:
                    st["slot"], st["pwm"] = None, PWM_NEUTRAL
                return (f"{cmd}: the drone reports DISARMED, so nothing would "
                        f"move. Send arm first. Nothing was held.")
            # Block until the hold finishes. Returning immediately meant a
            # pasted list of commands each cancelled the one before it -- on
            # 2026-08-24 "up 2" ran for about 100ms because "left 2" arrived
            # next, and nothing turned. One command at a time, and the reply
            # comes when the movement is actually over.
            held = st["pwm"]
            while time.time() < st["until"] and st["running"]:
                # Not silence: an executing command must not trip the dead-man.
                st["last_cmd"] = time.time()
                time.sleep(0.05)
            with lock:
                st["slot"], st["pwm"] = None, PWM_NEUTRAL
                st["last_cmd"] = time.time()
            return (f"{cmd}: held slot {slot} at {held} for {secs:g}s, "
                    f"now neutral. armed={st['armed']}"
                    + (f" — {st['text']}" if st["text"] else ""))
        return f"unknown: {cmd}. try: arm disarm {' '.join(DRIVE_KEYS)} " \
               f"neutral power N mode N status quit"

    try:
        while st["running"]:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(5)
                try:
                    line = conn.recv(512).decode("utf-8", "replace").strip()
                except OSError:
                    continue
                log(f"   daemon <- {line!r}")
                try:
                    reply = handle(line)
                except Exception as e:
                    reply = f"error: {e}"
                dbg(f"daemon: {line!r} -> {reply}")
                try:
                    conn.sendall((reply + "\n").encode())
                except OSError:
                    pass
    except KeyboardInterrupt:
        say("")
    finally:
        st["running"] = False
        with lock:
            st["slot"], st["pwm"] = None, PWM_NEUTRAL
        for i in range(20):
            try:
                sock.sendto(rc_override(rc_frame(st["power"]), tgt_sys, tgt_comp, i), peer)
            except OSError:
                pass
            time.sleep(0.025)
        try:
            sock.sendto(arm_disarm(False, tgt_sys, tgt_comp, 250), peer)
        except OSError:
            pass
        hb.stop()
        srv.close()
        try:
            os.unlink(path)
        except OSError:
            pass
        say("neutral sent, disarmed, socket removed.")
    return 0

def send_cmd(line):
    """Talk to a running daemon. One line in, one line out."""
    if not hasattr(socket, "AF_UNIX"):
        say("This build of Python has no AF_UNIX, so --send cannot run.")
        return 2
    path = sock_path()
    # The daemon does not open its socket until it is actually ready: netcode
    # handshake, control role, then the drone's first telemetry packet. That is
    # a few seconds on the drone's Wi-Fi, so a command typed immediately after
    # starting it would fail with "no daemon" when the daemon was simply still
    # coming up. Wait rather than make that the user's problem.
    # If no daemon is running, start one. Requiring the user to orchestrate
    # two terminals to send one command was a bad design: the daemon is an
    # implementation detail of "keep the link alive", not something anyone
    # should have to manage by hand.
    if not os.path.exists(path):
        launcher = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "DoryControl.sh")
        if os.path.exists(launcher):
            say("no daemon running — starting one ...")
            env = dict(os.environ)
            for k in ("DORY_SENDCMD", "DORY_DAEMON"):
                env.pop(k, None)
            dlog = os.path.join(os.path.dirname(LOGPATH), "daemon.log")
            try:
                open(dlog, "w").close()          # fresh, so the tail is ours
                with open(dlog, "ab") as lf:
                    child = subprocess.Popen([launcher, "--daemon"], env=env,
                                             stdout=lf, stderr=lf,
                                             stdin=subprocess.DEVNULL,
                                             start_new_session=True)
                say(f"   (its output goes to {dlog})")
            except Exception as e:
                say(f"   could not start it: {e}")

    deadline = time.time() + 40
    said = False
    c = None
    child = locals().get("child")
    while time.time() < deadline:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            c.settimeout(8)
            c.connect(path)
            break
        except OSError as e:
            c.close()
            c = None
            if not os.path.exists(path):
                if not said:
                    say("waiting for the daemon to be ready "
                        "(it opens the socket once the drone answers) ...")
                    said = True
                # If the daemon we just started has already exited, there is
                # nothing to wait for -- say why now instead of in 40 seconds.
                if child is not None and child.poll() is not None:
                    break
                try:
                    time.sleep(0.5)
                except KeyboardInterrupt:
                    say("cancelled.")
                    return 130
                continue
            say(f"Daemon socket exists but will not accept: {e}")
            return 1
    if c is None:
        dlog = os.path.join(os.path.dirname(LOGPATH), "daemon.log")
        if child is not None and child.poll() is not None:
            say(f"The daemon started and exited immediately (code {child.returncode}).")
        else:
            say("The daemon did not come up within 40s.")
        say(f"Why is in {dlog} — most likely one of:")
        say("  - the firewall needs lowering and sudo is not authorised;")
        say("    run `sudo -v` once, then try again")
        say("  - the drone is not powered, or this is not its Wi-Fi")
        try:
            tail = open(dlog).read().strip().splitlines()[-6:]
            if tail:
                say("")
                for ln in tail:
                    say("   " + ln)
        except Exception:
            pass
        return 1
    try:
        c.sendall((line + "\n").encode())
        say(c.recv(4096).decode("utf-8", "replace").strip())
    finally:
        c.close()
    return 0

def diagnose():
    """Everything, in one session, with tcpdump underneath as ground truth.

    Written after a day of one-hypothesis-per-trip debugging that never got a
    motor to turn. Each round tested a single idea and cost a whole session.
    This tests all of them at once and prints a matrix, so one log settles
    which of these is true rather than six more runs:

      A. does the ROV emit ANY UDP at all, and to which port?   (tcpdump)
      B. does MAVLink arrive on 14550, or somewhere else?       (3 sockets)
      C. is it v1 or v2 framing -- i.e. are our target ids right?
      D. does anything we send ever get acknowledged, and from
         which destination?                                     (4 candidates)
      E. does the control role change any of the above?
      F. does sustained HTTP polling, which the app does and we
         never have, change any of the above?

    tcpdump is the important one: it reads below the socket layer, so it can
    tell "the drone sends nothing" apart from "the drone sends something we
    are not listening for"."""
    import select, struct, threading as th
    host = (os.environ.get("DORY_HOST") or "192.168.1.1").split(":")[0]
    rov = "192.168.1.88"
    report = []

    def head(t):
        say(""); say("=" * 68); say(t); say("=" * 68)

    # --- A. ground truth on the wire -------------------------------------
    head("A  tcpdump: everything on the wire, both directions")
    cap = os.path.join(os.path.dirname(LOGPATH), "diagnose-udp.txt")
    tcp = None
    if IS_WIN:
        # No tcpdump. The rest of the diagnosis still runs; only the
        # ground-truth capture is missing, and on Windows the equivalent is
        # to run Wireshark alongside this.
        say("  Windows: no tcpdump. Everything else below still runs.")
        say("  For ground truth, capture UDP in Wireshark while this runs.")
    elif subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
        tcp = subprocess.Popen(
            ["sudo", "-n", "tcpdump", "-i", "en0", "-n", "-l",
             "udp and not port 53 and not port 5353"],
            stdout=open(cap, "w"), stderr=subprocess.DEVNULL)
        say(f"  capturing to {cap}")
        time.sleep(1.5)
    else:
        say("  no sudo, so no capture. Run `sudo -v` first for this to work;")
        say("  without it we cannot tell silence from listening on the wrong port.")

    # --- E/F. control role, and an app-like HTTP poller -------------------
    head("B  control role, and the HTTP polling the app never stops doing")
    st, body = http_json(f"http://{rov}/v1/status")
    say(f"  ROV  /v1/status -> {st}")
    got_role = claim_control(host)
    report.append(("control role", "obtained" if got_role else "REFUSED"))

    stop_poll = th.Event()
    def poll():
        while not stop_poll.is_set():
            for h, path in ((host, "/v1/status"), (rov, "/v1/status")):
                http_json(f"http://{h}{path}", timeout=2)
            stop_poll.wait(1.0)
    th.Thread(target=poll, daemon=True).start()
    say("  polling /v1/status on both hosts once a second, as the app does")

    # --- B. listen on every port it might use ----------------------------
    head("C  listen on 14550, 5600 and 1000 at once, 12s")
    socks = {}
    for port in (MAVLINK_PORT, VIDEO_PORT, 1000):
        try:
            socks[port] = bind_udp(port)
        except OSError as e:
            say(f"  cannot bind {port}: {e}")
    for sk in socks.values():
        sk.setblocking(False)

    seen = {}          # port -> {msgid: count}
    peers = {}         # port -> (ip, port)
    frames = {}        # port -> first raw frame
    vers = {}
    end = time.time() + 12
    while time.time() < end:
        r, _, _ = select.select(list(socks.values()), [], [], 0.2)
        for sk in r:
            port = [p for p, v in socks.items() if v is sk][0]
            try:
                data, addr = sk.recvfrom(4096)
            except OSError:
                continue
            peers.setdefault(port, addr)
            frames.setdefault(port, data)
            h = mav_hdr(data)
            if h:
                vers.setdefault(port, set()).add((h["ver"], h["sysid"], h["compid"]))
                d = seen.setdefault(port, {})
                d[h["msgid"]] = d.get(h["msgid"], 0) + 1
            else:
                d = seen.setdefault(port, {})
                d["raw"] = d.get("raw", 0) + 1
    for port in sorted(socks):
        if port in peers:
            say(f"  UDP {port:<6} from {peers[port][0]}:{peers[port][1]}  {seen.get(port)}")
            if port in vers:
                for v, sysid, compid in sorted(vers[port]):
                    say(f"           MAVLink v{v}  sysid={sysid} compid={compid}")
            say(f"           first frame: " +
                " ".join(f"{b:02x}" for b in frames[port][:24]))
            report.append((f"UDP {port} inbound", f"{sum(seen[port].values())} frames"))
        else:
            say(f"  UDP {port:<6} SILENT")
            report.append((f"UDP {port} inbound", "silent"))

    # target ids from whatever actually spoke
    tgt_sys, tgt_comp, ver = 1, 1, 1
    if MAVLINK_PORT in vers and vers[MAVLINK_PORT]:
        ver, tgt_sys, tgt_comp = sorted(vers[MAVLINK_PORT])[0]
    say(f"  -> targeting sysid={tgt_sys} compid={tgt_comp} (seen as v{ver})")
    report.append(("framing / target", f"v{ver} sysid={tgt_sys} compid={tgt_comp}"))

    # --- D. every destination, does anything answer? ---------------------
    head("D  send to each candidate destination, 6s each, watch for any ACK")
    sock = socks.get(MAVLINK_PORT)
    if sock is None:
        say("  no socket on 14550; cannot send.")
    else:
        base = peers.get(MAVLINK_PORT, (host, MAVLINK_PORT))
        cands = [(base[0], base[1], "the telemetry source"),
                 (rov, MAVLINK_PORT, "ROV, standard port"),
                 (rov, 1000, "ROV, the port the handshake announces"),
                 (host, 1000, "buoy, that same port")]
        for n, (dh, dp, why) in enumerate(cands, 1):
            dest = (dh, dp)
            # Three seconds of complete silence first. Nothing is sent, so a
            # thruster started by the previous destination has stopped well
            # before this one begins -- otherwise two adjacent phases blur
            # into one and you cannot tell which moved it.
            say("")
            say("  " + "-" * 60)
            say(f"  QUIET for 3s — nothing should be running")
            time.sleep(3.0)
            say("")
            say(f"  ####  DESTINATION {n} OF {len(cands)}  ####")
            say(f"  ####  {dh}:{dp}  —  {why}")
            say(f"  ####  driving channel 0 for 6s. LISTEN NOW.")
            say("")
            acks, texts, armed = [], [], False
            hb = Heartbeat(sock, dest).start()
            time.sleep(1.5)
            seqn = 0
            for pkt in (set_mode(19, tgt_sys, seqn),
                        arm_disarm(True, tgt_sys, tgt_comp, seqn + 1)):
                try:
                    sock.sendto(pkt, dest)
                except OSError as e:
                    say(f"      send failed: {e}")
                seqn += 1
            t_end = time.time() + 6
            while time.time() < t_end:
                # keep RC flowing, as a real command session would
                try:
                    sock.sendto(rc_override(rc_frame(POWER, {0: 1620}),
                                            tgt_sys, tgt_comp, seqn), dest)
                    seqn = (seqn + 1) & 0xFF
                except OSError:
                    pass
                if select.select([sock], [], [], 0.025)[0]:
                    try:
                        data, _ = sock.recvfrom(4096)
                    except OSError:
                        continue
                    h = mav_hdr(data)
                    if not h:
                        continue
                    pl = data[6:6 + h["ln"]] if h["ver"] == 1 else data[10:10 + h["ln"]]
                    if h["msgid"] == 77 and len(pl) >= 3:
                        c, res = struct.unpack_from("<HB", pl, 0)
                        acks.append(f"{c}->{MAV_RESULT.get(res, res)}")
                        say(f"      COMMAND_ACK {c} -> {MAV_RESULT.get(res, res)}")
                    elif h["msgid"] == 253 and len(pl) >= 2:
                        t = pl[1:51].split(b"\x00")[0].decode("utf-8", "replace")
                        if t and t not in texts:
                            texts.append(t)
                            say(f"      says: {t}")
                    elif h["msgid"] == 0 and len(pl) >= 7 and pl[6] & 0x80:
                        armed = True
                        say("      *** ARMED ***")
            # stop, neutral, disarm
            for _ in range(10):
                try:
                    sock.sendto(rc_override(rc_frame(POWER), tgt_sys, tgt_comp, seqn), dest)
                    seqn = (seqn + 1) & 0xFF
                except OSError:
                    pass
                time.sleep(0.02)
            try:
                sock.sendto(arm_disarm(False, tgt_sys, tgt_comp, seqn), dest)
            except OSError:
                pass
            hb.stop()
            verdict = ("ARMED" if armed else
                       ("ACK " + ",".join(acks)) if acks else
                       ("only: " + "; ".join(texts[:2])) if texts else "silence")
            say(f"  ####  DESTINATION {n} DONE — {verdict}")
            report.append((f"{n}. send to {dh}:{dp}", verdict))

    stop_poll.set()
    if tcp:
        time.sleep(1.0)
        subprocess.run(["sudo", "-n", "kill", str(tcp.pid)], capture_output=True)
        tcp.wait(timeout=5)
        head("E  what tcpdump saw")
        try:
            lines = open(cap).read().splitlines()
        except Exception:
            lines = []
        pairs = {}
        for ln in lines:
            f = ln.split()
            if len(f) > 4 and f[1] == "IP":
                pairs[f"{f[2]} > {f[4].rstrip(':')}"] = pairs.get(
                    f"{f[2]} > {f[4].rstrip(':')}", 0) + 1
        for k, v in sorted(pairs.items(), key=lambda kv: -kv[1])[:15]:
            say(f"  {v:6d}  {k}")
        say(f"  {len(lines)} packets total, full capture in {cap}")
        report.append(("tcpdump", f"{len(lines)} UDP packets, "
                                  f"{len(pairs)} distinct src>dst"))

    head("SUMMARY")
    for k, v in report:
        say(f"  {k:<28} {v}")
    say("")
    say("If a thruster ran, the DESTINATION number printed just before it is")
    say("the answer. With the firewall down the ACK line should now name it")
    say("without needing your ear at all.")
    say("")
    say("Read it like this:")
    say("  - tcpdump silent from .88      -> the ROV emits nothing; the fault")
    say("                                    is upstream of MAVLink entirely")
    say("  - tcpdump busy, sockets silent -> we listen on the wrong port")
    say("  - any ACK from one destination -> that is the address to use")
    say("  - ACKs but DENIED              -> a pre-arm condition, read `says:`")
    log("   diagnose: " + "; ".join(f"{k}={v}" for k, v in report))
    return 0

def find_link(seconds_each=8):
    """Which address does the drone actually LISTEN on?

    Downstream works: telemetry, battery and status text all arrive. Upstream
    has never once been acknowledged -- four runs, zero COMMAND_ACK, and the
    drone repeating "MYGCS: 255, heartbeat lost" through a session where we
    beat at 1 Hz for forty seconds without a break. That warning fires when a
    vehicle has NEVER seen its GCS as well as when it loses one, so the
    simplest reading is that nothing we send is getting to the flight
    controller.

    We reply to the source of the telemetry, which is what the app's transport
    does -- it sends to the address and port of the last packet in.
    But the buoy is a relay, and a relay is free to forward one way only. The
    netcode handshake announces 192.168.1.88:1000 -- the ROV and a port we
    have never sent a byte to.

    So: hold one link open, and cycle the destination. Everything else stays
    identical. Whichever destination stops the warning, or draws a COMMAND_ACK,
    is the answer. If none does, the problem is not the address."""
    import select, struct
    try:
        sock = bind_udp(MAVLINK_PORT)
    except OSError as e:
        say(f"Cannot listen on UDP {MAVLINK_PORT}: {e}")
        for line in port_holder(MAVLINK_PORT).splitlines():
            say("   " + line)
        return 1
    sock.settimeout(1.0)

    say(f"waiting for telemetry on UDP {MAVLINK_PORT} to learn the peer ...")
    peer, tgt_sys, tgt_comp = None, 1, 1
    deadline = time.time() + 12
    while peer is None and time.time() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        peer = addr
        for msgid, payload in mav_frames(data):
            if msgid == 0 and len(payload) >= 7:
                tgt_sys, tgt_comp = data[3], data[4]
    if peer is None:
        say("Nothing arrived; cannot even guess. Is the drone powered?")
        return 1

    rov = "192.168.1.88"
    candidates = [
        (peer[0], peer[1],   "the telemetry source, what we have always used"),
        (rov,     14550,     "the ROV directly, standard MAVLink port"),
        (rov,     1000,      "the ROV at the port the handshake announces"),
        (peer[0], 1000,      "the buoy at that same port"),
    ]
    claim_control()
    say(f"peer is {peer[0]}:{peer[1]}, target {tgt_sys}/{tgt_comp}")
    say(f"trying {len(candidates)} destinations, {seconds_each}s each.")
    say("Watch for COMMAND_ACK, or for the heartbeat warning to stop.")

    results = []
    for host, port, why in candidates:
        dest = (host, port)
        say("")
        say(f"=== {host}:{port} — {why}")
        acks, warns, seq = [], 0, 0
        hb = Heartbeat(sock, dest).start()
        time.sleep(2.0)
        try:
            sock.sendto(arm_disarm(True, tgt_sys, tgt_comp, seq), dest); seq += 1
        except OSError as e:
            say(f"    cannot send there: {e}")
            hb.stop()
            results.append((host, port, "unreachable"))
            continue
        end = time.time() + seconds_each
        while time.time() < end:
            if not select.select([sock], [], [], 0.2)[0]:
                continue
            try:
                data, _ = sock.recvfrom(4096)
            except OSError:
                continue
            for msgid, payload in mav_frames(data):
                if msgid == 77 and len(payload) >= 3:
                    cmd, res = struct.unpack_from("<HB", payload, 0)
                    acks.append((cmd, MAV_RESULT.get(res, res)))
                    say(f"    COMMAND_ACK cmd {cmd} -> {MAV_RESULT.get(res, res)}")
                elif msgid == 253 and len(payload) >= 2:
                    txt = payload[1:51].split(b"\x00")[0].decode("utf-8", "replace")
                    if "heartbeat lost" in txt:
                        warns += 1
                    elif txt:
                        say(f"    drone says {txt}")
                elif msgid == 0 and len(payload) >= 7 and payload[6] & 0x80:
                    say("    *** ARMED ***")
                    acks.append((400, "ARMED"))
        try:
            sock.sendto(arm_disarm(False, tgt_sys, tgt_comp, seq), dest)
        except OSError:
            pass
        hb.stop()
        verdict = ("ACK: " + ", ".join(f"{c}->{r}" for c, r in acks)) if acks \
                  else (f"silence, {warns} heartbeat-lost warnings" if warns
                        else "silence, and no warnings either")
        say(f"    {verdict}")
        results.append((host, port, verdict))

    say("")
    say("summary — the destination that answers is the one to use:")
    for host, port, verdict in results:
        say(f"  {host}:{port:<6} {verdict}")
    log("   findlink: " + "; ".join(f"{h}:{p} {v}" for h, p, v in results))
    return 0

def lights_only(seconds=4.0):
    """Set the headlights and exit. No daemon, no second terminal.

    Channel 5 rides on every RC frame, so setting it means sending frames for
    a moment. It does NOT arm and it holds every stick at neutral, so nothing
    can move: the only thing that changes is the light."""
    try:
        sock = bind_udp(MAVLINK_PORT)
    except OSError as e:
        say(f"Cannot bind UDP {MAVLINK_PORT}: {e}")
        for line in port_holder(MAVLINK_PORT).splitlines():
            say("   " + line)
        return 1
    sock.settimeout(1.0)
    claim_control()

    say(f"waiting for the drone on UDP {MAVLINK_PORT} ...")
    peer, tgt_sys, tgt_comp = None, 0, 0
    t0 = time.time()
    while peer is None and time.time() - t0 < 12:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        h = mav_hdr(data)
        if not h:
            continue
        peer = addr
        if h["msgid"] == 0:
            tgt_sys, tgt_comp = h["sysid"], h["compid"]
    if peer is None:
        say("Nothing arrived. Is the drone powered and the firewall down?")
        return 1

    hb = Heartbeat(sock, peer).start()
    say(f"lights -> {LIGHTS} ({'off' if LIGHTS <= 30 else 'on'}), "
        f"holding {seconds:g}s. Nothing is armed; nothing will move.")
    frame = rc_frame(0)
    dbg("frame " + " ".join(f"ch{i}={v}" for i, v in enumerate(frame)))
    seq, end = 0, time.time() + seconds
    while time.time() < end:
        try:
            sock.sendto(rc_override(frame, tgt_sys, tgt_comp, seq), peer)
        except OSError:
            pass
        seq = (seq + 1) & 0xFF
        time.sleep(0.025)
    hb.stop()
    say("done.")
    return 0

def control_drive(key, seconds, power_pct):
    """Drive one axis for a fixed time with no keyboard, then stop.

    This exists so the thrusters can be tested from a script. --control on its
    own needs a tty, which means the only unattended coverage was --selftest,
    and --selftest deliberately moves nothing -- so nothing ever proved a
    thruster responds.

    Always: arm, hold the input, then neutral x20 and disarm. The arm matters.
    The app gates its joysticks on the armed state (CameraControlActivity.java
    :461,476 only forward the stick when f16884r.b() is true), and that flag is
    set by the same COMMAND_LONG 400 this sends -- it is the "unlock" button in
    the app UI, not a separate thing."""
    import struct
    keys = [k.strip() for k in key.split(",") if k.strip()]
    bad = [k for k in keys if k not in DRIVE_KEYS]
    if bad or not keys:
        say(f"--control {key}: {', '.join(bad) or 'nothing'} is not a key.")
        say("One of, or a comma-separated list of: " + ", ".join(DRIVE_KEYS))
        return 2
    span = int(400 * max(1, min(100, power_pct)) / 100.0)

    def pwm_for(k):
        slot, sign = DRIVE_KEYS[k]
        if slot is None:
            return None, PWM_NEUTRAL
        return slot, max(PWM_MIN, min(PWM_MAX, PWM_NEUTRAL + sign * span))

    try:
        sock = bind_udp(MAVLINK_PORT)
    except OSError as e:
        say(f"Cannot listen on UDP {MAVLINK_PORT}: {e}")
        for line in port_holder(MAVLINK_PORT).splitlines():
            say("   " + line)
        return 1
    sock.settimeout(1.0)

    say(f"control: {len(keys)} input(s) — {', '.join(keys)} — "
        f"{seconds:g}s each at {power_pct}% power")

    # The link learns its peer from the first packet in, so wait for one.
    peer, tgt_sys, tgt_comp, seen = None, 1, 1, 0
    deadline = time.time() + min(12, max(4, seconds))
    while peer is None and time.time() < deadline:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        peer, seen = addr, seen + 1
        for msgid, payload in mav_frames(data):
            if msgid == 0 and len(payload) >= 9:
                tgt_sys, tgt_comp = data[3], data[4]
    if peer is None:
        say(f"  FAILED: nothing arrived on UDP {MAVLINK_PORT}, so there is no")
        say("  address to send to. Nothing was transmitted.")
        log(f"   control drive {key}: no peer")
        return 1
    dbg(f"peer {peer}, target {tgt_sys}/{tgt_comp}")

    seq, sent = 0, 0
    cur = [None, PWM_NEUTRAL]          # [slot, pwm] the loop is holding now
    def tx(frame_pwm=None):
        nonlocal seq, sent
        slot = cur[0]
        val = cur[1] if frame_pwm is None else frame_pwm
        over = {} if slot is None else {slot: val}
        frame = rc_frame(power_pct, over)
        sock.sendto(rc_override(frame, tgt_sys, tgt_comp, seq), peer)
        seq = (seq + 1) & 0xFF
        sent += 1
    dbg("frame " + " ".join(f"ch{i}={v}" for i, v in enumerate(rc_frame(power_pct))))

    # Hold the control role before sending anything. The app treats this as a
    # precondition, not an option, and retries until it succeeds.
    claim_control()

    # The heartbeat has to be running BEFORE the arm, not alongside it: the
    # firmware has to already consider this GCS present when the command
    # arrives. The app has been beating since it connected, so give it a
    # couple of beats here before asking for anything.
    hb = Heartbeat(sock, peer).start()
    say("  GCS heartbeat running at 1 Hz; waiting 2s before arming")
    time.sleep(2.0)

    try:
        # MANUAL first. The modes are ROV_MANUAL(19), ROV_STABILIZE(0) and
        # ROV_DEPTH_HOLD(2), and the app sends SET_MODE with base_mode 1
        # (CUSTOM_MODE_ENABLED). Whether the drone insists on a mode before it
        # will arm is a guess; sending it costs one packet.
        sock.sendto(set_mode(19, tgt_sys, seq), peer)
        seq = (seq + 1) & 0xFF
        dbg("SET_MODE custom_mode=19 (ROV_MANUAL), base_mode=1")
        time.sleep(0.3)

        sock.sendto(arm_disarm(True, tgt_sys, tgt_comp, seq), peer)
        seq = (seq + 1) & 0xFF
        say("  armed (COMMAND_LONG 400 param1=1.0) — the app's unlock button")
        time.sleep(0.3)

        # 40 Hz, as the app does: it schedules the send every 25ms.
        # The previous version read with a 1s socket timeout inside this loop
        # and so managed 10 Hz -- the 2026-08-24 log shows "40 RC frames" over
        # four seconds. select() with a zero timeout keeps the rate honest.
        #
        # Every key runs inside THIS one loop, on one socket, with one
        # heartbeat and one arm. That is the point: nine separate processes
        # each beating for seven seconds guaranteed a GCS failsafe in the gap
        # between them, and the drone said so -- "MYGCS: 255, heartbeat lost"
        # on 2026-08-24. A vehicle in GCS failsafe will not arm.
        import select
        end = time.time() + (seconds + GAP) * len(keys) + 5
        last = 0.0
        ki, kend = -1, 0.0
        while time.time() < end:
            now = time.time()
            if now >= kend and ki + 1 < len(keys):
                # A gap of neutral between inputs, so two adjacent axes cannot
                # blur into one and you can tell which motor was which.
                if ki >= 0 and GAP > 0:
                    cur[0], cur[1] = None, PWM_NEUTRAL
                    say(f"      neutral — {GAP:g}s gap")
                    g_end = time.time() + GAP
                    while time.time() < g_end:
                        if now - last >= 0.025:
                            tx()
                            last = time.time()
                        time.sleep(0.01)
                    now = time.time()
                ki += 1
                k = keys[ki]
                cur[0], cur[1] = pwm_for(k)
                kend = now + seconds
                label = "arm only, nothing should move" if cur[0] is None else \
                        f"slot {cur[0]} at {cur[1]} ({AXES[cur[0]][0].strip()})"
                say("")
                say(f"  >>> {k.upper():<5} {label}")
                if cur[0] is not None:
                    say(f"        RUNNING {seconds:g}s — WATCH WHICH MOTOR")
            if ki + 1 >= len(keys) and now >= kend:
                break
            if now - last >= 0.025:
                tx()
                last = now
            if select.select([sock], [], [], 0.002)[0]:
                try:
                    data, _ = sock.recvfrom(4096)
                except OSError:
                    continue
                for msgid, payload in mav_frames(data):
                    if msgid == 74 and len(payload) >= 20:
                        d = abs(struct.unpack_from("<f", payload, 8)[0])
                        print(f"  holding {cur[1]}   depth {d:5.2f}m   ",
                              end="\r", flush=True)
                    elif msgid == 77 and len(payload) >= 3:
                        # COMMAND_ACK: command uint16, result uint8. This is
                        # the drone saying in so many words why it refused.
                        cmd, res = struct.unpack_from("<HB", payload, 0)
                        say(f"  COMMAND_ACK cmd {cmd} -> {MAV_RESULT.get(res, res)}")
                        log(f"   COMMAND_ACK cmd={cmd} result={res}")
                    elif msgid == 253 and len(payload) >= 2:
                        # STATUSTEXT: severity uint8 then 50 bytes of text.
                        # ArduPilot puts its "PreArm: ..." refusals here, which
                        # is the most direct answer we can get.
                        sev = payload[0]
                        txt = payload[1:51].split(b"\x00")[0].decode("utf-8", "replace")
                        if txt:
                            say(f"  drone says [{SEVERITY.get(sev, sev)}] {txt}")
                            log(f"   STATUSTEXT sev={sev} {txt}")
                    elif msgid == 0 and len(payload) >= 7:
                        # base_mode bit 128 is SAFETY_ARMED. The app reads
                        # exactly this, so we can finally
                        # say whether the drone agreed to arm. Offset 6:
                        # HEARTBEAT packs custom_mode as a uint32 first, then
                        # type, autopilot, base_mode.
                        armed = bool(payload[6] & 0x80)
                        if armed != getattr(tx, "_armed", None):
                            tx._armed = armed
                            say(f"  drone reports {'ARMED' if armed else 'DISARMED'}")
    except KeyboardInterrupt:
        say("  interrupted")
    finally:
        print()
        cur[0] = None
        for _ in range(20):
            tx(PWM_NEUTRAL)
            time.sleep(0.025)
        sock.sendto(arm_disarm(False, tgt_sys, tgt_comp, seq), peer)
        say(f"  neutral x20 then disarm. {sent} RC frames, {hb.sent} heartbeats.")
        log(f"   control drive {key}: sent={sent} "
            f"heartbeats={hb.sent} armed={getattr(tx, '_armed', None)} peer={peer}")
        hb.stop()
    say("  Did anything move? Write down what this key actually did.")
    return 0

def control_loop(power_pct):
    import select, struct, termios, tty
    # Needs a real terminal for key capture. DoryTest.sh runs every mode with
    # stdin closed, so say this plainly instead of throwing a traceback.
    if not sys.stdin.isatty():
        say("--control needs a terminal: it reads the keyboard directly.")
        say("Run it by hand, not from a script or with stdin redirected.")
        return 2
    span = int(400 * max(1, min(100, power_pct)) / 100.0)
    hb = None

    try:
        sock = bind_udp(MAVLINK_PORT)
    except OSError as e:
        say(f"Cannot listen on UDP {MAVLINK_PORT}: {e}")
        for line in port_holder(MAVLINK_PORT).splitlines():
            say("   " + line)
        return 1
    sock.settimeout(0)

    say("")
    say("  UNVERIFIED AXES. Which key moves which way is a guess — the app")
    say("  never records it. Do this in a bucket, tether in hand, first.")
    say("")
    for slot, (label, keys) in AXES.items():
        say(f"    {keys:<16} slot {slot}  {label}")
    say("    space            all neutral, immediately")
    say("    a / d            arm / disarm")
    say("    + / -            power (now {}%)".format(power_pct))
    say("    x or ctrl-C      neutral, disarm, quit")
    say("")
    say(f"  waiting for the drone on UDP {MAVLINK_PORT} (sending nothing yet) ...")

    chans = {slot: PWM_NEUTRAL for slot in AXES}
    touched = {slot: 0.0 for slot in AXES}
    peer, tgt_sys, tgt_comp, seq, armed = None, 1, 1, 0, False
    depth = batt = None
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sent = 0
    try:
        tty.setcbreak(fd)
        last_tx = 0.0
        while True:
            r, _, _ = select.select([fd, sock], [], [], 0.02)

            if sock in r:
                try:
                    data, addr = sock.recvfrom(4096)
                except OSError:
                    data = None
                if data:
                    if peer is None:
                        peer = addr
                        say(f"  drone at {addr[0]}:{addr[1]} — controls live")
                        dbg(f"learned peer {addr}")
                        if hb is None:
                            hb = Heartbeat(sock, peer).start()
                    for msgid, payload in mav_frames(data):
                        if msgid == 0 and len(payload) >= 9:      # HEARTBEAT
                            tgt_sys, tgt_comp = data[3], data[4]
                        elif msgid == 74 and len(payload) >= 20:  # VFR_HUD
                            depth = abs(struct.unpack_from("<f", payload, 8)[0])
                        elif msgid == 147 and len(payload) >= 36: # BATTERY_STATUS
                            rem = struct.unpack_from("<b", payload, 35)[0]
                            batt = 0.0 if rem <= 15 else ((rem - 15) / 85.0) * 100.0

            now = time.time()
            if fd in r:
                ch = os.read(fd, 3).decode("utf-8", "replace")
                if ch in ("x", "\x03"):
                    break
                elif ch == " ":
                    for k in chans: chans[k] = PWM_NEUTRAL
                elif ch == "a":
                    if peer:
                        sock.sendto(arm_disarm(True, tgt_sys, tgt_comp, seq), peer)
                        seq = (seq + 1) & 0xFF; armed = True
                        dbg(f"ARM sent to {tgt_sys}/{tgt_comp}")
                elif ch == "d":
                    if peer:
                        sock.sendto(arm_disarm(False, tgt_sys, tgt_comp, seq), peer)
                        seq = (seq + 1) & 0xFF; armed = False
                        dbg("DISARM sent")
                elif ch == "+":
                    power_pct = min(100, power_pct + 10); span = int(400 * power_pct / 100.0)
                elif ch == "-":
                    power_pct = max(10, power_pct - 10); span = int(400 * power_pct / 100.0)
                else:
                    hit = None
                    # Arrows behave like a stick -- pushing away is forward.
                    # w/s are vertical, which is the one people expect to be
                    # "up". The typed commands use words instead, so there is
                    # no ambiguity there.
                    if ch == "\x1b[A":   hit = (4, +1)   # forward
                    elif ch == "\x1b[B": hit = (4, -1)   # back
                    elif ch == "\x1b[C": hit = (3, +1)   # yaw right
                    elif ch == "\x1b[D": hit = (3, -1)   # yaw left
                    elif ch == "w":       hit = (2, +1)   # UP, towards the surface
                    elif ch == "s":       hit = (2, -1)   # DOWN, deeper
                    elif ch == "q":       hit = (0, -1)   # roll left
                    elif ch == "e":       hit = (0, +1)   # roll right
                    elif ch == "r":       hit = (1, +1)   # pitch up
                    elif ch == "f":       hit = (1, -1)   # pitch down
                    if hit:
                        slot, sign = hit
                        chans[slot] = max(PWM_MIN, min(PWM_MAX, PWM_NEUTRAL + sign * span))
                        touched[slot] = now
                        dbg(f"key {ch!r} -> slot {slot} pwm {chans[slot]}")

            # Dead man: anything not re-pressed within HOLD_MS returns to centre.
            for slot in chans:
                if chans[slot] != PWM_NEUTRAL and (now - touched[slot]) * 1000 > HOLD_MS:
                    chans[slot] = PWM_NEUTRAL

            if peer and now - last_tx >= 0.025:      # 40 Hz, as the app does
                frame = rc_frame(power_pct, chans)
                sock.sendto(rc_override(frame, tgt_sys, tgt_comp, seq), peer)
                seq = (seq + 1) & 0xFF; sent += 1; last_tx = now

            live = "  ".join(f"s{slot}:{chans[slot]}" for slot in sorted(chans))
            extra = ""
            if depth is not None: extra += f"  depth {depth:5.2f}m"
            if batt  is not None: extra += f"  batt {batt:3.0f}%"
            print(f"  [{'ARMED' if armed else 'safe '}] pwr {power_pct:3d}%  {live}{extra}   ",
                  end="\r", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print()
        # Neutral, repeatedly, then disarm. Never leave a thruster latched.
        if peer:
            for _ in range(20):
                sock.sendto(rc_override(rc_frame(power_pct), tgt_sys, tgt_comp, seq), peer)
                seq = (seq + 1) & 0xFF
                time.sleep(0.025)
            sock.sendto(arm_disarm(False, tgt_sys, tgt_comp, seq), peer)
            say("  sent neutral x20 and a disarm")
        else:
            say(f"  nothing ever arrived on UDP {MAVLINK_PORT}; nothing was sent")
        log(f"   control: {sent} RC frames sent, peer={peer}, target={tgt_sys}/{tgt_comp}")
    return 0

def telemetry_loop(stop=None, quiet_start=False):
    """Print a live one-line readout until ctrl-C, `stop`, or --timeout."""
    give_up = time.time() + TIMEOUT if TIMEOUT else None
    import struct
    try:
        sock = bind_udp(MAVLINK_PORT)
    except OSError as e:
        say(f"Cannot listen on UDP {MAVLINK_PORT}: {e}")
        who = port_holder(MAVLINK_PORT)
        if who:
            say("Something else already has that port:")
            for line in who.splitlines():
                say("   " + line)
            say(f"Free it with:  lsof -tnP -iUDP:{MAVLINK_PORT} | xargs kill -9")
        else:
            say("Could not determine what holds it; try: lsof -nP -iUDP:14550")
        return 1
    sock.settimeout(1.0)
    if not quiet_start:
        say(f"listening for telemetry on UDP {MAVLINK_PORT} — ctrl-C to stop")
    dbg(f"telemetry bound 0.0.0.0:{MAVLINK_PORT}, sending nothing")

    state, buf, seen, first = {}, b"", 0, time.time()
    hist, last_dbg = {}, 0.0
    try:
        while stop is None or not stop.is_set():
            if give_up and time.time() >= give_up:
                dbg(f"telemetry: --timeout {TIMEOUT:g}s reached")
                break
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                if seen == 0 and time.time() - first > 12:
                    print()
                    say(f"No telemetry on UDP {MAVLINK_PORT} in 12s.")
                    say("The drone has to be powered and linked to the buoy.")
                    return 1
                continue
            buf = b"".join([buf, data])
            for msgid, payload in mav_frames(buf):
                seen += 1
                hist[msgid] = hist.get(msgid, 0) + 1
                if msgid == 74 and len(payload) >= 20:      # VFR_HUD
                    alt, = struct.unpack_from("<f", payload, 8)
                    heading, = struct.unpack_from("<h", payload, 16)
                    dbg(f"VFR_HUD raw alt={alt:+.3f} m -> depth {abs(alt):.2f} m, hdg {heading}")
                    state["depth"] = abs(alt)
                    state["raw_alt"] = alt
                    state["heading"] = heading
                elif msgid == 147 and len(payload) >= 36:   # BATTERY_STATUS
                    rem = struct.unpack_from("<b", payload, 35)[0]
                    cell, = struct.unpack_from("<H", payload, 10)
                    bid = payload[32]
                    state["raw_batt"] = rem
                    dbg(f"BATTERY_STATUS id={bid} raw_remaining={rem}% "
                        f"cell0={cell}mV -> shown {0.0 if rem <= 15 else ((rem-15)/85.0)*100:.0f}%")
                    # The app rescales so firmware 15% reads as 0%
                    # match it so the number agrees with the
                    # vendor app rather than quietly disagreeing.
                    state[f"batt{bid}"] = 0.0 if rem <= 15 else ((rem - 15) / 85.0) * 100.0
                    if cell not in (0, 0xFFFF):
                        state["volts"] = cell / 1000.0
            buf = b""
            if DEBUG and time.time() - last_dbg > 5:
                last_dbg = time.time()
                dbg(f"peer={addr[0]} messages so far={seen} by id={hist}")
            if "depth" in state or any(k.startswith("batt") for k in state):
                bits = []
                if "depth" in state:
                    bits.append(f"depth {state['depth']:6.2f} m")
                for k in sorted(k for k in state if k.startswith("batt")):
                    bits.append(f"batt{k[4:]} {state[k]:3.0f}%")
                if "volts" in state:
                    bits.append(f"{state['volts']:.2f} V")
                if "heading" in state:
                    bits.append(f"hdg {state['heading']:3d}\u00b0")
                print("  " + "   ".join(bits) + "        ", end="\r", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        print()
        log(f"   telemetry: {seen} messages, last state {state}")
    return 0

PAGE = b"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Chasing Dory</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root{color-scheme:dark;--bg:#0b0f14;--fg:#e6edf3;--dim:#8b98a5;--line:#1e2a36}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.5 ui-sans-serif,-apple-system,system-ui,sans-serif;
       display:flex;flex-direction:column;min-height:100vh}
  header{padding:10px 16px;border-bottom:1px solid var(--line);
         display:flex;gap:12px;align-items:baseline}
  h1{margin:0;font-size:14px;font-weight:600;letter-spacing:.01em}
  .dim{color:var(--dim);font-size:12px}
  main{flex:1;display:flex;align-items:center;justify-content:center;padding:16px}
  img{max-width:100%;max-height:calc(100vh - 130px);border-radius:8px;
      background:#000;display:block}
  footer{padding:10px 16px;border-top:1px solid var(--line);color:var(--dim);
         font-size:12px}
  code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--fg)}
</style></head><body>
<header><h1>Chasing Dory</h1><span class="dim">live &middot; UDP 5600</span></header>
<main><img src="/stream.mjpg" alt="live camera"></main>
<footer>Close this tab or press ctrl-C in the terminal to stop.</footer>
</body></html>"""

def find_vlc():
    """VLC is the first choice: it reads the SDP natively, so nothing has to be
    installed and nothing is re-encoded to show the picture."""
    from_path = shutil.which("vlc") or shutil.which("VLC")
    if from_path:
        return from_path
    if IS_WIN:
        # VLC is not on PATH after a default install on Windows either.
        cands = []
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(var)
            if base:
                cands.append(os.path.join(base, "VideoLAN", "VLC", "vlc.exe"))
        cands.append(shutil.which("vlc.exe") or "")
    else:
        cands = ["/Applications/VLC.app/Contents/MacOS/VLC",
                 os.path.expanduser("~/Applications/VLC.app/Contents/MacOS/VLC"),
                 "/usr/bin/vlc", "/usr/local/bin/vlc", "/snap/bin/vlc"]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None

def play_in_vlc(vlc, source, outfile):
    """`source` is a whole SDP behind an sdp:// prefix, not a path. VLC's
    `sdp` access module takes the description inline (verified: it still
    reports `RTP subsession 'video/H264'` and hands off to VideoToolbox), so
    nothing here depends on a file existing at the water."""
    # No --no-one-instance here. That option does not exist in the macOS build
    # -- VLC 3.0.20 answers "unknown option or missing mandatory argument" and
    # exits 1 before it opens anything, which is exactly what happened on
    # 2026-08-23: VLC was already running, nothing appeared, and the real cause
    # was our own command line. Running the binary out of the bundle does start
    # its own process even with another VLC open -- checked, lsof showed the
    # new one holding UDP 5600. Whether a *window* then comes to the front is
    # still unverified: every test here ran headless or had no decodable video,
    # so no window ever appeared to judge. Real video will settle it.
    #
    # --macosx-control-itunes=0 because VLC's macOS default for that setting
    # is 1, "Pause iTunes / Spotify": starting playback pauses whatever music
    # player you have running. A drone script has no business doing that. (It
    # was also my first guess at a security prompt Thijmen saw on 2026-08-23 --
    # wrongly: the logs show no Automation prompt and no firewall alert for
    # Spotify. The flag is worth having on its own merits, not as that fix.)
    cmd = [vlc, "--no-video-title-show", "--network-caching=200"]
    if IS_MAC:
        # macOS only. On Windows this flag does not exist and VLC exits 1 on
        # an unknown option -- the same failure --no-one-instance caused on
        # macOS, in mirror image.
        cmd.append("--macosx-control-itunes=0")
    else:
        # This one DOES exist off macOS, and matters for the same reason:
        # without it a running VLC swallows the stream instead of opening a
        # window for it.
        cmd.append("--no-one-instance")
    if outfile:
        # duplicate{} sends the same stream two ways at once: the window and
        # the file. mux follows the extension you asked for.
        mux = "ts" if os.path.splitext(outfile)[1].lower() in (".ts", ".mpg", ".mpeg") else "mp4"
        cmd.append("--sout=#duplicate{dst=display,dst=std{access=file,mux=%s,dst=%s}}"
                   % (mux, os.path.abspath(outfile)))
    cmd.append(source)
    # The SDP is multi-line, so flatten it for the log -- a command line that
    # wraps over seven lines is unreadable in _run.txt and cannot be pasted
    # back into a shell to reproduce.
    shown = " ".join(a.replace("\n", "\\n") for a in cmd)
    log("   " + shown)
    dbg("player: " + shown)
    if outfile:
        say(f"playing in VLC and recording to {outfile} — quit VLC to stop")
    else:
        say("playing in VLC — quit VLC to stop")
    try:
        return subprocess.run(cmd).returncode
    except KeyboardInterrupt:
        return 0

def serve_in_browser(sdp_path, outfile):
    """A browser cannot open RTP over UDP, so ffmpeg turns the stream into
    MJPEG and this serves it as multipart/x-mixed-replace -- which every
    browser renders in a plain <img>, with no JavaScript and no CDN. That
    matters here: the buoy's Wi-Fi has no internet, so nothing can be fetched."""
    import http.server, threading
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        say("The drone IS streaming, but nothing here can show it.")
        say("Install either:  brew install --cask vlc   (preferred)")
        say("            or:  brew install ffmpeg       (for the browser view)")
        say(f"The stream description is in {sdp_path}.")
        return 1

    latest = {"jpeg": None, "n": 0}
    cond   = threading.Condition()
    stop   = threading.Event()

    cmd = [ffmpeg, "-loglevel", "warning",
           "-protocol_whitelist", "file,rtp,udp",
           "-fflags", "nobuffer", "-flags", "low_delay",
           "-analyzeduration", "2000000", "-probesize", "2000000",
           "-i", sdp_path, "-an", "-f", "mjpeg", "-q:v", "6", "-"]
    if outfile:
        # A second output off the same input: the browser gets MJPEG, the file
        # gets the stream in its own right.
        cmd += ["-y", outfile]
    log("   " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=LOG)

    def reader():
        """ffmpeg writes JPEGs back to back; split them on SOI/EOI and keep
        only the newest, so a slow tab falls behind in quality, never in time."""
        buf = b""
        while not stop.is_set():
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                i = buf.find(b"\xff\xd8")
                j = buf.find(b"\xff\xd9", i + 2) if i >= 0 else -1
                if i < 0 or j < 0:
                    break
                frame, buf = buf[i:j + 2], buf[j + 2:]
                with cond:
                    latest["jpeg"] = frame
                    latest["n"] += 1
                    cond.notify_all()
        with cond:
            stop.set(); cond.notify_all()

    threading.Thread(target=reader, daemon=True).start()

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        def log_message(self, fmt, *args):
            log("   http " + (fmt % args))
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(PAGE)))
                self.end_headers()
                self.wfile.write(PAGE)
                return
            if self.path != "/stream.mjpg":
                self.send_error(404); return
            self.send_response(200)
            self.send_header("Cache-Control", "no-store, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type",
                             "multipart/x-mixed-replace; boundary=dory")
            self.end_headers()
            seen = 0
            while not stop.is_set():
                with cond:
                    cond.wait_for(lambda: latest["n"] != seen or stop.is_set(),
                                  timeout=5)
                    if stop.is_set() or latest["n"] == seen:
                        continue
                    seen, frame = latest["n"], latest["jpeg"]
                try:
                    self.wfile.write(b"--dory\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(b"Content-Length: %d\r\n\r\n" % len(frame))
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    break

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # Wait for a real frame before opening the tab, so the browser never
    # shows a broken image while ffmpeg is still working out the stream.
    with cond:
        cond.wait_for(lambda: latest["jpeg"] is not None or stop.is_set(),
                      timeout=15)
    if latest["jpeg"] is None:
        stop.set()
        proc.terminate()
        say("ffmpeg received the stream but produced no frames in 15s.")
        say(f"Its output is in {LOGPATH}.")
        say(f"To try by hand:  ffplay -protocol_whitelist file,rtp,udp -i {sdp_path}")
        return 1

    if outfile:
        say(f"recording to {outfile}")
    say(f"opening {url} in your browser — ctrl-C to stop")
    subprocess.run(["open", url], check=False)
    try:
        while proc.poll() is None and not stop.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        with cond:
            cond.notify_all()
        if proc.poll() is None:
            proc.terminate()
        srv.shutdown()
    say("stopped")
    return 0

def sdp_text(video_pt):
    """An SDP is unavoidable, but only because of one line. Payload types 96-127
    are *dynamic*: the number carries no meaning, and the mapping to a codec
    exists only out of band. VLC has an escape hatch for this and it is no use
    -- `--rtp-dynamic-pt` accepts exactly one value, `theora`. So rtp://@:5600
    on its own can never know the stream is H.264, and something has to say
    `a=rtpmap:96 H264/90000`.

    A *file* is a different question, and the answer there is no. See
    vlc_source(): the sdp:// scheme carries the same text inline."""
    return ("v=0\n"
            "o=- 0 0 IN IP4 127.0.0.1\n"
            "s=Chasing Dory\n"
            "c=IN IP4 0.0.0.0\n"
            "t=0 0\n"
            f"m=video {VIDEO_PORT} RTP/AVP {video_pt}\n"
            f"a=rtpmap:{video_pt} H264/90000\n")

def live_video():
    video_pt = sniff()
    if video_pt is None:
        return 1

    sdp = sdp_text(video_pt)
    if DEBUG:
        dbg("sdp:")
        for line in sdp.splitlines():
            dbg(f"    {line}")
    log("   sdp: " + sdp.replace("\n", " | "))

    # The player binds 5600 itself, so let go of it first -- otherwise it opens
    # the stream and then sits there receiving nothing.
    release_udp(VIDEO_PORT)

    # VLC first: it reads the SDP itself and needs nothing installed, and it
    # takes the whole thing inline, so there is no file to write, find, or
    # leave stale. The browser fallback is the one that needs a real path --
    # ffmpeg's demuxer wants a file it can open -- so that branch writes one.
    vlc = find_vlc()
    if vlc:
        return play_in_vlc(vlc, "sdp://" + sdp, LIVEFILE)

    sdp_path = os.path.join(os.path.dirname(LOGPATH), "dory-live.sdp")
    with open(sdp_path, "w") as f:
        f.write(sdp)
    log(f"   wrote {sdp_path} for ffmpeg")
    return serve_in_browser(sdp_path, LIVEFILE)

def run_live():
    """Video and telemetry are both pushed at us, so neither needs the HTTP
    host. Together, the readout runs beside the picture rather than instead
    of it -- depth while you are actually flying it."""
    if LIVE and TELEM:
        import threading
        stop = threading.Event()
        t = threading.Thread(target=telemetry_loop, args=(stop, True), daemon=True)
        t.start()
        try:
            return live_video()
        finally:
            stop.set()
            # Give the reader a moment to write its summary; a daemon thread
            # killed at exit never runs its finally, and the log would then
            # keep whatever the previous run left there.
            t.join(timeout=1.5)
    if LIVE:
        return live_video()
    return telemetry_loop()

# Video and telemetry need no host discovery -- and skipping it means they
# still work if the HTTP side is being odd.
if NETCODE_ONLY:
    sys.exit(netcode_only())

if LIGHTS_ONLY:
    session = open_session()
    try:
        sys.exit(lights_only(TIMEOUT or 4.0))
    finally:
        if session:
            session.stop()

if SENDCMD:
    sys.exit(send_cmd(SENDCMD))

if DAEMON:
    session = open_session()
    try:
        sys.exit(daemon())
    finally:
        if session:
            session.stop()

if DIAGNOSE:
    session = open_session()
    try:
        sys.exit(diagnose())
    finally:
        if session:
            session.stop()

if IDENTIFY:
    session = open_session()
    try:
        sys.exit(identify())
    finally:
        if session:
            session.stop()

if PROBE:
    try:
        bind_udp(MAVLINK_PORT)
    except OSError:
        pass
    session = open_session()
    try:
        sys.exit(probe())
    finally:
        if session:
            session.stop()

if FINDLINK:
    session = None
    try:
        bind_udp(MAVLINK_PORT)
    except OSError:
        pass
    session = open_session()
    try:
        sys.exit(find_link(int(TIMEOUT or 8)))
    finally:
        if session:
            session.stop()

def start_listening(video, mavlink):
    """Bind first, ask second. The buoy can start relaying the instant it
    accepts the session, and a datagram aimed at a port nothing is listening on
    is simply dropped -- so the order here is the whole point."""
    for port, kw in ((VIDEO_PORT if video else None, dict(rcvbuf=1048576, broadcast=True)),
                     (MAVLINK_PORT if mavlink else None, {})):
        if port is None:
            continue
        try:
            bind_udp(port, **kw)
        except OSError as e:
            # Not fatal here: the function that actually reads the port reports
            # it properly, with the name of whatever is holding it.
            dbg(f"could not pre-bind {port}: {e}")
    return open_session()

if CONTROL and not (RETRIEVE or REMOVE or LIST):
    session = start_listening(video=LIVE, mavlink=True)
    try:
        if SELFTEST:
            sys.exit(control_selftest())
        if CONTROL_KEY:
            sys.exit(control_drive(CONTROL_KEY, TIMEOUT or 3.0, POWER))
        if LIVE:
            threading.Thread(target=live_video, daemon=True).start()
            time.sleep(1)
        sys.exit(control_loop(POWER))
    finally:
        if session:
            session.stop()

if (LIVE or TELEM) and not (RETRIEVE or REMOVE or LIST):
    session = start_listening(video=LIVE, mavlink=TELEM)
    try:
        sys.exit(run_live())
    finally:
        if session:
            session.stop()

# ================================================================== HTTP ====
SSLCTX = ssl._create_unverified_context()

def request(url, method="GET", timeout=5):
    """-> (status, body). status 0 means the connection itself failed."""
    req = urllib.request.Request(url, method=method, headers={"Connection": "close"})
    t0 = time.time()
    dbg(f"{method} {url}  (timeout {timeout}s)")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSLCTX) as r:
            body = r.read()
            if r.url != url:
                body = f"[redirected to {r.url}] ".encode() + body
            dbg(f"  -> {r.status} {len(body)}B in {time.time()-t0:.2f}s"
                f" ct={r.headers.get('Content-Type','?')}")
            return r.status, body
    except urllib.error.HTTPError as e:
        body = e.read() or b""
        dbg(f"  -> HTTP {e.code} {len(body)}B in {time.time()-t0:.2f}s: {snippet(body, 60)}")
        return e.code, body
    except Exception as e:
        dbg(f"  -> failed in {time.time()-t0:.2f}s: {e}")
        return 0, str(e).encode()

def snippet(body, n=70):
    return body[:n].decode("utf-8", "replace").replace("\n", " ").strip()

def medias_from(body):
    """Every response shape this firmware family is known to return, or None."""
    try:
        d = json.loads(body)
    except Exception as e:
        dbg(f"  not JSON ({e}); {len(body)}B starting {snippet(body, 40)!r}")
        return None
    if isinstance(d, list):
        dbg(f"  shape: bare array, {len(d)} entries")
    elif isinstance(d, dict):
        dbg(f"  shape: object with keys {sorted(d.keys())}")
    items = d if isinstance(d, list) else None
    if items is None and isinstance(d, dict):
        for key in ("data", "result", "medias", "files", "list"):
            v = d.get(key)
            if isinstance(v, list):
                items = v; break
            if isinstance(v, dict):
                for k2 in ("medias", "files", "list"):
                    if isinstance(v.get(k2), list):
                        items = v[k2]; break
            if items is not None:
                break
    if items is None:
        dbg("  no list found under any known key -- not a media list")
        return None
    # An empty list is a real answer (card wiped). A list of things without
    # names is someone else's JSON, so do not mistake it for the camera.
    if items and not any(isinstance(i, dict) and i.get("name") for i in items):
        dbg(f"  rejected: {len(items)} entries but none carry a 'name'")
        return None
    dbg(f"  accepted: {len(items)} media entries")
    return items

# ------------------------------------------------------- candidate host order
# The app builds media URLs from i6.b.f37229v = "http://" + f37217t + "/" with
# the app's own default base URL is "192.168.1.1", so .1 goes first. .88 is the ROV
# base (f37247y) and only ever appears as .88:8082 in the live probe list
# only in the live probe list -- but it is cheap to try, so it is tried.
cands = []
def add(hp):
    if hp and hp not in cands:
        cands.append(hp)

add(os.environ.get("DORY_HOST"))
for hp in ("192.168.1.1", "192.168.1.88", "192.168.1.1:8082", "192.168.1.88:8082",
           "192.168.1.4", "192.168.1.4:8082"):
    add(hp)
add(os.environ.get("DORY_GW"))
for n in os.environ.get("DORY_NEIGHBOURS", "").split():
    if n != os.environ.get("DORY_MYIP"):
        add(n)

# ------------------------------------------------------ are we on the buoy? --
# The buoy hands out an address with no router option, so a default gateway
# means an ordinary internet network. The SSID would settle it, but macOS
# usually redacts it, so a gateway plus a non-Dory SSID only earns a fast
# check rather than an outright refusal.
ssid = (os.environ.get("DORY_SSID") or "").strip()
dbg(f"candidates: {cands}")
dbg(f"wifi gate: ssid={ssid!r} gateway={os.environ.get('DORY_GW')!r} "
    f"force={bool(os.environ.get('DORY_FORCE'))}")
if os.environ.get("DORY_GW") and not ssid.lower().startswith("dory") \
        and not os.environ.get("DORY_FORCE"):
    hit = None
    for hp in cands[:3]:
        st, body = request(f"http://{hp}/v1/medias", timeout=2)
        log(f"   gate {hp:<20} {st:<4} {snippet(body)}")
        if medias_from(body) is not None:
            hit = hp; break
    if hit is None:
        extra = f" and the SSID is {ssid}" if ssid and ssid != "<redacted>" else ""
        say(f"This is not the Dory Wi-Fi — there is a default gateway{extra},"
            " and nothing here serves the camera API.")
        say("Join Dory_xxxxx (password 12345678) and run it again."
            "  Pass --host to skip the check, or drop --checkwifi.")
        sys.exit(1)
    cands = [hit] + [c for c in cands if c != hit]

# ------------------------------------------------------------ find the camera
# Kept quiet on success: the table only reaches the screen if the first
# candidate was not the answer, which is exactly when it is worth reading.
base, items, alive, table = None, None, [], []
for hp in cands:
    st, body = request(f"http://{hp}/v1/medias", timeout=4)
    got = medias_from(body)
    line = f"   {'OK' if got is not None else '--'} {hp:<20} {st:<4} {snippet(body)}"
    table.append(line); log(line)
    if st:
        alive.append(hp)
    if got is not None:
        base, items = f"http://{hp}", got
        break

if DEBUG:
    print("\n".join(table))
elif base is not None and len(table) > 1:
    print("\n".join(table))

if base is None and os.environ.get("DORY_SCAN", "1") != "0" and os.environ.get("DORY_MYIP"):
    net = os.environ["DORY_MYIP"].rsplit(".", 1)[0]
    print("\n".join(table))
    say(f"== nothing known answered; sweeping {net}.0/24 ==")
    def try_host(i):
        hp = f"{net}.{i}"
        if hp in cands:
            return None
        st, body = request(f"http://{hp}/v1/medias", timeout=2)
        return (hp, st, body) if medias_from(body) is not None else None
    with ThreadPoolExecutor(max_workers=64) as pool:
        for res in pool.map(try_host, range(1, 255)):
            if res:
                hp, st, body = res
                say(f"   OK {hp:<20} {st:<4} {snippet(body)}")
                base, items = f"http://{hp}", medias_from(body)
                break

if base is None:
    paths = ("v1/versions", "v1/features", "v1/status", "v1/devinfo",
             "v1/tfcard/sdquery", "v1/manufacturer", "")
    if not alive:
        say("== nothing answered on any port — wrong network, or the buoy is asleep ==")
    else:
        say("== no host served /v1/medias — probing the rest of the API ==")
        def probe(job):
            hp, p = job
            st, body = request(f"http://{hp}/{p}", timeout=3)
            return f"   {hp:<20} /{p:<20} {st:<4} {snippet(body)}"
        with ThreadPoolExecutor(max_workers=16) as pool:
            for line in pool.map(probe, [(hp, p) for hp in alive for p in paths]):
                say(line)
    say("")
    say("Nothing on this network serves the media API.")
    say(f"Send over {LOGPATH} — it records every host tried and its answer.")
    sys.exit(1)

log(f"== camera at {base} ==")
dbg(f"camera base {base}; {len(items) if items else 0} raw entries")
items = [i for i in items if isinstance(i, dict) and i.get("name")]
vids  = sum(1 for i in items if (i.get("origin") or {}).get("duration"))

# ================================================================== --list ===
if LIST:
    say(f"{len(items)} item(s) on {base} — {vids} video")
    total = 0
    for it in items:
        size = int(it.get("size") or 0); total += size
        o = it.get("origin") or {}
        dur = f"{o['duration']}s" if o.get("duration") else "still"
        say(f"  {it['name']:<28} {size/1048576:8.1f} MB  {dur}")
    say(f"  {'':<28} {total/1048576:8.1f} MB total")
    if not (RETRIEVE or REMOVE):
        sys.exit(0)

# ================================================== the raw-filename rule ====
# The buoy does not percent-decode, so 20260717_133442(1).mp4 sent as
# ...%281%29.mp4 comes back 500. The app formats the name straight into the URL
# and so do we; the escaped form is only ever a fallback.
def name_urls(name):
    from urllib.parse import quote
    return [name] if quote(name) == name else [name, quote(name)]

# ================================================================ download ===
def fetch(name, out, resume, big):
    rc = 0
    for i, candidate in enumerate(name_urls(name)):
        cmd = ["curl", "-#", "-S", "-f"] if big else ["curl", "-sS", "-f"]
        cmd += ["--connect-timeout", "10"]
        if resume:
            cmd += ["-C", "-"]
        cmd += ["-o", out, f"{base}/v1/medias/{candidate}"]
        dbg("curl " + " ".join(cmd[1:]))
        rc = subprocess.run(cmd).returncode
        dbg(f"  curl rc={rc}"
            f" file={os.path.getsize(out) if os.path.exists(out) else 0}B")
        if rc == 0 or i == len(name_urls(name)) - 1:
            return rc
        log(f"   {name}: raw URL failed rc={rc}, retrying percent-encoded")
    return rc

def download(it):
    """-> 'ok' | 'skip' | 'fail'. On ok/skip the file on disk matches `size`."""
    name = it["name"]
    size = int(it.get("size") or 0)
    out  = os.path.join(RETRIEVE, os.path.basename(name))
    have = os.path.getsize(out) if os.path.exists(out) else 0
    dbg(f"{name}: device says {size}B, on disk {have}B -> "
        f"{'skip' if have and (not size or have == size) else 'fetch'}")
    if have and (not size or have == size):
        say(f"  skip  {name}")
        return "skip"
    mb = f"{size/1048576:.1f} MB" if size else "? MB"
    extra = f", resuming at {have/1048576:.1f} MB" if have else ""
    say(f"  get   {name}  ({mb}{extra})")
    big = size > 8 * 1048576
    rc = fetch(name, out, resume=have > 0, big=big)
    if rc != 0 and have > 0:
        # curl 33 = server ignored the Range header; start the file over.
        log(f"   {name}: no byte-range support, restarting")
        os.remove(out)
        rc = fetch(name, out, resume=False, big=big)
    if rc != 0:
        say(f"  FAIL  {name}  (curl {rc})")
        return "fail"
    got = os.path.getsize(out)
    if size and got != size:
        say(f"  WARN  {name}: got {got} bytes, expected {size}")
        return "fail"
    return "ok"

# ================================================================== delete ===
def delete(it):
    """DELETE /v1/medias/<name>."""
    name = it["name"]
    for candidate in name_urls(name):
        st, body = request(f"{base}/v1/medias/{candidate}", method="DELETE", timeout=15)
        log(f"   DELETE {name} -> {st} {snippet(body)}")
        if 200 <= st < 300:
            return True
    say(f"  KEPT  {name}  (device said {st} {snippet(body, 40)})")
    return False

def safe_to_delete(it, state):
    # (debug for each decision is emitted by the caller below)
    """Never delete something we do not demonstrably have."""
    if not RETRIEVE:
        return True                     # --removemedia alone; confirmed below
    if state not in ("ok", "skip"):
        return False
    size = int(it.get("size") or 0)
    out  = os.path.join(RETRIEVE, os.path.basename(it["name"]))
    if size <= 0:
        log(f"   {it['name']}: device reports no size, not deleting")
        return False
    return os.path.exists(out) and os.path.getsize(out) == size

# =================================================================== do it ===
if not items:
    say(f"nothing on the device ({base})")
    st, body = request(f"{base}/v1/tfcard/sdquery", timeout=4)
    log(f"   sdquery {st} {snippet(body, 120)}")
    sys.exit(0)

if RETRIEVE:
    say(f"{len(items)} item(s) on {base} — {vids} video")
    res, failed = {"ok": 0, "skip": 0, "fail": 0}, []
    states = {}
    for it in items:
        states[it["name"]] = st_ = download(it)
        res[st_] += 1
        if st_ == "fail":
            failed.append(it)

    # One more pass at whatever dropped out -- the buoy's range is about 15 m
    # and a single lost connection should not cost a trip.
    if failed:
        say(f"retrying {len(failed)} that failed")
        still = []
        for it in failed:
            st_ = download(it)
            states[it["name"]] = st_
            if st_ == "ok":
                res["ok"] += 1; res["fail"] -= 1
            else:
                still.append(it)
        failed = still

    say(f"downloaded {res['ok']}, skipped {res['skip']}, failed {res['fail']}  -> {RETRIEVE}")

    if REMOVE:
        for it in items:
            dbg(f"delete check {it['name']}: state={states.get(it['name'])!r} "
                f"-> {'delete' if safe_to_delete(it, states.get(it['name'])) else 'KEEP'}")
        deletable = [it for it in items if safe_to_delete(it, states.get(it["name"]))]
        held = len(items) - len(deletable)
        if held:
            say(f"keeping {held} on the device — not verified on disk")
        if deletable:
            say(f"deleting {len(deletable)} from the device")
            gone = sum(1 for it in deletable if delete(it))
            say(f"deleted {gone} of {len(deletable)}")
    if failed:
        say("still failing: " + ", ".join(i["name"] for i in failed))
        say(f"Details in {LOGPATH}.")
        sys.exit(1)

elif REMOVE:
    # No copy is being made. This is not undoable, so it gets a real prompt.
    total = sum(int(i.get("size") or 0) for i in items) / 1048576
    say(f"{len(items)} item(s) on {base} — {vids} video, {total:.1f} MB")
    say("--removemedia without --retrievemedia deletes them WITHOUT a copy.")
    if not YES:
        if not sys.stdin.isatty():
            say("Refusing to delete unprompted. Drop --confirm if you mean it.")
            sys.exit(1)
        try:
            answer = input(f"Type 'delete {len(items)}' to confirm: ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != f"delete {len(items)}":
            say("Nothing deleted.")
            sys.exit(1)
    gone = sum(1 for it in items if delete(it))
    say(f"deleted {gone} of {len(items)}")
    if gone != len(items):
        sys.exit(1)

if LIVE or TELEM:
    sys.exit(run_live())
