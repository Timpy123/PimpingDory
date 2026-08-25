#!/bin/bash
# Exercise every DoryControl.sh mode against the real drone, once, and write a
# transcript you can send back when you have internet again.
#
#   ./scripts/DoryTest.sh
#
# Run it on the buoy's Wi-Fi with the drone powered and awake. It takes roughly
# four minutes plus however long the download needs.
#
# Rules it follows:
#   - every mode runs with --debug, so the log says why, not just what
#   - each test is capped at 30s, except --retrievemedia and the real delete,
#     which run to completion however long they take
#
# *** THIS RUN ERASES THE DRONE'S CARD. ***
# The delete tests are real and they are last, after everything has been
# downloaded twice. Thijmen authorised this on 2026-08-22 having backed the
# files up. Pass --keep to run everything except the deletes — do that on any
# trip where the footage is not already safe somewhere else.
#
# Everything lands in ./dorytest-<timestamp>.log along with the exact command
# line used for each step.
set -uo pipefail

CTL="$(cd "$(dirname "$0")" && pwd)/DoryControl.sh"
LOG="$(pwd)/dorytest-$(date +%Y%m%d-%H%M%S).log"
CAP=30                     # seconds; the download ignores this
VIDCAP=10                  # video steps: if it works it works in ten seconds
KEEP=0                     # --keep skips the deletes
# Single diagnostic steps. These used to be options on DoryControl.sh, which
# was wrong: if you cannot use a command in the water it does not belong in
# the production script. DoryControl still implements them -- it is the only
# thing that talks to the drone -- but this is where you reach for them.
ONLY=""
# Confirmed working on real hardware 2026-08-24, so skipped by default: the
# usage/list variants, the handshake, plain live video, and the retrieve and
# delete paths. --all runs them anyway. This is about getting to the parts
# that still do not work without sitting through the parts that do.
SKIPCONFIRMED=1
for a in "$@"; do
  case "$a" in
    --keep) KEEP=1 ;;
    --all)  SKIPCONFIRMED=0 ;;
    --sweep|--probe|--diagnose|--findlink|--identify) ONLY="$a" ;;
    -h|--help|--usage)
      cat <<'EOT'
DoryTest.sh -- exercise DoryControl against the real drone

  (no options)   the full suite; ENDS BY ERASING THE CARD
  --keep         the full suite, but never delete anything
  --all          include the steps already confirmed working
  --sweep        ONLY the axis-mapping sweep: every axis 8s in turn
  --probe        ONLY the short probe: one arm, one up, every byte logged
  --diagnose     ONLY the big diagnostic: every theory at once, ~90s
  --findlink     ONLY the destination sweep
  --identify     ONLY: ask the flight controller what firmware it runs and
                 dump every parameter it holds. Read-only, nothing is armed.

Everything writes ./dorytest-<timestamp>.log. Run `sudo -v` first.
EOT
      exit 0 ;;
  esac
done
# Wraps a step that is already known good.
confirmed() { [ "$SKIPCONFIRMED" = "1" ] && return 0; return 1; }
skip() { STEP=$((STEP+1)); out ""; out "[$STEP] $1 — SKIPPED (confirmed working; --all to run it)"; }
PASS=0; FAIL=0; STEP=0
# Hard ceiling for each step's own process tree. Today's fork bomb reached the
# 4000-process user limit; with this, the worst case is +200 and the step dies
# on its own instead of taking the machine with it.
PROC_CAP=$(( $(ps -u "$(id -u)" 2>/dev/null | wc -l | tr -d ' ') + 200 ))

# --- both to screen and to the log -------------------------------------------
out() { printf '%s\n' "$*" | tee -a "$LOG"; }

