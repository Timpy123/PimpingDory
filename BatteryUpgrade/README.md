# Battery upgrade

Replace the cells in the **19386-EE-1P3S21700** pack. It is **1P3S**: three
cells in series, one parallel string, so a single cell carries the whole
current.

Candidates:

- **Vapcell 21700 Li-Ion**
- **Keeppower 21700 6000 mAh**

## What the drone says about it

From the parameter dump (`./scripts/DoryTest.sh --identify`):

| parameter | value |
|---|---|
| `BATT_CAPACITY` | 3898 mAh |
| `FS_BATT_VOLTAGE` | 10.5 V low-voltage failsafe |
| `BATT_MONITOR` | 5 — voltage **and** current |
| observed | 12.37 V, consistent with a healthy 3S pack |

There are **two batteries** reported over MAVLink, not one:

| id | reading | almost certainly |
|---|---|---|
| 0 | 12.37 V, 3S | the drone's pack |
| 1 | 3.90 V, single cell | the buoy |

The firmware puts the whole pack voltage in the first cell slot rather than
reporting the three cells individually, so a single failing cell cannot be
spotted from telemetry.

## The number that decides the cell

Capacity and current pull in opposite directions in a 1P pack:

- high-capacity 21700s (5000–6000 mAh) are typically rated **8–10 A continuous**
- high-drain 21700s (Molicel P42A, Samsung 30T, ~4200 mAh) manage **35–45 A**

So the peak draw decides it, and it has to be measured **in water** — a
propeller with nothing to push draws almost nothing. In air the whole drone
pulls about 1 A at full thrust, which says nothing useful.

```sh
sudo -v && ./scripts/DoryTest.sh --maxpower
```

Everything at full for 30 s, a reading every 5 s, then the peak. Note that
this firmware reports discharge as a **negative** current.
