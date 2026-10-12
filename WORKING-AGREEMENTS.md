# Working Agreements

---
> **Boot is critical:** application work preserves boot, network, SSH/getty and graphics startup. Do not run broad systemd synchronization or vendor boot scripts during a panel update. See [deployment](docs/DEPLOYMENT.md).

**Goal:** deliver safe increments that work on RPi. Respect existing interfaces and keep energy/CPU usage low. Follow the [environment policy](docs/ENVIRONMENT_POLICY.md).

---

## 1) Scope and Responsibility

**You can modify only:**
- `services/**` – service layer (API, bridges, registries, web sockets).
- `apps/**` – applications (UI/face, camera, vision, voice, motion).
- `web/**` – web resources.
- `tests/**` – unit/integration tests.
- `config/**` – configuration files only.
- `scripts/dev_pi-deploy.py` – short preview and application release through Git/SSH.
- `docs/**`, `docs_pl/**`, root guides and documentation rules.
- `Makefile`, `pytest.ini`, `pyproject.toml`.

**You must not:**
- change pins/hardware or `systemd/` units except those listed in `scripts/systemd-sync.sh`,
- install packages ad hoc on the robot; device runtime changes require a separate plan,
- install globally in Ubuntu or into Venom/Rider-PC; fill declared Rider-Pi WSL gaps in its existing `.venv` according to the environment policy,
- run long-lived daemons outside `systemd`,
- send telemetry/exfiltration.

**File size limit:** ≤ 600 lines (soft; if exceeded – split into modules).

---

## 2) Runtime Environment

- **Platform:** Raspberry Pi (Debian 11/Bullseye), **Python 3.9**.
- **Pi packages:** dependencies required by the selected profile, without an automatic test/dev installation.
- **WSL:** reuse the existing Rider-Pi `.venv` for worktrees; use `config/agent/requirements-wsl.txt` and the pip cache. `pyzmq` is required for BUS. A WSL package gap is not a robot limitation.
- **Hardware I/O:**
  - UART `/dev/ttyAMA0` – intended single owner for movement and reads.
    Check ownership before starting a component; see [motion architecture](docs/apps/motion.md).
    Do not open a second adapter on an occupied UART.
  - LCD ILI9xx – shared owner `apps/ui/lcd_sink.py` and `drivers/lcd/driver_ili9xx.py` backend (RAW/ShowImage).
  - LCD mounting is sideways on this robot. Preserve its orientation and the Face
    compensation `FACE_LCD_ROTATE=270`. Splash and Face use `drivers/lcd/board.py`: `FACE_LCD_ROTATE`, then
    `SPLASH_ROTATE`, default 270. `PREVIEW_ROT` affects camera images only.

---

## 3) Interfaces We Don't Break (Contracts)