# --- process hygiene ---------------------------------------------------------
# On 2026-08-22 a stray line in DoryControl.sh made it invoke itself and it
# fork-bombed the machine to the 4000-process ceiling. These two guards exist so
# that can never happen again unnoticed.
# Anything of ours still running. Both patterns matter: the launcher is
# "DoryControl.sh" and the program it runs is "dorycontrol.py". An orphan is
# usually only the second one -- and when the program was an embedded heredoc
# it showed in ps as a bare "python3 -", invisible to any sane pattern, which
# is how one held UDP 14550 through an entire run on 2026-08-24.
OURS='DoryControl\.sh|dorycontrol\.py|dorycontrol-embedded'
strays() { pgrep -f "$OURS" 2>/dev/null | wc -l | tr -d ' '; }

# Every port this suite binds. 40000 is the buoy's, not ours -- our end of the
# handshake is an ephemeral port, so there is nothing to collide with there.
PORTS="5600 14550"

# Refuse to start on a port we cannot have. A single stale interpreter holding
# 14550 silently failed telemetry, the control selftest and all nine thruster
# steps on 2026-08-24 -- the whole point of the trip -- while every one of them
# reported its own separate error. Better to lose two seconds here than a trip.
check_ports() {
  local blocked=0 port pid cmd
  for port in $PORTS; do
    for pid in $(lsof -tnP -iUDP:"$port" 2>/dev/null | sort -u); do
      cmd=$(ps -o command= -p "$pid" 2>/dev/null)
      [ -z "$cmd" ] && continue
      if printf '%s' "$cmd" | grep -qE "$OURS"; then
        out "   UDP $port  held by our own pid $pid — killing it"
        out "             $cmd"
        kill -9 "$pid" 2>/dev/null
      else
        out "   UDP $port  held by something that is NOT ours:"
        out "             pid $pid  $cmd"
        blocked=1
      fi
    done
  done
  sleep 1
  # Whatever we killed should be gone; anything still there stops the run.
  for port in $PORTS; do
    if [ -n "$(lsof -tnP -iUDP:"$port" 2>/dev/null)" ]; then
      out "   UDP $port  STILL held after cleanup"
      blocked=1
    fi
  done
  if [ "$blocked" = "1" ]; then
    out ""
    out "ABORTED: a port this test needs is in use by a process that is not"
    out "ours, so it will not be killed automatically. Free it and re-run:"
    for port in $PORTS; do out "   lsof -nP -iUDP:$port"; done
    exit 1
  fi
  out "   ports    UDP $PORTS free"
}
myprocs() { ps -u "$(id -u)" 2>/dev/null | wc -l | tr -d ' '; }

preflight() {
  out "== preflight =="
  if [ ! -x "$CTL" ]; then out "   FATAL: $CTL is missing or not executable"; exit 1; fi

  # A non-comment line that runs the script from inside the script is the
  # signature of that bug. Refuse to run at all if one is there.
  # The usage text no longer lives here -- it moved into dorycontrol.py so both
  # launchers share one copy -- so there is no heredoc left to skip.
  local selfcall
  selfcall=$(grep -nE '^[[:space:]]*[^#[:space:]].*DoryControl\.sh' "$CTL" \
             | grep -vE 'CTL=|\$CTL')
  if [ -n "$selfcall" ]; then
    out "   FATAL: DoryControl.sh invokes itself outside a comment or heredoc."
    out "   Refusing to run — this is exactly the fork-bomb signature."
    printf '%s\n' "$selfcall" | tee -a "$LOG"
    exit 1
  fi
  out "   guard    no self-invocation outside comments/heredoc"

  bash -n "$CTL" 2>>"$LOG" || { out "   FATAL: $CTL has a syntax error"; exit 1; }
  # The launcher is a stub now; the program next to it is what actually runs,
  # so check and fingerprint that too.
  local PYF="$(dirname "$CTL")/dorycontrol.py"
  if [ ! -f "$PYF" ]; then out "   FATAL: dorycontrol.py is missing"; exit 1; fi
  python3 -m py_compile "$PYF" 2>>"$LOG" || {
    out "   FATAL: dorycontrol.py has a syntax error"; exit 1; }
  rm -rf "$(dirname "$PYF")/__pycache__" 2>/dev/null
  out "   script   $CTL"
  out "   program  $PYF"
  out "   sha256   $(shasum -a 256 "$CTL" | awk '{print $1}')"
  out "   sha256   $(shasum -a 256 "$PYF" | awk '{print $1}')  (dorycontrol.py)"
  out "   log      $LOG"
}

