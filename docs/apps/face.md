# Rider-Pi Static Face Render API

## Endpoints

### 1. Render PNG to File

```bash
curl -s -X POST http://127.0.0.1:8080/face/render -H 'Content-Type: application/json' \
	-d '{"expr":"neutral","backend":"png","out":"/tmp/face_api.png","rotate":270,"size":240}'
ls -l /tmp/face_api.png
```

- `backend`: `png` (alias: `file`, `image`)
- `out`: output file path (required)
- `expr`: face expression (`neutral`, `happy`, `sad`, ...)
- `rotate`: optional rotation (0/90/180/270)
- `size`: size (default 240)

### 2. Render LCD (without HW → 503)

```bash
curl -s -i -X POST http://127.0.0.1:8080/face/render -H 'Content-Type: application/json' \
	-d '{"expr":"neutral","backend":"lcd"}' | head -n 1
```

- Without LCD hardware always returns HTTP 503 and `{ok:false,status:503,error:"LCD backend not available on this host"}`

### 3. Legacy Compatibility: /api/draw/face

```bash
curl -s -X POST http://127.0.0.1:8080/api/draw/face -H 'Content-Type: application/json' \
	-d '{"expr":"neutral","backend":"png","out":"/tmp/legacy.png"}'
ls -l /tmp/legacy.png
```

- With `backend:"lcd"` → HTTP 503

## Port and Environment

- Default port: **8080** (contractual, can override with `STATUS_API_PORT` or `API_PORT`)
- Global CORS (`Access-Control-Allow-Origin: *`)
- ENV: `STATUS_API_PORT`, `API_PORT`, `FACE_*`

## Behavior

- `/face/ping` → `{ok:true}`
- `/face/render` (PNG) → file on disk
- `/face/render` (LCD, without HW) → 503
- `/api/draw/face` → full legacy compatibility

## Out of Scope

- Animations/FaceLoop, TTS, visemes, RAW LCD driver
- No `/face/state`
- Service catalog version 2 does not install `rider-face` or other legacy units.
- S11 selects one camera tool; LCD uses the preserved renderer service.
- `systemd-sync.sh` prints a plan; `--with-dev` is compatibility only.
- See [task and resource contract](../TASKS_SERVICES_RESOURCES.md).
- Edit parameters via ENV in `systemd/robot.env` (e.g., `FACE_LCD_ROTATE`, `FACE_LCD_DRIVER`)
- In `/healthz`, `ownership_state` describes resource holders. A successful
  `lsof` read does not prove LCD power. `on` stays `null` and `power_known=false`
  until an explicit renderer report; `configured_on` describes configuration only.
  Recovered ownership after an inspection error does not mark the display as on.

## Tests

- `pytest -q tests/test_face_render_pupil.py tests/test_face_render_rotation.py tests/test_sink_lcd_path.py`
- Compile-check: `python -m compileall -q $(git ls-files '*.py')`

## API

- `GET /face/ping` → `{ok:true}`
- `POST /face/render` → `{ "expr": "happy", "rotate": 0, "spi_hz": 32000000, "backend": "lcd|png", "out": "/tmp/face.png" }`

## Notes

- Imports without side-effects (no import triggers LCD)
- PNG fallback always works
