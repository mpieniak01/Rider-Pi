# Katalog `scripts`

Ten katalog zawiera wszystkie skrypty operacyjne, diagnostyczne, deweloperskie i narzędziowe projektu **Rider-Pi**.  
Wcześniej skrypty były podzielone pomiędzy katalogi `ops/` i `tools/`, obecnie zostały **scalone** w jednym miejscu z ujednoliconym schematem nazewnictwa.

## Konwencja nazewnictwa

Wszystkie skrypty stosują wzorzec:  
**`[kategoria]_[opis-funkcjonalny]`**

### Kategorie

#### `sys_` – Operacje systemowe  
Skrypty do zarządzania systemem, usługami, rozruchem i operacjami krytycznymi:
- `sys_control.sh` – kontrola usług  
- `sys_systemd-sync.sh` – synchronizacja z systemd  
- `sys_boot-prepare.sh` – przygotowanie systemu do startu  
- `sys_cleanup.sh` – czyszczenie usług  
- `sys_camera-preview.sh` – podgląd kamery  
- `sys_camera-kill.sh` – zatrzymanie procesu kamery  
- `sys_kill-cam.sh` – zabicie procesów kamery  
- `sys_vision-control.sh` – kontrola systemu wizyjnego  
- `sys_lcd-control.py` – kontrola LCD  
- `sys_led-control.py` – kontrola diod LED  
- `sys_emergency-stop.py` – awaryjne zatrzymanie  
- `sys_xgo-init.py` – bezpieczna inicjalizacja XGO  
- `sys_splash-info.py` – ekran powitalny z informacjami o urządzeniu  
- `sys_splash-info.sh` – wrapper ekranu powitalnego  
- `sys_vendor-splash.py` – ekran powitalny producenta  
- `sys_voice-once.sh` – pojedyncza interakcja głosowa  
- `sys_voice-run.sh` – ciągłe uruchomienie głosu  
- `sys_voice-stream.sh` – tryb strumieniowy głosu  

#### `diag_` – Diagnostyka i monitorowanie  
Skrypty do testów, monitoringu i diagnostyki:
- `diag_bench-detect.sh` – test wykrywania  
- `diag_test-suite.sh` – zestaw testów  
- `diag_tests-audit.sh` – audyt testów  
- `diag_sensors.py` – test czujników XGO  
- `diag_metrics.sh` – monitorowanie metryk  
- `diag_stream.sh` – monitorowanie strumieni  
- `diag_framebuffer-grab.py` – zrzut bufora ramki  
- `diag_xgo-bootloader.py` – test bootloadera XGO  
- `diag_bus-spy.py` – podgląd magistrali komunikatów  
- `diag_lcd-raw.py` – diagnostyka surowego LCD  
- `diag_websocket-probe.py` – test połączenia WebSocket  

#### `dev_` – Narzędzia deweloperskie  
Skrypty do rozwoju, ręcznego sterowania i testów:
- `dev_manual-drive.py` – ręczne sterowanie robotem  
- `dev_check-file-length.py` – sprawdzanie długości plików  
- `dev_check-legacy-imports.py` – wykrywanie przestarzałych importów  
- `dev_face-cli.py` – interfejs CLI modułu „face”  
- `dev_face-lcd-clean.py` – czyszczenie LCD twarzy  
- `dev_face-presenter.py` – tylko prezentacja twarzy  
- `dev_face-lcd-direct.py` – bezpośrednie renderowanie twarzy na LCD  
- `dev_lcd-clear.py` – czyszczenie LCD / prezentacja  
- `dev_lcd-testcard.py` – plansza testowa LCD  
- `dev_lcd-show-raw.py` – wyświetlanie surowych danych LCD  
- `dev_panel-nuke.py` – testowy reset panelu i pasków  
- `dev_panel-reset.py` – reset panelu  
- `dev_panel-reset-safe.py` – bezpieczny reset panelu  
- `dev_bus-pub.py` – publikacja komunikatów na magistrali  
- `dev_bus-sub.py` – subskrypcja komunikatów z magistrali  
- `dev_bus-dump.py` – zrzut magistrali  
- `dev_bus-state.py` – stan magistrali  
- `dev_send-cmd.py` – wysyłanie komend  
- `dev_keyboard-sim.py` – symulator klawiatury  
- `dev_xgo-client.py` – klient XGO (tylko odczyt)  