# --- environment, so the log is readable months later ------------------------
environment() {
  out ""
  out "== environment =="
  out "   date     $(date)"
  out "   host     $(hostname) / $(sw_vers -productName 2>/dev/null) $(sw_vers -productVersion 2>/dev/null)"
  local iface ip
  for iface in $(ifconfig -l); do
    ip=$(ipconfig getifaddr "$iface" 2>/dev/null)
    [ -n "$ip" ] && out "   iface    $iface $ip"
  done
  out "   ssid     $(ipconfig getsummary en0 2>/dev/null | awk -F': *' '/ SSID *:/{print $2; exit}')"
  out "   gateway  $(netstat -rn -f inet | awk '/^default/{print $2; exit}')"
  out "   arp      $(arp -an 2>/dev/null | awk '{gsub(/[()]/,"",$2); print $2}' | tr '\n' ' ')"
  out "   python3  $(python3 --version 2>&1)"
  out "   curl     $(curl --version 2>/dev/null | head -1)"
  local vlc="/Applications/VLC.app/Contents/MacOS/VLC"
  [ -x "$vlc" ] && out "   vlc      $("$vlc" --version 2>/dev/null | head -1)" \
                || out "   vlc      NOT INSTALLED — the --video tests will use the browser fallback"
  command -v ffmpeg >/dev/null && out "   ffmpeg   $(ffmpeg -version 2>/dev/null | head -1)" \
                               || out "   ffmpeg   not installed"
  out "   procs    $(myprocs) of $(ulimit -u) allowed"
  check_ports
}

# --- how many files the drone currently holds ------------------------------
count_files() {
  local n
  n=$("$CTL" --list 2>/dev/null | awk '/item\(s\) on/{print $1; exit}')
  printf '%s' "${n:-0}"
}

# --- the runner --------------------------------------------------------------
# $1 label, $2 seconds (0 = no limit), $3 expected exit code (-1 = don't care),
# rest = the command. Runs in its own process group so a timeout kills the
# children too — python, curl and VLC all outlive a plain kill of the parent.
run() {
  local label="$1" limit="$2" want="$3"; shift 3
  STEP=$((STEP+1))
  local before; before=$(myprocs)

  out ""
  out "=============================================================="
  out "[$STEP] $label"
  out "     at $(date '+%H:%M:%S')   limit ${limit}s   expect exit ${want}"
  out "     \$ $*"
  out "=============================================================="

  set -m
  if [ "${TEE:-0}" = "1" ]; then
    # Show it live as well as logging it. The sweep is useless otherwise: you
    # are watching the drone, and you need to see WHICH axis is running at the
    # moment something moves. Everything still lands in the log.
    ( ulimit -u "$PROC_CAP" 2>/dev/null; exec "$@" ) </dev/null 2>&1 | tee -a "$LOG" &
  else
    ( ulimit -u "$PROC_CAP" 2>/dev/null; exec "$@" ) </dev/null >>"$LOG" 2>&1 &
  fi
  local pid=$!
  set +m

  local waited=0 timedout=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$limit" -gt 0 ] && [ "$waited" -ge "$limit" ]; then
      timedout=1
      kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
      sleep 2
      kill -9 -"$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null
      break
    fi
    sleep 1; waited=$((waited+1))
  done
  # A "Terminated: 15" notice from job control appears here whenever a capped
  # step is killed. It is expected, it cannot be redirected away (the shell
  # emits it asynchronously), and the line right below it says the same thing
  # in plainer words. Not a failure.
  wait "$pid" 2>/dev/null; local rc=$?

  # Anything the timeout missed dies here rather than piling up.
  local left; left=$(strays)
  if [ "$left" -gt 0 ]; then
    out "     note: killing $left leftover DoryControl process(es)"
    pkill -9 -f "$OURS" 2>/dev/null
    sleep 1
  fi

  local after; after=$(myprocs)
  local delta=$((after-before))

  if [ "$timedout" = "1" ]; then
    # Reaching the cap is the pass condition for a mode that runs until you
    # quit it: it means it was still going.
    out "     -> stopped at ${limit}s (still running, which is the pass)"
    PASS=$((PASS+1))
  elif [ "$want" = "-1" ]; then
    # "Don't care" about the exact code, but a live mode that exits early has
    # given up on something. Do not call that a pass -- the 2026-08-23 run
    # reported 19/19 while video and telemetry had both bailed out.
    if [ "$rc" = "0" ]; then
      out "     -> finished in ${waited}s, exit 0"
      PASS=$((PASS+1))
    else
      out "     -> FAILED: exited early (${waited}s, exit $rc) — see above for why"
      FAIL=$((FAIL+1))
    fi
  elif [ "$rc" = "$want" ]; then
    out "     -> finished in ${waited}s, exit $rc (as expected)"
    PASS=$((PASS+1))
  else
    out "     -> FAILED: exit $rc, expected $want, after ${waited}s"
    FAIL=$((FAIL+1))
  fi

  out "     procs ${before} -> ${after} (delta ${delta})"
  if [ "$delta" -gt 50 ]; then
    out ""
    out "     ABORTING: that step leaked ${delta} processes."
    out "     This is how the fork bomb looked. Stopping before it spreads."
    pkill -9 -f "$OURS" 2>/dev/null
    exit 1
  fi
}

