# Camera upgrade

Replace with a higher-resolution camera.

Standard is **1080p30 H.264 video and 1920×1080 stills**, 1/2.9" CMOS, f/1.6,
4 mm lens, 100° FOV, ISO 100–3200.

## What the software side expects

The drone pushes **RTP/H.264 to UDP 5600, payload type 96**, and the script
hands that to VLC through an inline `sdp://` URL. Anything that changes the
codec, payload type or resolution changes that description — `--video` reports
the payload type it actually sees, so a swap is diagnosable rather than
silent.

The stream is not sent at all until the netcode handshake on UDP 40000 asks
for it, so any replacement has to sit behind the same relay or bypass it
entirely.
