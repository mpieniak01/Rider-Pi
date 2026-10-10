# Rider-Pi motion architecture

Gate v1 describes code; SDK ACK is not physical execution proof.
See [safety](safety.md) and [environments](../ENVIRONMENT_POLICY.md).

## Command path

Pi/PC panel → API :8080 or optional HTTP bridge :8081 →
services.safety_contract → BUS motion.command → apps.motion.executor
(gate/controller/SDK) → UART. Only the executor owns UART for commands and
bounded reads. Its lock and exact ownership probe refuse foreign or unknown
owners. Sensor-reader projects motion.sensors.raw through BUS without SDK.
Panel reads use snapshots; missing telemetry stays null.

Default XgoAdapter is inert without owner and gate. The SDK 1.4.2 write guard
blocks constructor reset/action255; unknown SDK versions fail closed.
motion.main delegates to the executor; the legacy bridge has no hardware owner.
Passive vision never launches driving. Follow needs a matching current task
intent; an old producer cannot capture consent from a new generation.

## Consent and envelope

| State | Meaning |
| --- | --- |
| DISARMED | Reads only; every startup |
| ARMED | Specific plan, owner, lease up to 30 seconds |
| ESTOP | Latched inhibit; separate clear returns DISARMED |
| UNKNOWN | No fresh snapshot; clients block actuation |

ARM/clear require explicit operator_consent, operator_plan and the original
envelope. Owners: manual/follow_me/navigation. Actuators require request_id,
source, generation, increasing seq, ts and ttl_ms 1–500. API and executor
validate independently. Clients use API server_time and never refresh old
commands. Drive/yaw: [-1,1], pulses up to 0.25 seconds. STOP/disarm/E-Stop
need no fresh envelope. STOP changes generation and invalidates goals.
Superseded pending requests receive terminal ACK; goals never replay after ARM.

## Confirmation

GET control/state and safety are reads. Commands use POST; actuating GET is
refused. Legacy aliases cannot bypass envelopes. accepted/HTTP 202 is pending;
executed/confirmed means SDK submission, rejected means refusal/cancel/failure.
physical_completion remains unverified. Terminal ACK matches ID/action/source/
seq and time after dispatch. Snapshots keep a bounded ledger; UI history is not
a motion queue. Missing BUS/ACK is not success. Releasing moving resources
requires confirmed STOP.

## Dynamics and limits

The controller uses dt, ramps and bounded deadlines. Safety STOP immediately
clears targets. Normalized limits are not measured m/s or braking distances.
UART/SDK faults or failed STOP block readiness and subsequent ARM until a new
healthy executor. SDK source verifies velocity-zero writes; height/balance/
canned actions remain unavailable pending manual interruption characterization.
SIGTERM runs cleanup; SIGKILL, UART loss and Pi power loss have no physical STOP
proof. No independent firmware watchdog is asserted.

## Runtime and migration

/run/rider-motion holds status.json, feature_state.json and per-producer
<unit>.json. MOTION_STATE_PATH/FEATURE_STATE_PATH overrides support isolation.
Files survive restart, but a new generation invalidates consent.

UART owner/unit migration needs a separate plan and backups. Ordinary pi-preview
protects drivers/systemd. In an agreed maintenance window without autonomy,
stop the old owner, update selected code/units, reload systemd and start one new
DISARMED owner. Rollback restores matching code and units. Migration never runs
an automatic motion probe. Preserve LCD rotation 270, boot, Wi-Fi and SSH.
