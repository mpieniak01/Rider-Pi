# Control API

Robot movement and control endpoints.

## Base Path
`/api/control`

## Endpoints

### POST /api/control
Generic control command endpoint.

**Request Body:**
```json
{
  "type": "drive|stop|spin",
  "lx": 0.5,      // linear velocity (optional, -1.0 to 1.0)
  "az": 0.0,      // angular velocity (optional, -1.0 to 1.0)
  "duration": 0.5 // duration in seconds (optional)
}
```

**Response:**
```json
{
  "ok": true
}
```

**Examples:**

Drive forward:
```bash
curl -X POST http://robot-ip:8080/api/control \
  -H "Content-Type: application/json" \
  -d '{"type": "drive", "lx": 0.5, "az": 0.0}'
```

Stop:
```bash
curl -X POST http://robot-ip:8080/api/control \
  -H "Content-Type: application/json" \
  -d '{"type": "stop"}'
```

Spin left:
```bash
curl -X POST http://robot-ip:8080/api/control \
  -H "Content-Type: application/json" \
  -d '{"type": "spin", "dir": "left", "speed": 0.3, "duration": 0.5}'
```

---

### POST /api/control/balance
Control robot balance/stabilization.

**Request Body:**
```json
{
  "enabled": true  // true to enable, false to disable
}
```

**Response:**
```json
{
  "ok": true,
  "sent": {
    "enabled": true
  }
}
```

**Bus Topic:** `cmd.balance` (TOPIC_MOTION_BALANCE)

**Example:**
```bash
curl -X POST http://robot-ip:8080/api/control/balance \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

---

### POST /api/control/height
Control robot height/suspension.

**Request Body:**
```json
{
  "height": 128  // height value (0-255)
}
```

**Response:**
```json
{
  "ok": true,
  "sent": {
    "height": 128
  }
}
```

**Bus Topic:** `cmd.height` (TOPIC_MOTION_HEIGHT)

**Example:**
```bash
curl -X POST http://robot-ip:8080/api/control/height \
  -H "Content-Type: application/json" \
  -d '{"height": 150}'
```

---

## Legacy Endpoints

### POST /api/move
Direct movement command (legacy format).

**Request Body:**
```json
{
  "vx": 0.5,       // forward/backward velocity
  "vy": 0.0,       // left/right velocity (optional)
  "yaw": 0.0,      // rotation velocity
  "duration": 0.5  // duration in seconds
}
```

### POST /api/stop
Stop robot movement (legacy).

### POST /api/preset
Execute preset movement.

**Request Body:**
```json
{
  "name": "preset_name"
}
```

---

## Implementation

**Module:** `services/api_core/control_api.py`

**Bus Topics Published:**
- `cmd.move` - Movement commands
- `cmd.stop` - Stop command
- `cmd.balance` - Balance control
- `cmd.height` - Height control
- `cmd.preset` - Preset execution

## See Also

- [Navigator API](navigator.md) - Autonomous navigation
- [common/bus.py](../../common/bus.py) - Bus topic definitions
- [Motion Module](../apps/motion.md) - Motion system documentation

## Executor-owned permission and observation freshness

The sole `motion-executor` UART owner is the authority for ARM, DISARMED and ESTOP.
`authorization` describes its permission, owner, execution context, generation and
instance; `execution` describes local readiness and an inhibition reason.
Telemetry freshness, HTTP failures and client connectivity never imply DISARMED.
A stale snapshot retains the last reported permission and original timestamp,
marks `authorization.confirmed=false` and `stale=true`, and cannot claim execution readiness.
Without any valid snapshot, permission is unknown, never implicitly disarmed.

For operator panel sessions, missing sensors or a control timing interruption
stop the current goal without revoking permission. Cancellation invalidates
commands created before that boundary; recovery never replays the old target.
New operator intents are still validated by the executor against permission,
generation, sequence, timestamp/TTL, settings revision and actuator capability.
API and emergency CLI share the same transport and never authorize from a cached GET.
Explicit STOP/disarm, ESTOP, real actuator failures and executor shutdown retain
their existing disarming policy. Startup always starts disarmed.
Test context still requires independent explicit test operator consent.

Manual clients keep the last reported permission visible with an observation
warning. They do not disable direction controls merely because a GET is slow;
they forward fresh bounded intents and display the robot's ACK or refusal.
Permission changes are recorded once in the `motion.permission` log.