### HTTP API (8080)
- GET /healthz: health; GET /api/control/state and /api/safety: gate v1 and server_time.
- POST /api/control: actuators require request_id/source/generation/seq/ts/TTL.
- POST /api/safety: explicit plan/consent for ARM/clear; STOP/E-Stop always available.
- POST /api/chat/* and file-serving interfaces remain available.

### BUS (ZMQ 5555/5556)
- Commands: motion.command; state/confirmation: motion.state, motion.ack.
- Legacy actuator topics require the same envelope. Passive tracking cannot authorize motion.

### Face Renderer
- `apps/draw/face_primitives.py: draw_face(canvas, cfg, model, guide=False, quality="fast")` – **don't change signature**.
- Pupil: drift+clamp, blink→look coupling – controlled by ENV (see §7).

---

## 4) Definition of Done

- Works on RPi; no regression in API and core paths.
- Relevant checks pass; confirm hardware functions on the Pi.
- A short iteration can use a relevant WSL test and a device test; full `make test`
  is not mandatory before every preview.
- Release requires PR review and green existing CI checks;
  the version tested on the Pi must match the release.
- Port/service changes → update `ARCHITECTURE.md`.
- Changes described in `docs/` (summary in commits).

---

## 5) Developer Workflow

- One Issue = one increment.
- Branch: `codex/<nr>-short-description`.
- Commits: `feat|fix|chore(scope): description (nr)`.
- PR: description + *Fixes <nr>* if closing Issue.
- Two paths: local commit → `make pi-preview` → Pi function test; then
  push → PR/review → merge → `make pi-release PI_COMMIT=<sha>`.
- Return from preview with `make pi-rollback`. See [deployment](docs/DEPLOYMENT.md).

**Example:**
```bash
# start
git switch -c codex/42-pupil-drift-tuning

# work
# optionally run a short check or relevant WSL test

# commit
git commit -m "feat(face): pupil drift clamp improves edge cases (42)"

# preview and function test on the physical Pi before publication
make pi-preview

# PR/push
git push -u origin codex/42-pupil-drift-tuning
```

---

## 6) Testing


### Test categories — binding rule

- **Automatic:** software tests with mocks/simulation isolated from the real
  robot and its command bus. They must not arm the device.
- **Hardware without movement:** e.g. camera, LCD or telemetry reads; a separate
  scope with confirmation that neither autonomy nor actuators are started.
- **Movement/actuators:** driving, turning, height, balance, actions and any
  scenario that can move the robot — manual tests only after explicit operator
  consent for the specific plan. Never trigger these through automatic
  pytest/E2E/CI, general diagnostics, deployment, schedules or opening a panel.
  Permission for cameras, service startup or deployment is not movement consent.

Consent for one attempt does not arm later tests. Before an attempt, the operator
confirms space, surface, cable and stopping procedure. Diagnostics must not
clear E-Stop or enable movement to make a test work.
- **Quick single-tests** (face examples):
```bash
pytest -q tests/test_renderer_basics.py::test_basic_frame_renders_and_pupils_visible
pytest -q tests/test_pupil_drift.py::test_pupil_drift_changes_bbox
pytest -q tests/test_blink_shift_coupling.py::test_blink_can_trigger_look_when_coupling_enabled
```
- **REST read without movement**:
```bash
curl -s http://localhost:8080/healthz | jq .
```
- Motion tests require prepared hardware and operator consent (section 9).
- **BUS spy:** `python3 scripts/dev_bus-sub.py motion`
- **LCD/PNG demo (face):**
```bash
sudo -E env -u FACE_MOUTH_SHAPE -u FACE_MOUTH_OPEN \
  FACE_IDLE_ENABLE=1 FACE_IDLE_BLINK_SEC=3.4 FACE_IDLE_LOOK_P=0.22 FACE_IDLE_LOOK_SEC=3.4 \
  FACE_GESTURE_LOOK_AMP=0.32 \
  FACE_EYES_FOLLOW_KX=0.12 FACE_EYES_FOLLOW_KY=0.22 \
  FACE_BROW_FOLLOW_KX=0.03 FACE_BROW_FOLLOW_KY=0.06 \
  FACE_PUPIL_DRIFT_AMP_K=0.02 FACE_PUPIL_DRIFT_FREQ=0.8 \
  python3 scripts/dev_face-lcd-direct.py --expr neutral --fps 20 --rotate 270 --secs 8 --stats
```

---

## 7) Facial Expression Configuration (ENV / config knobs)

**ENV (runtime):**
- `FACE_IDLE_ENABLE` (0/1), `FACE_IDLE_BLINK_SEC`, `FACE_IDLE_LOOK_P`, `FACE_IDLE_LOOK_SEC`.
- `FACE_GESTURE_BLINK_DUR`, `FACE_GESTURE_BLINK_HOLD`.
- `FACE_GESTURE_LOOK_T`, `FACE_GESTURE_LOOK_AMP`.
- **Pupil:** `FACE_PUPIL_DRIFT_AMP_K`, `FACE_PUPIL_DRIFT_FREQ`, `FACE_PUPIL_CLAMP_RATIO`.
- **Coupling:** `FACE_BLINK_SHIFT_PROB`.
- **Follow:** `FACE_EYES_FOLLOW_KX/KY`, `FACE_BROW_FOLLOW_KX/KY` (small values!).
- **Debug:** `FACE_DEBUG_MOUTH`.

**`config/face.toml` (for renderer – lowercase keys):**
- `head_ky`, `brow_y_k`, `mouth_y_k`.
- Mouth ribbon: `mouth_ribbon_taper_k`, `mouth_small_th_k_base`.
- Per-shape: `mouth_*_lift_k`, `mouth_*_arch_k`.
- Preserved `FACE_*` aliases for compatibility (loader can map).

> Rule: **preferably modify ENV** for tuning; keep TOML consistent with default styling.

---

## 8) Lint/Format

- **Ruff is quality gate**: `pre-commit` hook runs `ruff check/format` on every commit **and** on CI. Commits with lint errors **are rejected**.
- **Don't bypass** hooks with `--no-verify` (acceptable only locally for WIP – never on `main`).
- **Configuration location**: `pyproject.toml` (don't change rules without justification in PR).
- **Exceptions/suppressions**: prefer local `# noqa: ...` or entry in `per-file-ignores` **only** for tests; avoid global ignores.
- **Rules not auto-fixed**: `unfixable = ["UP006","UP045"]` – don't attempt mass type modernization if it breaks compatibility.

**Quick commands:**
```bash
ruff check apps/ tests/ services/ common/ --statistics
ruff format
```

---

## 9) Security and Validation

- Validate the current `/api/control` contract and validate again at the executor.
- `SAFE_MAX_DURATION` and `MIN_CMD_GAP` – enforce time and frequency limits.
- When in doubt – **don't execute**; return error and log with parameter suggestion.

### Physical robot during development

- The robot may be connected to a power cable. Treat it as unprepared for movement
  until the operator confirms readiness. Describe intended movement/duration/speed,
  then obtain confirmation of space, surface and safe cable routing.
- Driving, turning, height and balance are physical actions. For panel/API changes
  use reads and mocks in the existing local WSL environment.
- Diagnostics must not arm movement or clear E-Stop. Read test/demo effects before
  running it; some scripts change guards.
- `MOTION_ENABLE=0`, `DRY_RUN`, S0/S11 labels and `make stop-all` do not confirm
  a global guard. Deployment preview does not disarm executors.
- Account for acceleration, inertia and braking distance. Ramped ordinary STOP
  and latched emergency STOP have different purposes. Never replay pending
  movement after rearming. See current gaps in [safety](docs/apps/safety.md).

---

## 10) Energy Efficiency / Performance

- Vision/Camera – **OFF by default**; enable only when needed.
- Start voice, tracking and navigation on demand for a specific scenario.
  Check actual processes afterward: stopping a target may leave shared services
  running. Reading battery telemetry is not an automatic movement guard.
- LCD push – use fast-path RAW RGB565 where available.
- Avoid active loops; prefer timers and fixed timing.

---

## 11) Logging

- Concise, with prefixes: `[api]`, `[bridge]`, `[vision]`, `[voice]`, `[face]`.
- No sensitive data; INFO/DEBUG level controlled by ENV.

---

## 12) Concurrency

- One active increment at a time.
- If `.codex.lock` exists – don't introduce changes.

---

## 13) Migration Notes — Face LCD Fast-path (2025-09)

- Removed dependencies on `_apps/ui/face_renderers.py`.
- LCD Driver: `apps/ui/face/driver_ili9xx.py` (mock in CI + SPI in runtime).
- Fast-path RAW RGB565; mock saves PNG/565/meta.
- Panel/rotation config: `apps/ui/face/panel_cfg.py`; I/O: `apps/ui/face/face_io.py`.
- CLI: `scripts/dev_face-lcd-direct.py` and `scripts/dev_face-cli.py`.
- Tests: `tests/test_face_raw_fastpath.py`, `tests/test_no_underscore_apps_dependency.py`.

**Example (mock, fast-path):**
```bash
export FACE_LCD_BACKEND=mock
export FACE_LCD_ROTATE=270
export FACE_LCD_SPI_HZ=32000000
python3 scripts/dev_face-lcd-direct.py --expr neutral --secs 4 --stats
```

---

## 14) PR Checklist (Summary)

- [ ] Changes only in allowed directories.
- [ ] No new dependencies.
- [ ] `pytest` green (locally, key face tests).
- [ ] Lint/format (ruff) performed.
- [ ] `ARCHITECTURE.md` updated if services/ports changed.
- [ ] Logs with prefixes.
- [ ] Comments in commits and link to Issue.

## Documentation

Follow the [documentation policy](docs/DOCUMENTATION_POLICY.md). Task plans and reports stay local.
