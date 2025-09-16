# Rider-Pi: Buźka LCD/PNG

## Szybki start

- CLI: `python3 tools/newface_lcd_direct.py --expr happy --stats`
- API: `POST /face/render` (backend: lcd/png)

## Zmienne środowiskowe
- `RIDER_APPS_PATH` — ścieżka do katalogu apps (domyślnie: `_apps:apps`)
- `FACE_LCD_ROTATE` — rotacja LCD (0/90/180/270)
- `FACE_LCD_SPI_HZ` — prędkość SPI (np. 32000000)

## Komendy i flagi
- `--force-raw` — wymuś tryb RAW RGB565 (jeśli wspierane)
- `--force-pil` — wymuś tryb PIL (fallback)
- `--stats` — loguj FPS co ~1s
- `--expr` — wyraz buźki: neutral, happy, sad
- `--rotate` — rotacja LCD
- `--spi-hz` — prędkość SPI
- `--backend` — lcd/png (API)
- `--out` — ścieżka pliku PNG (API)

## Backend LCD/PNG
- LCD: szybka ścieżka RAW (jeśli wspierane przez hardware)
- PNG: generuje plik na dysku (działa zawsze, fallback)

## Przykłady
- LCD: `python3 tools/newface_lcd_direct.py --force-raw --stats`
- PNG: `curl -X POST http://localhost:5000/face/render -H 'Content-Type: application/json' -d '{"expr":"happy","backend":"png","out":"/tmp/face.png"}'`

## Testy
- `pytest -q tests/test_face_render_pupil.py tests/test_face_render_rotation.py tests/test_sink_lcd_path.py`
- Compile-check: `python -m compileall -q $(git ls-files '*.py')`

## API
- `GET /face/ping` → `{ok:true}`
- `POST /face/render` → `{ "expr": "happy", "rotate": 0, "spi_hz": 32000000, "backend": "lcd|png", "out": "/tmp/face.png" }`

## Uwagi
- Importy bez side-effectów (żaden import nie wywołuje LCD)
- Fallback PNG działa zawsze
