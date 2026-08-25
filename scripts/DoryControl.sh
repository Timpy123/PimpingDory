#!/bin/bash
# Talk to a Chasing Dory underwater drone without the vendor app.
# Everything here was read out of the CHASING GO2 app (com.chasing.ifdory).
# Join the drone's Wi-Fi (Dory_xxxxx / 12345678) and run it.
#
#   ./scripts/DoryControl.sh --retrievemedia ./media
#   ./scripts/DoryControl.sh --retrievemedia ./media --removemedia
#   ./scripts/DoryControl.sh --removemedia --confirm
#   ./scripts/DoryControl.sh --video
#   ./scripts/DoryControl.sh --telemetry
#
# There is no internet on the buoy's Wi-Fi, so this has to be enough on its
# own: it finds the camera, does the job, and stays quiet while that works.
# The moment something is off it says what it tried and why -- and either way
# the full detail lands in <path>/_run.txt, readable later back on the internet.
set -uo pipefail

# One source of truth for the option list: the program prints it, both
# launchers ask for it. A usage text maintained per platform is the first
# thing to drift.
PYFILE="$(cd "$(dirname "$0")" && pwd)/dorycontrol.py"
usage() { DORY_USAGE_ONLY=1 python3 "$PYFILE"; }

DEFAULT_MEDIA="$(pwd)/media"
RETRIEVE=""; REMOVE=0; LIVE=0; LIVEFILE=""; LIST=0; TELEM=0; CONTROL=0; POWER=40; SELFTEST=0
# The buoy relays nothing until a client completes the netcode handshake on
# UDP 40000, so it is on by default for everything that listens.
NETCODE="${DORY_NETCODE:-1}"; NETCODE_ONLY=0
CONTROL_KEY=""; TIMEOUT=""; GAP=3; LIGHTS="${DORY_LIGHTS:-off}"; LIGHTS_GIVEN=0; FINDLINK=0; PROBE=0; DIAGNOSE=0; IDENTIFY=0; MAXPOWER=0; DAEMON=0; SENDCMD=""
# Defaults chosen for someone standing at the water: try the address the buoy
# actually answers on, do not sweep, do not second-guess the Wi-Fi, do not ask.
# Each one has an inverse flag for when you want the caution back.
HOST="${DORY_HOST:-192.168.1.1}"; SCAN="${DORY_SCAN:-0}"
FORCE="${DORY_FORCE:-1}"; YES="${DORY_YES:-1}"
DEBUG="${DORY_DEBUG:-}"

# An optional value may follow these flags, but a following flag is not one.
next_is_value() { [ $# -ge 1 ] && [ -n "${1:-}" ] && [ "${1#-}" = "$1" ]; }

while [ $# -gt 0 ]; do
  case "$1" in
    --retrievemedia)
      shift
      if next_is_value "${1:-}"; then RETRIEVE="$1"; shift
      else RETRIEVE="$DEFAULT_MEDIA"; fi ;;
    --removemedia) REMOVE=1; shift ;;
    --video)
      LIVE=1; shift
      if next_is_value "${1:-}"; then LIVEFILE="$1"; shift; fi ;;
    --telemetry) TELEM=1; shift ;;
    --control)
      CONTROL=1; shift
      if next_is_value "${1:-}"; then CONTROL_KEY="$1"; shift; fi ;;
    # One command, one terminal, no daemon: the axis-mapping session. It is
    # sugar for --control with every key, because a sweep IS a single session
    # -- the daemon only ever mattered for keeping the link alive BETWEEN
    # separate commands.
    --sweep)
      CONTROL=1; CONTROL_KEY="a,forward,back,up,down,left,right,rollleft,rollright,pitchup,pitchdown"; shift
      if next_is_value "${1:-}"; then TIMEOUT="$1"; shift; else TIMEOUT=8; fi ;;
    --gap) GAP="${2:-3}"; shift 2 ;;
    # A value is optional: bare --lights turns them on.
    --lights)
      shift
      if next_is_value "${1:-}"; then LIGHTS="$1"; shift; else LIGHTS="on"; fi
      LIGHTS_GIVEN=1 ;;
    --timeout) TIMEOUT="${2:-}"; shift 2 ;;
    --selftest) SELFTEST=1; shift ;;
    --power)   POWER="${2:-40}"; shift 2 ;;
    --list)    LIST=1; shift ;;
    --netcode) NETCODE_ONLY=1; shift ;;
    --findlink) FINDLINK=1; shift ;;
    --probe)    PROBE=1; shift ;;
    --identify) IDENTIFY=1; shift ;;
    --maxpower) MAXPOWER=1; shift ;;
    --diagnose) DIAGNOSE=1; shift ;;
    --daemon)   DAEMON=1; shift ;;
    --send)     SENDCMD="${2:-status}"; shift 2 ;;
    --sock)     DORY_SOCK="${2:-}"; export DORY_SOCK; shift 2 ;;
    --no-netcode) NETCODE=0; shift ;;
    --host)    HOST="${2:-}"; shift 2 ;;
    --scan)    SCAN=1; shift ;;
    --checkwifi) FORCE=""; shift ;;
    --confirm) YES=""; shift ;;
    --debug)   DEBUG=1; shift ;;
    -h|--help|--usage) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; echo >&2; usage >&2; exit 2 ;;
  esac