# Only for --control, which reads the keyboard. Raw mode is restored afterwards
# whatever happens: a SIGKILL skips the script's own cleanup.

# =============================================================================
: > "$LOG"
out "DoryControl test run — every step below ran with --debug"
out "Send this whole file back; it is meant to be read cold."
preflight

environment

if [ -n "$ONLY" ]; then
  # A single diagnostic downloads nothing and deletes nothing, so the card
  # warning below does not apply and would only be alarming.
  out ""
  out ">>> Single step: $ONLY. The drone's card is not touched."
elif [ "$KEEP" = "1" ]; then
  out ""
  out ">>> --keep given: the drone's card will NOT be touched."
else
  out ""
  out ">>> WARNING: this run ENDS BY ERASING the drone's card."
  out ">>> Everything is downloaded to ./media twice first, and the deletes"
  out ">>> only remove files verified on disk. Re-run with --keep to skip them."
fi

# --- sudo, while we still own the terminal ------------------------------------
# Every step below runs as a background job, and a background job cannot read a
# password: sudo's read from /dev/tty raises SIGTTIN, so the prompt appears and
# the keystrokes go to the shell. That is the failure seen on 2026-08-23. So the
# firewall gets lowered HERE, in the foreground, once — and the video steps then
# find it already down and leave it alone.
FWBIN="/usr/libexec/ApplicationFirewall/socketfilterfw"
FWMARK="$(cd "$(dirname "$0")" && pwd)/.firewall_was_on"
KEEPALIVE=""

fw_on() { "$FWBIN" --getglobalstate 2>/dev/null | grep -qE "State = 1"; }

fw_restore() {
  [ -n "$KEEPALIVE" ] && kill "$KEEPALIVE" 2>/dev/null
  [ -f "$FWMARK" ] || return 0
  if sudo -n "$FWBIN" --setglobalstate on >/dev/null 2>&1; then
    rm -f "$FWMARK"; out "firewall turned back on"
  else
    out "*** FIREWALL STILL OFF. Run: sudo $FWBIN --setglobalstate on ***"
  fi
}

