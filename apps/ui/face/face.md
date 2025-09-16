# Rider-Pi: Buźka LCD/PNG

## Szybki start

- CLI: `python3 tools/newface_lcd_direct.py --expr happy --stats`
- API: `POST /face/render` (backend: lcd/png)

## Zmienne środowiskowe
- `RIDER_APPS_PATH` — ścieżka do katalogu apps (domyślnie: `_apps:apps`)
- `FACE_LCD_ROTATE` — rotacja LCD (0/90/180/270)
- `FACE_LCD_SPI_HZ` — prędkość SPI (np. 32000000)
- `FACE_LCD_DRIVER` — sterownik LCD: `auto`, `st7789`, `ili9341` (domyślnie: auto)
- `FACE_LCD_BL_PIN` — pin podświetlenia (domyślnie: 13)

## Komendy i flagi
- `--force {auto,raw,pil}` — wymuś backend (domyślnie auto, ENV: `FACE_LCD_FORCE`)
- `--driver {auto,st7789,ili9341}` — wybór sterownika LCD (ENV: `FACE_LCD_DRIVER`)
- `--stats` — loguj FPS/statystyki
- `--secs` — czas trwania testu
- `--expr` — wyraz buźki: neutral, happy, sad
- `--rotate` — rotacja LCD
- `--spi-hz` — prędkość SPI
- `--bl-pin` — pin podświetlenia
- `--backend` — lcd/png (API)
- `--out` — ścieżka pliku PNG (API)

## Backend LCD/PNG
- LCD: szybka ścieżka RAW (jeśli wspierane przez hardware)
- PNG: generuje plik na dysku (działa zawsze, fallback)

## Przykłady
- LCD: `python3 tools/newface_lcd_direct.py --force raw --driver st7789 --rotate 270 --spi-hz 32000000 --stats --secs 5`
- PNG: `python3 tools/newface_lcd_direct.py --force pil --stats --secs 2`
- API LCD: `curl -X POST http://localhost:5000/face/render -H 'Content-Type: application/json' -d '{"expr":"happy","backend":"lcd"}'`
- API PNG: `curl -X POST http://localhost:5000/face/render -H 'Content-Type: application/json' -d '{"expr":"happy","backend":"png","out":"/tmp/face.png"}'`
## Troubleshooting LCD
- Jeśli nie wykryto LCD lub brak sterownika: sprawdź ENV `FACE_LCD_DRIVER`, podłączone urządzenie, uprawnienia do SPI.
- Fallback do PIL/PNG następuje automatycznie przy braku HW lub błędzie inicjalizacji.
- API zwraca 503 Service Unavailable gdy backend=lcd i brak HW.
## Systemd: rider-face.service
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
