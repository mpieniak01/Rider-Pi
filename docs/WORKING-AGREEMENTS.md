# Working Agreements

---
**Goal:** deliver small, safe increments that work on RPi. Respect existing interfaces. Don't install new dependencies. Keep energy/CPU usage low.

---

## 1) Scope and Responsibility

**You can modify only:**
- `services/**` – service layer (API, bridges, registries, web sockets).
- `apps/**` – applications (UI/face, camera, vision, voice, motion).
- `web/**` – web resources.
- `tests/**` – unit/integration tests.
- `config/**` – configuration files only.
- `Makefile`, `pytest.ini`, `pyproject.toml`.

**You must not:**
- change pins/hardware or `systemd/` units except those listed in `scripts/systemd-sync.sh`,
- add dependencies from outside repo (no online `pip install`),
- run long-lived daemons outside `systemd`,
- send telemetry/exfiltration.

**File size limit:** ≤ 600 lines (soft; if exceeded – split into modules).

---

## 2) Runtime Environment

- **Platform:** Raspberry Pi (Debian/Bookworm), **Python 3.9**.
- **Packages:** only what's in repo and installed via `make setup`.
- **Hardware I/O:**
  - UART `/dev/ttyAMA0` – exclusively via *Motion Bridge*.
  - LCD ILI9xx – via `apps/ui/face/driver_ili9xx.py` (RAW/ShowImage), no direct SPI-write elsewhere.

---

## 3) Interfaces We Don't Break (Contracts)

### HTTP API (8080)
- `GET /healthz` – health check.
- `POST /api/control` – `{action:"move|stop|turn", ...}` (time and range validation).
- `POST /api/chat/*` – voice/chat integration.
- File serving from `data/`, `snapshots/`.

### BUS (ZMQ 5555/5556)
- Example topics: `motion.move|stop|state`, `vision.person|face|motion`, `voice.state`, `face.state`.

### Face Renderer
- `apps/draw/face_primitives.py: draw_face(canvas, cfg, model, guide=False, quality="fast")` – **don't change signature**.
- Pupil: drift+clamp, blink→look coupling – controlled by ENV (see §7).

---

## 4) Definition of Done

- Works on RPi; no regression in API and core paths.
- `pytest` passes locally (`make test`); new features have tests.
- Port/service changes → update `ARCHITECTURE.md`.
- Changes described in `docs/` (summary in commits).

---

## 5) Developer Workflow

- One Issue = one increment.
- Branch: `codex/<nr>-short-description`.
- Commits: `feat|fix|chore(scope): description (nr)`.
- PR: description + *Fixes <nr>* if closing Issue.

**Example:**
```bash
# start
git switch -c codex/42-pupil-drift-tuning

# work
make test  # run local tests

# commit
git commit -m "feat(face): pupil drift clamp improves edge cases (42)"

# PR/push
git push -u origin codex/42-pupil-drift-tuning
```

---

## 6) Testing

- **Quick single-tests** (face examples):
```bash
pytest -q tests/test_renderer_basics.py::test_basic_frame_renders_and_pupils_visible
pytest -q tests/test_pupil_drift.py::test_pupil_drift_changes_bbox
pytest -q tests/test_blink_shift_coupling.py::test_blink_can_trigger_look_when_coupling_enabled
```
- **E2E REST**:
```bash
curl -s http://localhost:8080/healthz | jq .
curl -s -X POST http://localhost:8080/api/control -H 'Content-Type: application/json' \
  -d '{"action":"move","vx":0.4,"yaw":0,"duration":0.2}'
```
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

- Validate `/api/control`: only `move|stop|turn` allowed.
- `SAFE_MAX_DURATION` and `MIN_CMD_GAP` – enforce time and frequency limits.
- When in doubt – **don't execute**; return error and log with parameter suggestion.

---

## 10) Energy Efficiency / Performance

- Vision/Camera – **OFF by default**; enable only when needed.
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