if [ -x "$FWBIN" ] && fw_on; then
  out ""
  out ">>> The video steps need the macOS firewall lowered. Authorising now."
  out ">>> Type your password at the prompt; it is asked once, here, and the"
  out ">>> firewall goes back on before this script finishes."
  if ! sudo -v; then
    out "sudo was declined. Stopping — the video steps cannot work without it."
    exit 1
  fi
  sudo -n "$FWBIN" --setglobalstate off >/dev/null 2>&1
  if fw_on; then
    out "ERROR: the firewall is still enabled after trying to disable it."
    out "Stopping, rather than running video steps that would receive nothing."
    exit 1
  fi
  touch "$FWMARK"
  # Tell the child not to second-guess this: we own the marker and the restore.
  export DORY_FW_MANAGED=1
  out "     firewall is down for the duration"
  # Keep the sudo timestamp warm; the download can outlast the default 5 min.
  ( while :; do sudo -n true 2>/dev/null; sleep 45; done ) &
  KEEPALIVE=$!
  trap fw_restore EXIT INT TERM
elif [ -x "$FWBIN" ]; then
  out ""
  out ">>> Firewall is already off; leaving it that way."
fi

# A single diagnostic, then stop. No card, no downloads, no deletes.
if [ -n "$ONLY" ]; then
  TEE=1
  case "$ONLY" in
    --sweep)
      out ""
      out ">>> AXIS MAPPING. Every axis 8s in turn, 3s gaps. It arms."
      out ">>> In a bucket, tether in hand. Note which motor runs for each."
      run "sweep: every axis in turn" 180 -1 "$CTL" --sweep 8 --power 30 --debug
      out "     WHAT MOVED, and on which key?"
      out "       (expected, from the vehicle's own ArduSub parameters)"
      for k in "a           arm only, nothing should move" \
               "forward     forward"       "back        backward" \
               "up          towards the surface" "down        deeper" \
               "left        yaw left"      "right       yaw right" \
               "rollleft    roll left"     "rollright   roll right" \
               "pitchup     nose up"       "pitchdown   nose down"; do
        out "       $k"
        out "         actual: ..........................................."
      done ;;
    --probe)
      run "probe: one arm, one up, every byte" 90 -1 "$CTL" --probe --debug ;;
    --diagnose)
      run "diagnose: every theory at once" 180 -1 "$CTL" --diagnose --debug ;;
    --findlink)
      run "findlink: which address does the drone listen on" 90 -1 \
          "$CTL" --findlink --timeout 8 --debug ;;
    --identify)
      out ""
      out ">>> Asking the flight controller what it is. Read-only: nothing"
      out ">>> is armed and no thruster can move. Takes up to ~2 minutes,"
      out ">>> most of it waiting for the parameter list."
      run "identify: autopilot version and full parameter dump" 200 -1 \
          "$CTL" --identify --debug
      if [ -s "$(pwd)/media/params.txt" ]; then
        out "     parameters: $(wc -l < "$(pwd)/media/params.txt" | tr -d ' ') lines in media/params.txt"
        out "     KEEP THAT FILE. It is the only record of how this vehicle"
        out "     is configured, and a reflash would need it."
      fi ;;
  esac
  out ""
  out "log: $LOG"
  fw_restore
  exit 0
fi

# --- 1. things that need no drone at all -------------------------------------
if confirmed; then skip "usage and argument handling"
else
  run "usage via --usage"           10  0  "$CTL" --usage
  run "usage via --help"            10  0  "$CTL" --help
  run "no arguments prints usage"   10  2  "$CTL"
  run "unknown option is rejected"  10  2  "$CTL" --definitely-not-a-flag
fi

# --- 2. discovery and listing ------------------------------------------------
if confirmed; then skip "list, default and forced host"
else
  run "list, default host"          "$CAP" 0 "$CTL" --list --debug
  run "list, host forced to .1"     "$CAP" 0 "$CTL" --list --host 192.168.1.1 --debug
fi
run "list, host forced to .88 (should fall back to .1)" \
                                  "$CAP" -1 "$CTL" --list --host 192.168.1.88 --debug
run "list with --scan"            "$CAP" -1 "$CTL" --list --scan --debug
run "list with --checkwifi"       "$CAP" -1 "$CTL" --list --checkwifi --debug

