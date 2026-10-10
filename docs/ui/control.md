# Tasks and control

Open /control for the single task catalog and explicit motion preparation.
The [operator panel contract](operator-panel.md) defines readiness, safety,
metadata, ACK and keyboard rules.

1. Read the current state and actuator capabilities.
2. Prepare the robot, free space and power cable; write a specific trial plan.
3. Select the owner, confirm preparation and explicitly ARM for at most 30 seconds.
4. Start the corresponding task or send a short manual pulse.
5. Observe the robot separately from SDK ACK; use STOP and end the task.

Manual impulses use normalized values -1..1 and at most 0.25 seconds.
They are requests, not measured speed or distance.
Height, balance and prebuilt actions remain visible and blocked while
manual characterization of safe interruption is required.

W/S/A/D and arrows only operate outside editing fields with fresh manual
permission. Space outside fields sends STOP. Focus, connection or view loss
revokes local permission and attempts STOP. ARM is available directly in
Navigation and System when an action must be performed in those views.

Device preview belongs to /devices; system administration belongs to /system.
Opening a view or choosing a task option never starts a service.
Verification uses isolated fixtures; physical motion requires separate
explicit permission for a prepared operator.
