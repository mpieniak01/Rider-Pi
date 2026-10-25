# Legacy trajectory demonstrations

The producer [apps/demos/trajectory.py](../../apps/demos/trajectory.py) remains
a historical example. It publishes raw type=drive lx/az messages on a legacy
topic; it does not construct the current safety envelope or obtain a task
generation. It is not a validated automatic physical test and does not establish
an authorized path through the current executor.

## Behavior and configuration

The sequence is forward, right spin, backward, then a legacy stop message.
_drive_for publishes repeatedly; finally attempts another stop publication.
That publication is not an executor ACK or proof of physical stopping.

| Variable | Default |
| --- | --- |
| BUS_PUB_ADDR | tcp://127.0.0.1:5555 |
| MOTION_TOPIC | motion |
| DEMO_RATE_HZ | 10 |
| DEMO_SPEED_FWD / DEMO_SPEED_ROT | 0.25 |
| DEMO_SEG_SEC | 2.0 |

These are normalized example commands, not physical velocity or a qualified
maneuver. A variable named MOTION_ENABLE=0 does not isolate a live BUS or robot.
Software inspection requires an explicitly isolated broker/consumer and fake
outputs. Do not launch a second UART owner to make this example work.

Current physical control uses [motion authority](motion.md),
[manual settings](calibration.md) and the operator's separate trial consent.
[Simulator](simulator.md) · [task catalogue](../TASKS_SERVICES_RESOURCES.md).