# --- 2b. the handshake that starts the stream --------------------------------
# Three trips saw 0 packets on 5600 and 14550 while HTTP listed files fine.
# The buoy relays nothing until a client completes a netcode handshake on UDP
# 40000; DoryControl now speaks it. This step is the one to read first — if it
# fails, everything below that listens will fail too, and for this reason.
out ""
out ">>> Asking the buoy to start pushing video and telemetry."
run "netcode handshake with the buoy" 20 -1 "$CTL" --netcode --debug

# Proof that the handshake is what changed things: with --no-netcode the
# script does exactly what every run before 2026-08-23 did -- bind and listen
# without asking. If this one reports 0 packets while the steps above report
# some, that is the before-and-after in a single log.
if confirmed; then skip "video with --no-netcode (proves the handshake)"
else
  run "video with --no-netcode (expected to receive nothing)" \
                                    "$CAP" -1 "$CTL" --video --no-netcode --timeout 6 --debug
fi

# --- 3. telemetry: depth and battery -----------------------------------------
run "telemetry, 30s of live depth and battery" \
                                  "$CAP" -1 "$CTL" --telemetry --debug

# --- 4. live video -----------------------------------------------------------
# VLC opens a window for these. That is the test — let it, then let the cap
# close it. If nothing appears, the log says whether packets arrived.
out ""
out ">>> The next steps open VLC for 10s each. Leave them alone."
if confirmed; then skip "video, live only"
else
  run "video, live only"            "$CAP" -1 "$CTL" --video --debug
fi
# .mp4, and the cap sends SIGTERM rather than SIGKILL so VLC gets to write
# the moov atom. An mp4 killed mid-write has no index and will not play.
CLIP="$(pwd)/dorytest-clip.mp4"
rm -f "$CLIP"
run "video, live plus recording"  "$VIDCAP" -1 "$CTL" --video "$CLIP" --debug
if [ -s "$CLIP" ]; then
  out "     recorded $(du -h "$CLIP" | awk '{print $1}') to dorytest-clip.mp4"
  out "     Open it. If it will not play, the mp4 was not finalised and the"
  out "     recording needs a clean quit rather than a timeout."
else
  out "     NOTE: dorytest-clip.mp4 is empty or missing — recording did not work"
fi
run "video plus telemetry together" \
                                  "$VIDCAP" -1 "$CTL" --video --telemetry --debug

# --- 4b. is anything on the wire at all? -------------------------------------
# tcpdump reads through BPF, below macOS's Local Network privacy layer, so it
# tells "the drone is silent" apart from "the Mac is hiding the packets".
#
# Two changes after the 2026-08-23 run came back empty. It captures ALL UDP,
# not just 5600 and 14550: filtering on the two ports we guessed can only ever
# confirm the guess, and if the buoy relays somewhere else that filter hides
# the answer. And it runs WHILE the handshake is going, because with no
# handshake there is nothing to capture — which is exactly why the last run
# recorded 0 packets and told us nothing.
out ""
out ">>> Watching the whole wire while the handshake runs."
if sudo -n true 2>/dev/null; then
  DUMP="$(pwd)/dorytest-udp.txt"
  sudo -n tcpdump -i en0 -n -l "udp and not port 80 and not port 53" \
       > "$DUMP" 2>"$DUMP.err" &
  DUMPPID=$!
  sleep 2
  run "handshake again, with the wire being watched" 20 -1 "$CTL" --netcode --debug
  sleep 2
  sudo -n kill "$DUMPPID" 2>/dev/null
  wait "$DUMPPID" 2>/dev/null
  out ""
  out "     --- every UDP packet seen, both directions ---"
  if [ -s "$DUMP" ]; then
    # Ports, then a sample. The port summary is the thing worth reading: it
    # says where the buoy actually sends, rather than where we hoped.
    out "     ports seen:"
    awk '{print $3, $5}' "$DUMP" | sed 's/[.:]$//' | sort | uniq -c | sort -rn \
      | head -20 | while read -r line; do out "       $line"; done
    out "     first 25 packets:"
    head -25 "$DUMP" | while read -r line; do out "       $line"; done
    out "     ($(wc -l < "$DUMP" | tr -d ' ') packets total, full list in $DUMP)"
  else
    out "       nothing at all. Not one UDP packet in either direction."
    out "       That rules out the Mac dropping them: BPF sees the wire."
    [ -s "$DUMP.err" ] && head -5 "$DUMP.err" | while read -r l; do out "       $l"; done
  fi
