# Faza 5 — sink LCD RAW dla animacji twarzy

## Konfiguracja środowiska (ENV)

- `FACE_SINK=file|lcd|null` — wybór sinka (przeważa nad FACE_LCD_ENABLE)
- `FACE_LCD_ENABLE=0|1` — włączenie LCD (legacy)
- `FACE_LCD_SPI_HZ=32000000` — prędkość SPI
- `FACE_LCD_ROTATE=0|90|180|270` — rotacja
- `FACE_LCD_BL_PIN=...` — pin podświetlenia
- `FACE_LCD_DRIVER=auto` — wybór sterownika

## Przykłady użycia

**File sink (debug):**
```bash
export FACE_SINK=file
PYTHONPATH=. python3 -m services.api_server &
curl -s -X POST http://127.0.0.1:8080/face/play -H 'Content-Type: application/json' \
  -d '{"expr":"happy","fps":20,"sink":"file"}'
sleep 3
ls -l /tmp/face_latest.png
```

**LCD sink:**
```bash
export FACE_SINK=lcd
PYTHONPATH=. python3 -m services.api_server &
curl -s -X POST http://127.0.0.1:8080/face/play -H 'Content-Type: application/json' \
  -d '{"expr":"happy","fps":20,"sink":"lcd"}'
```

## Troubleshooting

- Brak LCD: `/face/play` z `sink=lcd` zwraca 503 i komunikat `LCD not available`.
- FileSink: `/tmp/face_latest.png` nie pojawia się — sprawdź uprawnienia.
- Legacy API (`/face/render`, `/api/draw/face`): nadal działa (PNG out).

## API

- `/face/play` — obsługuje `sink` w payloadzie ("lcd", "file", "null").
- `/face/stop`, `/face/state` — bez zmian.
- `/face/render`, `/api/draw/face` — PNG out.

## Brak regresji

- Port API: 8080
- Globalny CORS: włączony
- Brak crashy przy braku HW
