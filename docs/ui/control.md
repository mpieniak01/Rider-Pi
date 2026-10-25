# Tasks and control

Open /control for the single task catalog and explicit motion preparation.
The [operator panel contract](operator-panel.md) defines readiness, safety,
metadata, ACK and keyboard rules.

1. Read the current state and actuator capabilities.
2. Prepare the robot, free space and power cable; write a specific trial plan.
3. Confirm preparation and explicitly ARM the operator/manual panel session.
   It has no lease timer; timed test/navigation sessions remain separate.
4. Start the corresponding task or send a short manual pulse.
5. Observe the robot separately from SDK ACK; use STOP and end the task.

Manual pulses use Pi-owned directional settings, normalized values -1..1
and a duration of 0.01–1.0 s (initial default 0.25 s). Read the live descriptor.
They are requests, not measured speed or distance.
Height and roll balance use their advertised position/mode capability.
Manufacturer actions remain blocked pending interruption characterization.

W/S/A/D and arrows only operate outside editing fields with fresh manual
permission. Space outside fields sends STOP. Focus loss, a hidden page
or release ends a held intent; it does not automatically disarm the operator.
Missing hold renewals stop movement through the Pi watchdog.
[Panel ownership](../manual-panel-authority.md) prevents another panel from
renewing or releasing the holder’s command. ARM is available directly in
Navigation and System when an action must be performed in those views.

Device preview belongs to /devices; system administration belongs to /system.
Opening a view or choosing a task option never starts a service.
Verification uses isolated fixtures; physical motion requires separate
explicit permission for a prepared operator.
