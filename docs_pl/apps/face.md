
# API statycznego renderu buźki Rider-Pi

## Endpointy

### 1. Render PNG do pliku

```bash
curl -s -X POST http://127.0.0.1:8080/face/render -H 'Content-Type: application/json' \
	-d '{"expr":"neutral","backend":"png","out":"/tmp/face_api.png","rotate":270,"size":240}'
ls -l /tmp/face_api.png
```

- `backend`: `png` (alias: `file`, `image`)
- `out`: ścieżka do pliku wyjściowego (wymagana)
- `expr`: wyraz buźki (`neutral`, `happy`, `sad`, ...)
- `rotate`: opcjonalnie obrót (0/90/180/270)
- `size`: rozmiar (domyślnie 240)

### 2. Render LCD (bez HW → 503)

```bash
curl -s -i -X POST http://127.0.0.1:8080/face/render -H 'Content-Type: application/json' \
	-d '{"expr":"neutral","backend":"lcd"}' | head -n 1
```

- Bez sprzętu LCD zawsze HTTP 503 i `{ok:false,status:503,error:"LCD backend not available on this host"}`

### 3. Legacy kompat: /api/draw/face

```bash
curl -s -X POST http://127.0.0.1:8080/api/draw/face -H 'Content-Type: application/json' \
	-d '{"expr":"neutral","backend":"png","out":"/tmp/legacy.png"}'
ls -l /tmp/legacy.png
```

- Z `backend:"lcd"` → HTTP 503

## Port i środowisko

- Domyślny port: **8080** (kontraktowy, można nadpisać `STATUS_API_PORT` lub `API_PORT`)
- Globalny CORS (`Access-Control-Allow-Origin: *`)
- ENV: `STATUS_API_PORT`, `API_PORT`, `FACE_*`

## Zachowanie

- `/face/ping` → `{ok:true}`
- `/face/render` (PNG) → plik na dysku
- `/face/render` (LCD, bez HW) → 503
- `/api/draw/face` → pełna kompatybilność legacy

## Poza zakresem

- Animacje/FaceLoop, TTS, visemy, sterownik LCD RAW
- Brak `/face/state`
- Plik unit: `systemd/rider-face.service`
- Domyślnie wyłączony: `sudo systemctl disable rider-face.service`
- Włącz: `sudo systemctl enable rider-face.service && sudo systemctl start rider-face.service`
- Edytuj parametry przez ENV w `systemd/robot.env` (np. `FACE_LCD_ROTATE`, `FACE_LCD_DRIVER`)

## Testy
- `pytest -q tests/test_face_render_pupil.py tests/test_face_render_rotation.py tests/test_sink_lcd_path.py`
- Compile-check: `python -m compileall -q $(git ls-files '*.py')`

## API
- `GET /face/ping` → `{ok:true}`
- `POST /face/render` → `{ "expr": "happy", "rotate": 0, "spi_hz": 32000000, "backend": "lcd|png", "out": "/tmp/face.png" }`

## Uwagi
- Importy bez side-effectów (żaden import nie wywołuje LCD)
- Fallback PNG działa zawsze