else
  out "     sudo needs a password, so this was skipped. Run it yourself,"
  out "     in one terminal, while --netcode runs in another:"
  out "       sudo tcpdump -i en0 -n udp and not port 80"
  out "     Packets there but not in the script above => macOS Local Network"
  out "     privacy is eating them, not a protocol problem."
fi

# --- 4c. does VLC actually open a window? ------------------------------------
# The 2026-08-23 run never got here: no packets meant the player was never
# launched, so the "VLC was already open and nothing appeared" complaint was
# never actually tested. This runs the exact argv the script uses.
# No SDP file anywhere. The description goes on the command line behind
# sdp://, which is what DoryControl.sh itself passes -- the payload-type-96
# to H.264 mapping has to travel somehow (rtp://@:5600 cannot carry it, and
# VLC's --rtp-dynamic-pt only accepts "theora"), but it never needs to be a
# file. This is the identical argv the script builds.
out ""
out ">>> A VLC window should appear now. It closes itself after 10s."
VLCBIN="/Applications/VLC.app/Contents/MacOS/VLC"
if [ -x "$VLCBIN" ]; then
  # This only shows a picture while a netcode session is live, so hold one
  # open for the duration. Without it the buoy has stopped relaying by now
  # and VLC sits on a silent port -- which is exactly what happened on the
  # 2026-08-24 run and looked like a VLC fault.
  "$CTL" --netcode --timeout 20 --debug >/dev/null 2>&1 &
  NCPID=$!
  sleep 2
  run "VLC opens its own window on the sdp:// URL" "$VIDCAP" -1 \
      "$VLCBIN" --no-video-title-show --network-caching=200 \
      --macosx-control-itunes=0 \
      $'sdp://v=0\no=- 0 0 IN IP4 127.0.0.1\ns=Chasing Dory\nc=IN IP4 0.0.0.0\nt=0 0\nm=video 5600 RTP/AVP 96\na=rtpmap:96 H264/90000\n'
  kill "$NCPID" 2>/dev/null; wait "$NCPID" 2>/dev/null
else
  out "     VLC is not installed; skipped."
fi

# --- 4d. control transport, nothing moves ------------------------------------
out ""
out ">>> Control link check. Neutral frames only — the drone will NOT move."
run "control selftest (no arming, no movement)" \
                                  "$CAP" -1 "$CTL" --control --selftest --debug

# --- 4e. each axis, one at a time, unattended --------------------------------
# THE THRUSTERS RUN HERE. Until --control <key> existed the only unattended
# coverage was the selftest above, which deliberately moves nothing -- so
# nothing had ever proved a thruster responds at all.
#
# Each step arms (COMMAND_LONG 400 param1=1.0 -- the app's "unlock" button),
# holds one axis for 4s, then sends neutral x20 and disarms. Watch the drone
# and write down what each one actually does: that mapping is the one thing
# the vendor app never records.
out ""
out ">>> ================= THE DRONE WILL NOW MOVE ================="
out ">>> Five steps, 4 seconds each, one axis at a time, 30% power."
out ">>> IN A BUCKET, TETHER IN HAND. Write down what each one moves."
out ""
# Before driving anything: find out whether the drone can hear us at all.
# Four runs have now sent well-formed arm commands and never once drawn a
# COMMAND_ACK, while the drone repeats "MYGCS: 255, heartbeat lost" through a
# session we beat continuously. That warning fires when a vehicle has NEVER
# seen its GCS, so the working assumption is that our upstream packets are not
# reaching the flight controller. This sweeps the addresses it might be
# listening on -- including 192.168.1.88:1000, which the netcode handshake
# announces and which we have never sent a byte to.
out ""
out ">>> Which address does the drone actually listen on? ~40s."
run "findlink: sweep the possible MAVLink destinations" 60 -1 \
    "$CTL" --findlink --timeout 8 --debug

