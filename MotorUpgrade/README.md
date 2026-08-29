# Motor upgrade

Replace the thrusters with more powerful ones. Five as standard.

## The layout, from the compute module plug diagram

| plug | thruster |
|---|---|
| 1 | Left Vertical |
| 2 | Left |
| 3 | Rear Vertical |
| 4 | Right |
| 5 | Right Vertical |

**Two horizontal and three vertical. No lateral thruster** — the drone cannot
strafe. That is also why RC channel 5, *lateral* in stock ArduSub, was free for
Chasing to repurpose as the lights.

## What drives them

`RC_SPEED = 490`, so plain PWM at 490 Hz. There is no `MOT_PWM_TYPE`, no
`ESC_*` parameters and no ESC telemetry: the ESCs are dumb output stages that
take a pulse width and report nothing back. No DShot, no OneShot, no RPM
feedback.

`MOT_1..8_DIRECTION` exists for eight channels though only five are used, and
`BRD_PWM_COUNT = 6` — outputs 1–5 the thrusters, output 6 the light.

## Before ordering anything

Measure the peak current first — see `BatteryUpgrade/`. More thrust means more
draw from a 1P pack that already has to deliver it through one cell.
