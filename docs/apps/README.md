# Application guide index

Modules under apps/ implement robot applications; HTTP orchestration and
resource ownership are documented separately. A module's presence does not
mean it is enabled, installed or physically qualified.

| Area | Guides |
| --- | --- |
| Operator and execution | [Motion](motion.md), [safety](safety.md), [manual physical acceptance](physical-motion.md), [calibration](calibration.md), [conversation commands](agent-control.md) |
| Vision | [Camera](camera.md), [camera source OFF](camera-source-off.md), [vision](vision.md), [perception models](perception-models.md), [navigation profiles](navigation-profiles.md) |
| Navigation and observation | [Navigator](navigator.md), [mapper](mapper.md), [odometry](odometry.md), [system telemetry](system-telemetry.md) |
| Voice and text | [Voice](voice.md), [chat](chat.md), [NLU](nlu.md) |
| Display and input | [Drawing](draw.md), [hardware sink](hw.md), [UI](ui.md), [face](face.md), [LCD ownership](face-lcd.md), [launcher](launcher.md), [menu](menu.md) |
| Software scenarios | [Choreographer](choreographer.md), [demos](demos.md), [simulator](simulator.md) |

Use the [task/service/resource catalogue](../TASKS_SERVICES_RESOURCES.md) and
[systemd mapping](../SYSTEMD_SERVICES_MAPPING.md) for actual launch units.
There is no universal rider-<module>.service or python -m apps.<name> command.
Preserve one UART/LCD owner; opening a guide or panel never starts a task.

Automatic checks use the existing WSL virtualenv, isolated BUS and explicit
hardware mocks. A demo name or DRY_RUN flag alone is not physical isolation.
[Environment policy](../ENVIRONMENT_POLICY.md) · [Configuration](../config/README.md) ·
[Operational scripts](../ops/README.md).
