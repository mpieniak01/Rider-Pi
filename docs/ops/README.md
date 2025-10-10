# Dokumentacja skryptów operacyjnych (`ops/*`)

> Indeks dokumentacji wszystkich skryptów operacyjnych w katalogu `ops/`

## Spis dokumentów

### Główne kategorie

- [**voice-scripts.md**](voice-scripts.md) — skrypty głosowe (voice-run.sh, voice-once.sh)
- [**systemd-scripts.md**](systemd-scripts.md) — zarządzanie usługami systemd
- [**display-scripts.md**](display-scripts.md) — kontrola wyświetlacza LCD i LED
- [**camera-scripts.md**](camera-scripts.md) — zarządzanie kamerą i processami
- [**monitoring-scripts.md**](monitoring-scripts.md) — monitorowanie systemu i metryk
- [**utility-scripts.md**](utility-scripts.md) — narzędzia pomocnicze i demo

## Szybki indeks skryptów

### Skrypty głosowe
- `voice-run.sh` — uruchamianie aplikacji głosowej (legacy z ENV)
- `voice-once.sh` — pojedyncze polecenie głosowe

### Skrypty systemd
- `service_ctl.sh` — bezpieczna kontrola usług systemd (whitelist)
- `systemd_sync.sh` — synchronizacja definicji systemd z repo
- `boot_prepare.sh` — przygotowanie systemu przy starcie

### Skrypty wyświetlacza
- `lcdctl.py` — kontrola LCD (jasność, zasilanie, czyszczenie)
- `ledctl.py` — kontrola diod LED
- `fbgrab.py` — zrzut ekranu z framebuffera
- `splash_device_info.py` — ekran powitalny z info o urządzeniu
- `vendor_splash.py` — ekran powitalny producenta

### Skrypty kamery
- `camera_preview.sh` — uruchomienie preview z kamery
- `camera_takeover_kill.sh` — wymuszenie dostępu do kamery
- `kill_cam.sh` — szybkie zabicie procesów kamery
- `vision_ctl.sh` — kontrola usług wizyjnych

### Skrypty monitoringu
- `monitor_metrics.sh` — monitorowanie metryk systemu
- `monitor_stream.sh` — monitorowanie strumieni

### Skrypty testowe
- `test_suite.sh` — zestaw testów
- `tests_audit.sh` — audyt testów
- `bench_detect.sh` — benchmark detekcji

### Diagnostyka XGO
- `check_xgo_sensors.py` — sprawdzenie czujników XGO
- `xgo_bl_probe.py` — diagnostyka bootloadera XGO
- `xgo_safe_init.py` — bezpieczna inicjalizacja XGO

### Narzędzia pomocnicze
- `export_env.sh` — eksport zmiennych środowiskowych
- `volume_hooks.sh` — hooki głośności
- `services_cleanup.sh` — czyszczenie usług
- `estop.py` — emergency stop
- `demo_lemniscate.py` — demo ruchu w kształcie lemniskaty

## Konwencje skryptów

### Nagłówki

Wszystkie skrypty powinny zawierać:
```bash
#!/usr/bin/env bash
set -euo pipefail  # fail-fast

# Opis skryptu
# Użycie: ./script.sh [args]
```

### Logowanie

Preferowany format logów:
```bash
log() { echo "[$(basename "$0")] $*" >&2; }
log "INFO: Starting process..."
```

### Ścieżki

Używaj absolutnych ścieżek lub wykrywania repo root:
```bash
REPO_ROOT="${REPO_ROOT:-$HOME/robot}"
cd "$REPO_ROOT" || exit 1
```

### Idempotencja

Skrypty powinny być **idempotentne** — wielokrotne uruchomienie daje ten sam rezultat.

## Zasady bezpieczeństwa

### Whitelist

Skrypty zarządzające systemem (systemd, procesy) używają **whitelist** dozwolonych operacji.

Przykład: `service_ctl.sh` akceptuje tylko zdefiniowaną listę usług.

### Nie nadpisuj konfiguracji

Skrypty w `ops/` **czytają** konfigurację z `config/`, ale **nie nadpisują** istniejących wartości ENV.

Zobacz: [docs/CONFIG_POLICY.md](../CONFIG_POLICY.md)

## Helper tools

### load_config.sh (planowane)

Helper dla skryptów do automatycznego ładowania konfiguracji:

```bash
source "$REPO_ROOT/scripts/util_load-config.sh"
setup_voice_env  # automatyczne wykrycie i załadowanie ENV
```

## Uruchamianie skryptów

### Lokalne (development)

```bash
# Z repo root
./scripts/sys_voice-run.sh

# Z dowolnego miejsca (jeśli PATH skonfigurowany)
voice-run.sh
```

### Przez systemd

```bash
# Większość skryptów ma odpowiadające usługi systemd
sudo systemctl start rider-voice.service
```

## Kody wyjścia

Standardowe kody wyjścia zgodne z POSIX:

| Kod | Znaczenie |
|-----|-----------|
| 0 | Sukces |
| 1 | Błąd ogólny |
| 2 | Błędne argumenty |
| 124 | Timeout (traktowany jako sukces w niektórych kontekstach) |
| 127 | Komenda nie znaleziona |

## Diagnostyka

### Sprawdzanie dostępności skryptów

```bash
# Lista wszystkich skryptów ops
ls -la ops/*.sh ops/*.py

# Sprawdź uprawnienia wykonywania
find ops -type f \( -name "*.sh" -o -name "*.py" \) ! -perm -u+x
```

### Logi skryptów

Większość skryptów loguje do:
- `stdout` — normalne wyjście
- `stderr` — błędy i ostrzeżenia
- `/var/log/rider/` — logi systemd services (jeśli skonfigurowane)

---

**Related docs:**
- [CONFIG_POLICY.md](../CONFIG_POLICY.md) — polityka konfiguracji
- [docs/apps/](../apps/) — moduły aplikacyjne
- [docs/config/](../config/) — parametry konfiguracji

**Ostatnia aktualizacja:** 2025-01