#### `demo_` – Dema  
Skrypty demonstracyjne prezentujące funkcje systemu:
- `demo_trajectory.py` – demo trajektorii (krzywa lemniskaty)  
- `demo_weather-lcd.py` – demo pogody na LCD  

#### `util_` – Narzędzia pomocnicze  
Skrypty wspierające i użytkowe:
- `util_export-env.sh` – eksport zmiennych środowiskowych  
- `util_volume-hooks.sh` – haki regulacji głośności  
- `util_load-config.sh` – ładowanie konfiguracji  
- `util_volume.py` – kontrola głośności  

---

## Szybkie odniesienie (Quick Reference)

### Typowe operacje

**Kontrola systemu:**
```bash
./scripts/sys_control.sh <usługa> <akcja>
./scripts/sys_emergency-stop.py on|off|status
```

**Diagnostyka:**
```bash
./scripts/diag_sensors.py          # Sprawdzenie czujników XGO
./scripts/diag_bus-spy.py          # Podgląd magistrali komunikatów
./scripts/diag_test-suite.sh       # Uruchomienie zestawu testów
```

**Rozwój:**
```bash
./scripts/dev_manual-drive.py      # Ręczne sterowanie robotem
./scripts/dev_bus-pub.py <temat> <dane>
./scripts/dev_bus-sub.py <temat>
```

**LCD / Wyświetlacz:**
```bash
sudo python3 scripts/sys_lcd-control.py on|off|status
./scripts/dev_face-lcd-direct.py --expr neutral --secs 5
./scripts/dev_lcd-clear.py
```

**Głos:**
```bash
./scripts/sys_voice-once.sh        # Jednorazowa interakcja głosowa
./scripts/sys_voice-run.sh         # Tryb ciągły
```

---

## Uwagi migracyjne

Ten katalog **scala** skrypty z dawnych katalogów `ops/` i `tools/`:

- **ops/** → wszystkie skrypty operacyjne przeniesione do `scripts/` z prefiksem `sys_`, `diag_` lub `util_`  
- **tools/** → wszystkie narzędzia deweloperskie przeniesione do `scripts/` z prefiksem `dev_`, `diag_` lub `util_`  
- **Zachowano:** podkatalogi `ops/agent/` i `ops/audio/` (bez zmian)

Szczegółowe mapowanie przeniesień znajduje się w pliku **`SCRIPTS_MIGRATION_SUMMARY.md`** w katalogu głównym projektu.

---

## Użycie przez Makefile

Wiele skryptów jest zintegrowanych z **Makefile** dla wygody:

```bash
make bus-spy           # Uruchom diag_bus-spy.py
make lcd-on            # Włącz LCD (sys_lcd-control.py on)
make lcd-off           # Wyłącz LCD (sys_lcd-control.py off)
```

Pełną listę dostępnych poleceń znajdziesz w pliku `Makefile`.

---

## Dobre praktyki

1. **Używaj ścieżek bezwzględnych** lub automatycznego wykrywania katalogu repozytorium  
2. **Loguj informacje na stderr**, a dane wyjściowe na stdout  
3. **Stosuj `set -euo pipefail`** w skryptach bash dla szybkiego wykrywania błędów  
4. **Twórz skrypty idempotentne**, aby wielokrotne uruchomienie nie powodowało skutków ubocznych  
5. **Dodawaj informację o użyciu** w nagłówku skryptu lub przez opcję `--help`  

---

## Powiązana dokumentacja

- `docs/ops/` – szczegółowe opisy skryptów operacyjnych  
- `SCRIPTS_MIGRATION_SUMMARY.md` – pełne informacje o migracji  
- `Makefile` – integracja z systemem budowania  

---

## Wkład (Contributing)

Podczas dodawania nowych skryptów:

1. Stosuj konwencję nazewnictwa: `[kategoria]_[opis-funkcjonalny]`  
2. Wybierz odpowiedni prefiks kategorii  
3. Ustaw uprawnienia wykonywalne:  
   ```bash
   chmod +x scripts/twoj_skrypt
   ```  
4. Dodaj dokumentację do tego README  
5. Zaktualizuj `Makefile`, jeśli skrypt ma mieć własny cel (target)  

---

**Ostatnia aktualizacja:** październik 2025 (PR #13 – konsolidacja ops/tools)
