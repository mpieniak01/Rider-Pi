
# API statycznego renderu buźki Rider-Pi

## Endpointy

### 1. Render PNG do pliku

```bash
curl -s -X POST http://127.0.0.1:8080/face/render -H 'Content-Type: application/json' \
	-d '{"expr":"neutral","backend":"png","out":"/tmp/face_api.png","rotate":270,"size":240}'
ls -l /tmp/face_api.png
```

- `backend`: `png` (alias: `file`, `image`)
- `out`: `face.png` lub `face_<nazwa>.png` bezpośrednio w `FACE_RENDER_DIR` (domyślnie `/tmp`); [ograniczenia eksportu](../api-specs/security.md).
- `expr`: wyraz buźki (`neutral`, `happy`, `sad`, ...)
- `rotate`: opcjonalnie obrót (0/90/180/270)
- `size`: rozmiar 16–1024 (domyślnie 240)

### 2. Render LCD (bez HW → 503)

```bash
curl -s -i -X POST http://127.0.0.1:8080/face/render -H 'Content-Type: application/json' \
	-d '{"expr":"neutral","backend":"lcd"}' | head -n 1
```

- Bez sprzętu LCD zawsze HTTP 503 i `{ok:false,status:503,error:"LCD backend not available on this host"}`

### 3. Legacy kompat: /api/draw/face

```bash
curl -s -X POST http://127.0.0.1:8080/api/draw/face -H 'Content-Type: application/json' \
	-d '{"expr":"neutral","backend":"png","out":"/tmp/face_legacy.png"}'
ls -l /tmp/face_legacy.png
```

- Z `backend:"lcd"` → HTTP 503

## Port i środowisko

- Domyślny port: **8080** (kontraktowy, można nadpisać `STATUS_API_PORT` lub `API_PORT`)
- Origin/CORS według [wspólnej granicy HTTP](../api-specs/security.md); dodatkowe klienty w `RIDER_ALLOWED_ORIGINS`.
- ENV: `STATUS_API_PORT`, `API_PORT`, `FACE_*`

## Zachowanie

- `/face/ping` → `{ok:true}`
- `/face/render` (PNG) → plik na dysku
- `/face/render` (LCD, bez HW) → 503
- `/api/draw/face` → pełna kompatybilność legacy

## Poza zakresem

- Animacje/FaceLoop, TTS, visemy, sterownik LCD RAW
- Brak `/face/state`
- Katalog usług wersji 2 nie instaluje `rider-face` ani innych jednostek legacy.
  S11 wybiera jedno narzędzie kamery; LCD korzysta z zachowanej usługi renderera.
  `systemd-sync.sh` pokazuje plan, a `--with-dev` jest wyłącznie opcją kompatybilności.
  Zobacz [kontrakt zadań i zasobów](../ZADANIA_USLUGI_ZASOBY.md).
- Edytuj parametry przez ENV w `systemd/robot.env` (np. `FACE_LCD_ROTATE`, `FACE_LCD_DRIVER`)
- W `/healthz` `ownership_state` opisuje właścicieli zasobu. Udany odczyt `lsof`
  nie dowodzi zasilania LCD. `on` pozostaje `null`, a `power_known=false`, dopóki
  renderer nie zgłosi jawnego stanu; `configured_on` opisuje tylko konfigurację.
  Po błędzie inspekcji sam powrót znanej własności nie ustawia ekranu jako włączony.

## Testy
- `pytest -q tests/test_face_render_pupil.py tests/test_face_render_rotation.py tests/test_sink_lcd_path.py`
- Compile-check: `python -m compileall -q $(git ls-files '*.py')`

## API
- `GET /face/ping` → `{ok:true}`
- `POST /face/render` → `{ "expr": "happy", "rotate": 0, "spi_hz": 32000000, "backend": "lcd|png", "out": "/tmp/face.png" }`

## Uwagi
- Importy bez side-effectów (żaden import nie wywołuje LCD)
- Fallback PNG zapisuje plik, gdy katalog docelowy spełnia wymagania bezpieczeństwa.

## Bezpieczne pliki podglądu i narzędzi offline

Mock LCD (także import kompatybilności `apps.ui.face.driver.mock`) zachowuje
pliki `/tmp/face_last.png`, `.rgb565` i `.meta.json`. Symulator zachowuje
`/tmp/lcd_sim_<numer>.*`, a backend PNG i fallback buźki respektują `FACE_OUTFILE`.
Te zapisy oraz PNG narzędzia pogodowego używają atomowej publikacji plików
z prawami `0600`. Dowiązanie w miejscu pliku wynikowego nie jest otwierane;
dowiązania w katalogach oraz niezaufane katalogi są odrzucane. Błąd kodera
pozostawia poprzedni kompletny plik. Czytniki podglądu powinny działać jako ten
sam użytkownik co proces zapisujący.

`dev_face-cli.py --stats` odczytuje artefakty wybranego sterownika mock,
wyłącznie własne zwykłe pliki, bez dowiązań
symbolicznych i twardych ani zapisu grupowego/publicznego. Metadane JSON mają
limit 64 KiB; niebezpieczny lub niepoprawny artefakt daje komunikat diagnostyczny.
Nazwy plików i orientacja LCD pozostają zgodne z konfiguracją.