done

if [ -z "$RETRIEVE" ] && [ "$REMOVE" = 0 ] && [ "$LIVE" = 0 ] && [ "$LIST" = 0 ] \
   && [ "$TELEM" = 0 ] && [ "$CONTROL" = 0 ] && [ "$NETCODE_ONLY" = 0 ] \
   && [ "$FINDLINK" = 0 ] && [ "$PROBE" = 0 ] && [ "$DIAGNOSE" = 0 ] \
   && [ "$DAEMON" = 0 ] && [ -z "$SENDCMD" ] && [ "$LIGHTS_GIVEN" = 0 ] \
   && [ "$IDENTIFY" = 0 ] && [ "$MAXPOWER" = 0 ]; then
  usage >&2; exit 2
fi

# --lights with nothing else is an action in its own right: set the light and
# exit. Requiring a daemon and a second terminal to turn a lamp on and off was
# a bad design.
LIGHTS_ONLY=0
if [ "$LIGHTS_GIVEN" = 1 ] && [ -z "$RETRIEVE" ] && [ "$REMOVE" = 0 ] \
   && [ "$LIVE" = 0 ] && [ "$LIST" = 0 ] && [ "$TELEM" = 0 ] \
   && [ "$CONTROL" = 0 ] && [ "$NETCODE_ONLY" = 0 ] && [ "$FINDLINK" = 0 ] \
   && [ "$PROBE" = 0 ] && [ "$DIAGNOSE" = 0 ] && [ "$DAEMON" = 0 ] \
   && [ -z "$SENDCMD" ] && [ "$IDENTIFY" = 0 ] && [ "$MAXPOWER" = 0 ]; then
  LIGHTS_ONLY=1
fi

# Where the run log goes: alongside the media when there is a destination,
# next to the script otherwise.
if [ -n "$RETRIEVE" ]; then
  mkdir -p "$RETRIEVE"; LOGDIR="$RETRIEVE"
else
  LOGDIR="$DEFAULT_MEDIA"; mkdir -p "$LOGDIR"
fi
LOG="$LOGDIR/_run.txt"

# The network we ran on is always recorded, never printed unless it matters.
{
  echo ""
  echo "== run $(date) == retrieve='${RETRIEVE}' remove=$REMOVE live=$LIVE list=$LIST telem=$TELEM"
} >> "$LOG"

dbg() { [ -n "$DEBUG" ] && printf '  · %s\n' "$*" >&2; return 0; }

# --- firewall, for --video only ----------------------------------------------
# macOS's application firewall can silently drop the inbound RTP. Turning it off
# for the duration is a real change to the machine's security, so: only --video
# touches it, we only put back what was there, and we leave a marker file so a
# run that gets SIGKILLed (exactly what DoryTest.sh does to capped steps) is
# healed by the next run rather than leaving you exposed.
#
# Never prompt for a password from here. When this runs as a background job --
# which it does under DoryTest.sh -- sudo's read from /dev/tty raises SIGTTIN,
# the process stops, and the typing you do goes to the shell instead. That is
# the "Password: appears but nothing I type registers" failure. So: sudo -n
# only, and if there is no cached credential, say what to do and stop.
FW="/usr/libexec/ApplicationFirewall/socketfilterfw"
FWMARK="$(cd "$(dirname "$0")" && pwd)/.firewall_was_on"

fw_is_on() { "$FW" --getglobalstate 2>/dev/null | grep -qE "State = 1"; }

restore_firewall() {
  [ -f "$FWMARK" ] || return 0
  if sudo -n "$FW" --setglobalstate on >/dev/null 2>&1; then
    rm -f "$FWMARK"
    echo "firewall turned back on"
  else
    echo "" >&2
    echo "COULD NOT restore the firewall — the sudo timestamp expired." >&2
    echo "Run this now:  sudo $FW --setglobalstate on" >&2
  fi
}

