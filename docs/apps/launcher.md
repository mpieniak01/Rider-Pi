# Legacy interactive CLI

[apps/main.py](../../apps/main.py) is a historical terminal launcher, separate
from the [four-button menu](menu.md). The former apps/launcher/main.py entry
point is absent.

The CLI uses /home/pi/robot/data/flags, can create/remove motion.enable and
estop.on, publishes legacy raw motion messages and can launch trajectory.py
as a child process. Its demo_trajectory_safe name describes the old flag flow;
it does not establish isolation or qualify the current executor safety contract.
Importing the module can create its flags directory.

A file flag is neither operator ARM nor permission for an automated physical
trial. Removing an old estop flag is not an approved way to clear current
E-Stop. Legacy STOP publication is not a terminal executor ACK.

Use [current operator control](../ui/control.md), [motion authority](motion.md)
and [task/service mappings](../TASKS_SERVICES_RESOURCES.md) for device operation.
Inspect this CLI with fake files/processes and an isolated BUS; do not run it
as a software smoke test against a robot. Physical actions require a separate
operator-approved plan.