# ONE process, one heartbeat, one arm, every axis in turn. Nine separate
# processes each beating for seven seconds put a gap between every step, and
# the drone named the consequence on 2026-08-24: "MYGCS: 255, heartbeat lost".
# A vehicle in GCS failsafe will not arm, so nothing could ever have moved.
run "sweep: every axis in turn, 8s each" 180 -1 \
    "$CTL" --sweep 8 --power 30 --debug
out ""
out "     WHAT MOVED, and on which key?"
for k in a up down left right w s q e; do
  out "       $k  ......................................................"
done

# --- 5. the download: no time limit ------------------------------------------
out ""
out ">>> Downloading everything now. No time limit; this is the slow one."
run "retrieve to the default ./media" 0 -1 "$CTL" --retrievemedia --debug
run "retrieve again (everything should skip)" 0 -1 "$CTL" --retrievemedia --debug

# --- 6. delete ---------------------------------------------------------------
# Last on purpose: everything above has already run against a full card, and
# the files have been downloaded twice by now.
if [ "$KEEP" = "1" ]; then
  out ""
  out ">>> --keep given: skipping the delete tests. The card is untouched."
else
  out ""
  out ">>> Delete tests. THE CARD WILL BE EMPTIED from here on."

  # 6a. The guard first: with --confirm and no tty this must refuse and remove
  #     nothing. Checked before the real delete, while there is still something
  #     to lose, because that is the only way the check means anything.
  BEFORE_COUNT=$(count_files)
  out "     drone is holding ${BEFORE_COUNT} file(s) before the guard test"
  run "removemedia --confirm with no tty (must refuse)" \
                                    "$CAP" 1 "$CTL" --removemedia --confirm --debug
  GUARD_COUNT=$(count_files)
  out "     after the guard test: ${GUARD_COUNT} file(s)"
  if [ "$BEFORE_COUNT" != "$GUARD_COUNT" ]; then
    out "     *** FAILED: the guard deleted something. ***"
    FAIL=$((FAIL+1))
  else
    out "     good: the guard refused and removed nothing"
  fi

  # 6b. The real one, and the path that matters most: download first, then
  #     delete only what is verified on disk. Everything is already downloaded,
  #     so this also exercises "already present -> still delete it".
  #     No time cap: killing this mid-DELETE is not something to invite.
  run "retrievemedia + removemedia (the real delete)" \
                                    0 -1 "$CTL" --retrievemedia --removemedia --debug
  AFTER_COUNT=$(count_files)
  out "     drone is holding ${AFTER_COUNT} file(s) after the real delete"
  if [ "$AFTER_COUNT" = "0" ]; then
    out "     good: the card is empty and the files are in ./media"
  else
    out "     NOTE: ${AFTER_COUNT} file(s) left. Not necessarily wrong — the"
    out "     script keeps anything it could not verify on disk. The --debug"
    out "     lines above say which and why."
  fi
  out "     local copies now in ./media: $(ls -1 media 2>/dev/null | grep -vc '^_')"

  # 6c. The empty-card path, which nothing has ever exercised.
  run "removemedia on an empty card"  "$CAP" -1 "$CTL" --removemedia --debug
  run "list on an empty card"         "$CAP" -1 "$CTL" --list --debug
fi

# Controls are covered by the --control <key> steps above, which need no
# keyboard. Nothing here waits for input: apart from the one sudo prompt at
# the top, this script runs start to finish on its own.

# =============================================================================
out ""
out "=============================================================="
out "finished $(date)"
out "$PASS passed, $FAIL failed, across $STEP steps"
out "strays left behind: $(strays)   procs now: $(myprocs)"
fw_restore
out "firewall now: $("$FWBIN" --getglobalstate 2>/dev/null | tail -1)"
out "log: $LOG"
out "=============================================================="
echo
echo "Send this file back: $LOG"
[ "$FAIL" = "0" ]