# When a calling script has already lowered the firewall and owns the restore,
# it sets this. Without it we would see its marker file, mistake it for a
# crashed run's leftover, put the firewall back up and then lower it again --
# which is exactly what happened in testing.
# Which modes listen on a UDP port and therefore need the firewall down.
# Computed here because the stale-marker check below consults it.
NEEDS_FW=0
[ "$LIVE" = "1" ] && NEEDS_FW=1
[ "$TELEM" = "1" ] && NEEDS_FW=1
[ "$CONTROL" = "1" ] && NEEDS_FW=1
[ "$PROBE" = "1" ] && NEEDS_FW=1
[ "$DIAGNOSE" = "1" ] && NEEDS_FW=1
[ "$DAEMON" = "1" ] && NEEDS_FW=1
[ "$LIGHTS_ONLY" = "1" ] && NEEDS_FW=1
[ "$FINDLINK" = "1" ] && NEEDS_FW=1
[ "$IDENTIFY" = "1" ] && NEEDS_FW=1
[ "$MAXPOWER" = "1" ] && NEEDS_FW=1

if [ -n "$SENDCMD" ]; then
  # A pure client: it opens a Unix socket to a running daemon and binds no
  # network port at all, so the firewall is irrelevant to it. It must not heal
  # the marker either -- the marker exists because the daemon is running and
  # legitimately holding the firewall down. Getting this wrong made every
  # --send abort with "a previous run left the firewall OFF" instead of
  # sending the command.
  dbg "--send is a client; not touching the firewall"
elif [ -n "${DORY_FW_MANAGED:-}" ]; then
  dbg "firewall managed by the caller; not touching it"
elif [ -x "$FW" ]; then
  # Heal a previous run that was killed before it could put things back --
  # but only if it really is dead. The marker records the pid that made it, so
  # a daemon that is still running and still needs the firewall down is left
  # alone instead of being healed out from under itself.
  if [ -f "$FWMARK" ] && [ -s "$FWMARK" ] && kill -0 "$(cat "$FWMARK")" 2>/dev/null; then
    dbg "firewall marker belongs to live pid $(cat "$FWMARK"); leaving it alone"
  elif [ -f "$FWMARK" ] && [ "$NEEDS_FW" = "1" ] && ! fw_is_on; then
    # This run wants the firewall down and a dead run already left it down.
    # Adopt the marker and get on with it. Refusing to run here -- which is
    # what this did until 2026-08-25 -- meant every command failed because the
    # machine was already in the state the command needed.
    echo $$ > "$FWMARK"
    dbg "firewall already off from a dead run; adopting the marker"
  elif [ -f "$FWMARK" ]; then
    if sudo -n "$FW" --setglobalstate on >/dev/null 2>&1; then
      rm -f "$FWMARK"; echo "firewall was left off by an earlier run — restored"
    else
      # A warning, not a refusal. Nothing here needs the firewall UP.
      echo "NOTE: an earlier run left the firewall off and sudo is not" >&2
      echo "authorised, so it stays off. To put it back:" >&2
      echo "   sudo $FW --setglobalstate on" >&2
    fi
  fi

  # EVERY mode that listens on a UDP port needs this, not just --video.
  # The macOS application firewall silently drops inbound UDP to an unsigned
  # binary: on 2026-08-24 a capture showed 6843 video packets and 608 MAVLink
  # packets arriving on the wire while the sockets bound to those exact ports
  # reported SILENT. Because only --video lowered the firewall, telemetry and
  # control worked inside DoryTest.sh (which lowers it for the whole run) and
  # never worked standalone -- which sent a day of debugging into MAVLink
  # semantics that were not the problem.
  if [ "$NEEDS_FW" = "1" ] && fw_is_on; then
    if ! sudo -n true 2>/dev/null; then
      # Prompting is only safe when we own the terminal. The "+" in ps's stat
      # field means this process group is the foreground one; without it, a
      # read from /dev/tty raises SIGTTIN and the password you type is eaten by
      # the shell instead -- which is exactly what happened under DoryTest.sh.
      case "$(ps -o stat= -p $$ 2>/dev/null)" in
        *+*) if [ -t 0 ]; then
               echo "lowering the macOS firewall for the video session:"
               sudo -v || { echo "sudo declined; not continuing." >&2; exit 1; }
             fi ;;
      esac
    fi
    if ! sudo -n true 2>/dev/null; then
      echo "" >&2
      echo "--video needs to lower the macOS firewall, and sudo is not" >&2
      echo "authorised. It cannot ask for the password from here: running as a" >&2
      echo "background job, the prompt appears but the keystrokes go to the" >&2
      echo "shell. Authorise it first, in this terminal:" >&2
      echo "" >&2
      echo "    sudo -v" >&2
      echo "" >&2
      echo "then run this again. It stays valid for a few minutes." >&2
      exit 1
    fi
    echo "turning the firewall off for this session"
    sudo -n "$FW" --setglobalstate off >/dev/null 2>&1
    # Verify. Believing the exit code is not enough -- confirm the state.
    if fw_is_on; then
      echo "" >&2
      echo "ERROR: the firewall is still enabled after trying to disable it." >&2
      echo "Not continuing: the video would silently receive nothing." >&2
      echo "Try by hand:  sudo $FW --setglobalstate off" >&2
      exit 1
    fi
    echo $$ > "$FWMARK"          # only now: it really is off
    dbg "firewall disabled; will restore on exit"
    trap restore_firewall EXIT INT TERM
  elif [ "$LIVE" = "1" ]; then
    dbg "firewall already off; leaving it alone"
  fi
