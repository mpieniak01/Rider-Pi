# CONTRIBUTING — zasady pisania kodu (Rider-Pi)

## Filozofia
- **Cienkie routery / entrypointy** (`services/api_server.py`, `apps/*/main.py`):
  tylko routing + walidacja + delegacja. **Zero** logiki domenowej tutaj.
- **Funkcje zamiast klas**, jeśli stan nie jest potrzebny.
- **Podział na moduły**: jeśli plik > **600 linii** (preferujemy ≤ 400), rozbij na mniejsze i przenieś logikę do `services/api_core/*` albo lokalnych `*_utils.py`.
- **Kod sprzętowy** (GPIO/Camera/UART/cv2) trzymamy w `*_bridge.py` / `drivers/`. Warstwa HTTP nie importuje bezpośrednio sprzętu.

## Struktura warstw
- `services/api_server.py` → routing i walidacja → woła funkcje z `services/api_core/*`.
- `services/api_core/*` → logika domenowa (state, sysinfo, control, vision, services).
- `apps/*` → procesy narzędziowe i integracje (motion, camera, ui).
- `*_bridge.py` / `drivers/*` → dostęp do sprzętu (UART, kamera, GPIO).

## Styl
- Python 3.11, `ruff` jako linter/formatter (pliki konfig: `ruff.toml`).
- Importy: stdlib → third-party → lokalne. Nazwy funkcji: `czasownik_rzeczownik()` (np. `load_config()`, `render_face()`).
- Publiczne funkcje mają krótkie **docstringi** (Google/NumPy style).
- Długie linie (E501) na razie **nie blokują** — porządkujemy stopniowo.

## Budżet plików
- Plik ≤ **600 linii** (preferujemy ≤ 400). Jeśli rośnie → wynoś funkcje do modułów.

## Testy i CI
- CI: `.github/workflows/ci.yml` (ruff + lekkie pytesty). Linty mogą być nieblokujące.
- Smoke-test lokalny (po zmianach w API):
  ```bash
  ./ops/systemd_sync.sh
  sudo systemctl daemon-reload
  sudo systemctl restart rider-api.service
  curl -s 127.0.0.1:8080/healthz
  curl -s 127.0.0.1:8080/state
  curl -s 127.0.0.1:8080/sysinfo
  curl -s -X POST 127.0.0.1:8080/api/control -H 'Content-Type: application/json' -d '{"cmd":"move","dir":"forward","v":0.15,"t":0.10}'
  curl -s -X POST 127.0.0.1:8080/api/control -H 'Content-Type: application/json' -d '{"cmd":"stop"}'
