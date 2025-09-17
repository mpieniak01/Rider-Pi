This is not an official repository for the Rider-PI robot. It is a sandbox for practicing robot programming.

## Face LCD – migracja z _apps i fast-path RAW (mock)

Wersja 2025-09: buźka nie korzysta już z `_apps/ui/face_renderers.py`. Nowy driver (mock domyślny, fast-path RAW RGB565) znajduje się w `apps/ui/face/driver/`.

### Najważniejsze zmiany:
- Brak zależności od `_apps` w ścieżce buźki (czysty import z `apps/`)
- Mock zapisuje `/tmp/face_last.png`, `/tmp/face_last.rgb565`, `/tmp/face_last.meta.json`
- Fast-path RAW RGB565: szybkie wypychanie klatki bezpośrednio do bufora
- Konfiguracja przez ENV lub flagi CLI (`FACE_LCD_ROTATE`, `FACE_LCD_BACKEND`, `FACE_LCD_FIT`)
- Testy i uruchamianie bez sprzętu (mock domyślny)

### Przykładowe komendy (dev/CI, bez sprzętu):

```bash
export RIDER_APPS_PATH="_apps:apps"
export FACE_LCD_BACKEND=mock
export FACE_LCD_ROTATE=270
export FACE_LCD_SPI_HZ=32000000
export FACE_LCD_FIT=fill

python3 -m compileall -q services/api_core/*.py services/api_server.py apps/ui/face/*.py
pytest -q tests/test_face_anim_api.py
pytest -q tests/test_face_raw_fastpath.py
pytest -q tests/test_no_underscore_apps_dependency.py
python3 tools/face_cli.py --expr happy --rotate 270 --force raw:rgb565 --stats
ls -lah /tmp/face_last.*
```

### Wynik działania mocka:
- `/tmp/face_last.png` – wizualizacja ostatniej klatki
- `/tmp/face_last.rgb565` – bufor RAW RGB565 (240x240x2)
- `/tmp/face_last.meta.json` – metadane (rotacja, tryb, timestamp)

### Więcej:
- Szczegóły migracji i testów: patrz `tests/test_face_raw_fastpath.py`, `tests/test_no_underscore_apps_dependency.py`
- Kod drivera: `apps/ui/face/driver/`, konwersje: `apps/ui/face/face_io.py`, konfiguracja: `apps/ui/face/panel_cfg.py`