fi

IFACE=""; MYIP=""
for i in $(ifconfig -l); do
  a=$(ipconfig getifaddr "$i" 2>/dev/null)
  if [ -n "$a" ]; then
    echo "   iface    $i $a" >> "$LOG"; dbg "iface    $i $a"
    if [ -z "$MYIP" ]; then IFACE="$i"; MYIP="$a"; fi
  fi
done
# macOS hides the SSID from the terminal unless it has Location permission,
# so this is often "<redacted>" and cannot be relied on by itself.
SSID=$(ipconfig getsummary "${IFACE:-en0}" 2>/dev/null | awk -F': *' '/ SSID *:/{print $2; exit}')
GW=$(netstat -rn -f inet | awk '/^default/{print $2; exit}')
{
  echo "   ssid     ${SSID:-(unknown)}"
  echo "   gateway  ${GW:-(none)}"
} >> "$LOG"

if [ -n "$MYIP" ]; then
  ping -c 2 -t 2 "${MYIP%.*}.255" >/dev/null 2>&1
fi
PREFIX="${MYIP%.*}."
NEIGHBOURS=$(arp -an 2>/dev/null | awk -v p="$PREFIX" '{gsub(/[()]/,"",$2); if (index($2,p)==1 && $4 != "incomplete" && $2 !~ /\.(0|255)$/) print $2}' | sort -u)
echo "   arp      $(echo "$NEIGHBOURS" | tr '\n' ' ')" >> "$LOG"
dbg "ssid     ${SSID:-(unknown)}"
dbg "gateway  ${GW:-(none)}"
dbg "arp      $(echo "$NEIGHBOURS" | tr '\n' ' ')"

export DORY_LOG="$LOG" DORY_MYIP="$MYIP" DORY_GW="$GW" DORY_SSID="$SSID"
export DORY_NEIGHBOURS="$NEIGHBOURS" DORY_HOST="$HOST" DORY_SCAN="$SCAN"
export DORY_FORCE="$FORCE" DORY_YES="$YES"
export DORY_RETRIEVE="$RETRIEVE" DORY_REMOVE="$REMOVE"
export DORY_LIVE="$LIVE" DORY_LIVEFILE="$LIVEFILE" DORY_LIST="$LIST"
export DORY_TELEM="$TELEM" DORY_DEBUG="$DEBUG"
export DORY_CONTROL="$CONTROL" DORY_POWER="$POWER" DORY_SELFTEST="$SELFTEST"
export DORY_NETCODE="$NETCODE" DORY_NETCODE_ONLY="$NETCODE_ONLY"
export DORY_CONTROL_KEY="$CONTROL_KEY" DORY_TIMEOUT="$TIMEOUT" DORY_GAP="$GAP" DORY_LIGHTS="$LIGHTS" DORY_LIGHTS_ONLY="$LIGHTS_ONLY"
export DORY_FINDLINK="$FINDLINK" DORY_PROBE="$PROBE" DORY_DIAGNOSE="$DIAGNOSE"
export DORY_DAEMON="$DAEMON" DORY_SENDCMD="$SENDCMD" DORY_IDENTIFY="$IDENTIFY" DORY_MAXPOWER="$MAXPOWER"

# `ps` now shows `python3 .../dorycontrol.py`, which is identifiable on its
# own -- an orphaned interpreter holding UDP 14550 was invisible when this was
# a heredoc and showed only as `python3 -`. That cost an entire test run on
# 2026-08-24. DoryTest.sh matches on the filename.
# ---------------------------------------------------------------------------
# Everything below this point used to be an embedded Python program. It now
# lives in scripts/dorycontrol.py, which the Windows launcher runs too --
# TODO.md called this right: two hand-maintained implementations drift, and
# the drift only shows up at the water where neither can be debugged. The
# Windows port was three days behind within a week. One file, two launchers.
#
# The launcher's whole job is the network facts, which are the genuinely
# platform-specific part, plus the firewall handling above.
if [ ! -f "$PYFILE" ]; then
  echo "Cannot find dorycontrol.py next to this script (expected $PYFILE)" >&2
  exit 2
fi
exec python3 "$PYFILE"
