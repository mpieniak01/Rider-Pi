# Four-button menu

The maintained four-button implementation is
[apps/menu/main.py](../../apps/menu/main.py). apps/launcher/main.py was removed;
do not use it as a launch command. The separate [legacy CLI](launcher.md) is
apps/main.py and has different behavior.

The menu subscribes to ui.button and motion.state. It handles id=LEFT|RIGHT|OK|BACK
with event=down; LEFT/RIGHT wrap the cursor, OK selects and BACK requests STOP.
It publishes system.menu.state about once per second and system.mode on selection.

| Item | Intent |
| --- | --- |
| Dema | STOP then system.mode=demos, demo=trajectory |
| Autonomia | STOP then system.mode=autonomy |
| Teleop | STOP then system.mode=teleop |
| Ustawienia / Logi | Placeholders, no implemented action |

STOP uses motion.command with action=stop, source=manual, origin=physical_menu
and a fresh request_id. Publication alone is not confirmation of physical stop.
The menu does not grant ARM or manufacture current command generations.

A fresh battery observation below 0.15 blocks the Dema/Autonomia selection.
Missing battery is represented as unknown; this menu check is not a complete
safety admission policy. Consumers and the current executor remain authoritative.
The module uses common.bus/ZeroMQ, not just the standard library.

[Button input](ui.md) · [Motion authority](motion.md) ·
[Actual task/service mappings](../TASKS_SERVICES_RESOURCES.md).
Tests must isolate the BUS because a menu intent can trigger a consumer.
