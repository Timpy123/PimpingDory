# Storage upgrade

Open the buoy and see whether the 16 GB is an SD card on the board or soldered
eMMC. If it is a card, `dd` it onto a bigger one and see whether the firmware
accepts the result.

## Before opening anything

The manual (p.9) lists `STORAGE 16G` under **BUOY**, not DRONE, so the buoy is
the enclosure to open.

The REST API has `GET /v1/tfcard/sdquery` and `POST /v1/tfcard/format`.
"tfcard" is TransFlash, the old name for microSD — a hint that the firmware at
least thinks in terms of a removable card rather than eMMC.

`./scripts/DoryControl.sh --list` reports what the API says about capacity.
