# Dokumentacja skryptów operacyjnych

> Indeks dokumentacji wszystkich skryptów operacyjnych (obecnie w katalogu `scripts/`)

> **Uwaga:** Skrypty zostały przeniesione z `ops/` i `tools/` do `scripts/` z ujednoliconą konwencją nazewnictwa. Zobacz [../scripts/README.md](../../scripts/README.md) dla szczegółów migracji.

## Spis dokumentów

### Główne kategorie

- [**voice-scripts.md**](voice-scripts.md) — skrypty głosowe (voice-run.sh, voice-once.sh)
- [**systemd-scripts.md**](systemd-scripts.md) — zarządzanie usługami systemd
- [**display-scripts.md**](display-scripts.md) — kontrola wyświetlacza LCD i LED
- [**camera-scripts.md**](camera-scripts.md) — zarządzanie kamerą i processami
- [**monitoring-scripts.md**](monitoring-scripts.md) — monitorowanie systemu i metryk
- [**utility-scripts.md**](utility-scripts.md) — narzędzia pomocnicze i demo

## Szybki indeks skryptów

> Wszystkie skrypty znajdują się teraz w katalogu `scripts/` z prefiksami kategorii.  
> Pełna lista i konwencja nazewnictwa: [scripts/README.md](../../scripts/README.md)

### Skrypty głosowe (prefiks `sys_`)
- `sys_voice-run.sh` — uruchamianie aplikacji głosowej (legacy z ENV)
- `sys_voice-once.sh` — pojedyncze polecenie głosowe
- `sys_voice-stream.sh` — tryb strumieniowy głosu

### Skrypty systemd (prefiks `sys_`)
- `sys_control.sh` — bezpieczna kontrola usług systemd (whitelist)
- `ops/systemd-sync.sh` — synchronizacja definicji systemd z repo (pozostało w ops/)
- `sys_boot-prepare.sh` — przygotowanie systemu przy starcie

### Skrypty wyświetlacza (prefiks `sys_`)
- `sys_lcd-control.py` — kontrola LCD (jasność, zasilanie, czyszczenie)
- `sys_led-control.py` — kontrola diod LED
- `diag_framebuffer-grab.py` — zrzut ekranu z framebuffera
- `sys_splash-info.py` — ekran powitalny z info o urządzeniu
- `sys_vendor-splash.py` — ekran powitalny producenta

### Skrypty kamery (prefiks `sys_`)
- `sys_camera-preview.sh` — uruchomienie preview z kamery
- `sys_camera-kill.sh` — wymuszenie dostępu do kamery
- `sys_kill-cam.sh` — szybkie zabicie procesów kamery
- `sys_vision-control.sh` — kontrola usług wizyjnych

### Skrypty monitoringu (prefiks `diag_`)
- `diag_metrics.sh` — monitorowanie metryk systemu
- `diag_stream.sh` — monitorowanie strumieni

### Skrypty testowe (prefiks `diag_`)
- `diag_test-suite.sh` — zestaw testów
- `diag_tests-audit.sh` — audyt testów
- `diag_bench-detect.sh` — benchmark detekcji

### Diagnostyka XGO (prefiks `diag_` i `sys_`)
- `diag_sensors.py` — sprawdzenie czujników XGO
- `diag_xgo-bootloader.py` — diagnostyka bootloadera XGO
- `sys_xgo-init.py` — bezpieczna inicjalizacja XGO

### Narzędzia pomocnicze (prefiks `util_` i `sys_`)
- `util_export-env.sh` — eksport zmiennych środowiskowych
- `util_volume-hooks.sh` — hooki głośności
- `sys_cleanup.sh` — czyszczenie usług
- `sys_emergency-stop.py` — emergency stop
- `demo_trajectory.py` — demo ruchu w kształcie lemniskaty

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

Skrypty operacyjne **czytają** konfigurację z `config/`, ale **nie nadpisują** istniejących wartości ENV.

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
# Lista wszystkich skryptów
ls -la scripts/*.sh scripts/*.py

# Sprawdź uprawnienia wykonywania
find scripts -type f \( -name "*.sh" -o -name "*.py" \) ! -perm -u+x
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
- [scripts/README.md](../../scripts/README.md) — pełna dokumentacja katalogu scripts/
- [docs/_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md](../_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md) — szczegóły migracji ops/→scripts/

**Ostatnia aktualizacja:** 2025-10 (po migracji do scripts/)
