# Resource diagnostics

See the [task and resource contract](TASKS_SERVICES_RESOURCES.md) for ownership,
states and the installation migration.

## Inspection

`GET /api/resource/<camera|mic|speaker|lcd|uart>` reports exact device paths,
observed PIDs, owning systemd units, consumers and `observed_at`.
It never initializes the robot SDK or changes a process.

| State | Meaning | free |
| --- | --- | --- |
| free | Successful ownership observation with no holder | true |
| busy | One or more observed holders | false |
| unavailable | No matching device path | null |
| unknown | Ownership could not be read reliably | null |

Camera paths are V4L2 `/dev/videoN`; SPI/framebuffers belong to LCD.
UART is a separate resource, reserved for the sole motion executor.
The sensor reader consumes BUS telemetry.

The CLI provides the same inspection:

```bash
./scripts/resource_diag.py status camera
./scripts/resource_diag.py status uart
```

## Stop and manual recovery

Stop the owning task through its task API first. Shared consumers keep their units
until the last task stops. A moving task requires confirmed STOP before releasing
services. Administration refuses to stop a unit leased by another task.

`POST {"action":"stop"}` on the resource endpoint stops only catalogued services
whose metadata includes that resource. Unknown owners/read failures are refused.
All requested steps must complete before the operation reports success.

Release is a separate, explicitly reviewed recovery. It requires `force: true`,
`operator_consent: true` and exact currently observed PIDs. The response lists
owners, consumers and effects; active task consumers prevent release.
The command sends SIGTERM only to the selected owners. It does not escalate to
SIGKILL or automatically start another service. UART, LCD and base units are protected.

```bash
# Only after reviewing owners and stopping their tasks:
./scripts/resource_diag.py release camera --pid 1234 --force --operator-consent
```

## Camera feed and guard

RAW capture owns the camera; frame-distributor supplies consumers including PC
offload. Offload cannot fall back to a second physical camera owner.
`vision-resource-guard.sh claim|release` checks these conditions read only.
It neither kills another owner nor resumes preview. RAW/EDGE/SSD conflicts are
refused; select one tool through the task API.

Automated checks use fake ownership and processes. Physical motion trials require
operator consent for the exact plan; viewing camera data does not grant that consent.
