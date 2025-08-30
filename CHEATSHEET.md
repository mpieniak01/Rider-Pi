# Rider‑Pi — CHEATSHEET.md (quick ops)

_As of: 2025‑08‑30 · status_api.py: REST `/api/*` · Repo path: `/home/pi/robot`_

This is a practical, copy‑paste guide for starting the **web API/dashboard**, running **camera modes & tracking**, killing stuck camera/LCD, and running **smoke/bench tests**. It mirrors our current repo layout and scripts.

---

## 0) Session setup (recommended)
```bash
cd /home/pi/robot
export BUS_PUB_PORT=5555
export BUS_SUB_PORT=5556
export STATUS_API_PORT=8080
export PREVIEW_ROT=270
export SKIP_V4L2=1
```

---

## 1) Web — Status API + dashboard + control
```bash
python3 scripts/status_api.py
# Open:
#  Dashboard  → http://<pi>:8080/
#  Control    → http://<pi>:8080/control
#  SSE events → http://<pi>:8080/events (vision.*, camera.*)
#  Snapshots  → http://<pi>:8080/snapshots/cam.jpg
```

### REST control endpoints (new)
```bash
# Move: JSON {vx, vy, yaw, duration}
curl -s -X POST http://<pi>:8080/api/move \
  -H 'Content-Type: application/json' \
  -d '{"vx":0.6,"vy":0,"yaw":0,"duration":0.8}'

# Stop
curl -s -X POST http://<pi>:8080/api/stop -H 'Content-Type: application/json' -d '{}'

# Preset macro
curl -s -X POST http://<pi>:8080/api/preset \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo_square"}'

# Voice (TTS/command bus)
curl -s -X POST http://<pi>:8080/api/voice \
  -H 'Content-Type: application/json' \
  -d '{"text":"cześć Rider"}'
```
> **Topics published by API:** `cmd.move`, `cmd.stop`, `cmd.preset`, `cmd.voice`

---

## 2) Camera — preview / detection / hybrid tracking
### 2.1 Fast face (HAAR) preview (~15 FPS @320×240)
```bash
python3 apps/camera/preview_lcd_takeover.py
```

### 2.2 Object detection (SSD; e.g., `person`) (~5 FPS)
```bash
export SSD_CLASSES="person"   # comma‑list, e.g. "person,dog"
export SSD_SCORE=0.5           # threshold
export SSD_EVERY=2             # detect every N frames
python3 apps/camera/preview_lcd_ssd.py
```

### 2.3 Hybrid (SSD + tracker KCF/CSRT + HAAR) (~4–6 FPS)
```bash
python3 apps/camera/preview_lcd_hybrid.py
```

### 2.4 Wrapper (quick preview)
```bash
bash scripts/camera_preview.sh
```

---

## 3) Kill camera / free SPI (when preview is stuck)
```bash
bash scripts/camera_takeover_kill.sh
```

---

## 4) LCD backlight on/off
```bash
python3 scripts/lcdctl.py off   # turn LCD off
python3 scripts/lcdctl.py on    # turn LCD on
```
> Keep LCD on after tests: run smoke test with `KEEP_LCD=1`.

---

## 5) Smoke tests (automated sanity)
```bash
# Default
bash scripts/smoke_test.sh

# Recommended flags
PREVIEW_ROT=270 SKIP_V4L2=1 bash scripts/smoke_test.sh
KEEP_LCD=1 bash scripts/smoke_test.sh
PREVIEW_ROT=270 SKIP_V4L2=1 KEEP_LCD=1 bash scripts/smoke_test.sh
```

---

## 6) Bench detection FPS (logs)
```bash
BENCH_LOG=1 bash scripts/bench_detect.sh
# thresholds: HAAR≥12 FPS, SSD≥4 FPS, HYBRID≥3 FPS
```

---

## 7) Motion bridge + quick command tests
```bash
# Motion bridge (DRY RUN by default): listens on cmd.move/cmd.stop/...
python3 scripts/motion_bridge.py

# CLI test sequence: forward → turn_left → stop
python3 scripts/send_cmd.py

# Or use the web Control panel (calls /api/move and /api/stop)
```
> Ensure `motion_bridge.py` subscribes to **`cmd.move`, `cmd.stop`, `cmd.preset`, `cmd.voice`** (not `cmd.motion.*`).

---

## 8) Events stream & system health
```bash
# SSE events in terminal
curl -N http://localhost:8080/events

# Health
curl -s http://localhost:8080/healthz | jq .

# Sysinfo + CPU/MEM history
curl -s http://localhost:8080/sysinfo | jq .
```

---

## 9) Troubleshooting quick fixes
```bash
# 1) Free camera/SPI if busy
bash scripts/camera_takeover_kill.sh

# 2) Toggle LCD
python3 scripts/lcdctl.py off; sleep 1; python3 scripts/lcdctl.py on

# 3) Check API live
curl -s http://localhost:8080/healthz | jq .
```

---

## 10) Env var reference (current)
- **Bus/API:** `BUS_PUB_PORT=5555`, `BUS_SUB_PORT=5566` *(u nas XPUB 5556; PUBLISH 5555)*, `STATUS_API_PORT=8080`
- **Camera/Vision:** `PREVIEW_ROT=270`, `SKIP_V4L2=1`, `SSD_EVERY`, `SSD_SCORE`, `SSD_CLASSES`, `DISABLE_LCD=1`, `NO_DRAW=1`
- **LCD:** `FACE_LCD_SPI_HZ=12000000`
- **Vision dispatcher:** `VISION_ON_CONSECUTIVE`, `VISION_OFF_TTL_SEC`, `VISION_MIN_SCORE`
- **Motion/UX:** `MOTION_ENABLE=1`, `BUTTONS_SIM=1`
- **Bench:** `BENCH_LOG=1`, `KEEP_LCD=1`

