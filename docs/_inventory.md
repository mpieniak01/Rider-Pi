# Inwentaryzacja modułów, skryptów i konfiguracji Rider-Pi

> **Wygenerowano automatycznie** — lista wszystkich komponentów wymagających dokumentacji

## Moduły aplikacyjne (`apps/*`)

| Katalog | Pliki główne | Status dokumentacji |
|---------|-------------|---------------------|
| `apps/camera` | `__main__.py`, `preview_lcd.py`, `preview_lcd_hybrid.py`, `preview_lcd_ssd.py`, `preview_lcd_takeover.py`, `cam_motion.py` | ⚠️ Do uzupełnienia |
| `apps/chat` | `main.py` | ⚠️ Do uzupełnienia |
| `apps/demos` | `trajectory.py` | ⚠️ Do uzupełnienia |
| `apps/draw` | `face_primitives.py`, `face_renderer.py`, `face_emotions.py` | ⚠️ Do uzupełnienia |
| `apps/hw` | `sink_lcd.py` | ⚠️ Do uzupełnienia |
| `apps/launcher` | `main.py` | ⚠️ Do uzupełnienia |
| `apps/menu` | `main.py` | ⚠️ Do uzupełnienia |
| `apps/motion` | `main.py`, `rider_control.py`, `xgo_adapter.py` | ⚠️ Do uzupełnienia |
| `apps/nlu` | `main.py` | ⚠️ Do uzupełnienia |
| `apps/safety` | `estop.py` | ⚠️ Do uzupełnienia |
| `apps/ui` | `buttons.py`, `config.py`, `face_actuators.py`, `face_core.py`, `face_emotions.py` | ⚠️ Do uzupełnienia |
| `apps/vision` | `detector_hog.py`, `detector_tflite.py`, `dispatcher.py`, `edge_preview.py`, `obstacle_roi.py` | ⚠️ Do uzupełnienia |
| `apps/voice` | `cli.py`, `config.py`, `asr.py`, `tts.py`, `audio/capture.py`, `audio/playback.py`, etc. | ✅ Udokumentowane w `docs/modules/voice.md` |

## Skrypty operacyjne

> **Uwaga:** Skrypty zostały przeniesione z `ops/` i `tools/` do `scripts/` z ujednoliconą konwencją nazewnictwa.  
> Zobacz [../scripts/README.md](../scripts/README.md) i [_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md](_pr_summaries/SCRIPTS_MIGRATION_SUMMARY.md)

### Skrypty głosowe (sys_voice-*)
- `sys_voice-run.sh` — uruchamianie aplikacji głosowej (legacy z ENV)
- `sys_voice-once.sh` — pojedyncze polecenie głosowe
- `sys_voice-stream.sh` — tryb strumieniowy głosu

### Skrypty systemd (sys_*)
- `sys_control.sh` — kontrola usług systemd (whitelist)
- `scripts/systemd-sync.sh` — synchronizacja definicji systemd z repo (przeniesiono z ops/)
- `sys_boot-prepare.sh` — przygotowanie systemu przy starcie

### Skrypty wyświetlacza (sys_*, diag_*)
- `sys_lcd-control.py` — kontrola LCD (brightness, power, clear)
- `sys_led-control.py` — kontrola diod LED
- `diag_framebuffer-grab.py` — zrzut ekranu z framebuffera
- `sys_splash-info.py` — ekran powitalny z informacjami o urządzeniu
- `sys_splash-info.sh` — wrapper bash dla splash
- `sys_vendor-splash.py` — ekran powitalny producenta

### Skrypty kamery (sys_*)
- `sys_camera-preview.sh` — preview z kamery
- `sys_camera-kill.sh` — wymuszenie dostępu do kamery (kill procesów)
- `sys_kill-cam.sh` — szybkie zabicie procesów kamery
- `sys_vision-control.sh` — kontrola usług wizyjnych

### Skrypty monitoringu (diag_*)
- `diag_metrics.sh` — monitorowanie metryk systemu
- `diag_stream.sh` — monitorowanie strumieni

### Skrypty testowe i diagnostyczne (diag_*)
- `diag_test-suite.sh` — zestaw testów
- `diag_tests-audit.sh` — audyt testów
- `diag_bench-detect.sh` — benchmark detekcji
- `diag_sensors.py` — sprawdzenie czujników XGO
- `diag_xgo-bootloader.py` — diagnostyka bootloadera XGO
- `sys_xgo-init.py` — bezpieczna inicjalizacja XGO

### Skrypty pomocnicze (util_*, sys_*)
- `util_export-env.sh` — eksport zmiennych środowiskowych
- `util_volume-hooks.sh` — hooki głośności
- `sys_cleanup.sh` — czyszczenie usług
- `sys_emergency-stop.py` — emergency stop
- `demo_trajectory.py` — demo ruchu w kształcie lemniskaty

## Pliki konfiguracyjne (`config/*`)

| Plik | Moduł | Status dokumentacji |
|------|-------|---------------------|
| `voice_openai_file.toml` | voice (tryb plikowy) | ⚠️ Do uzupełnienia szczegółami parametrów |
| `voice_openai_streaming.toml` | voice (tryb strumieniowy) | ⚠️ Do uzupełnienia szczegółami parametrów |
| `face.toml` | ui/face (rendering buźki) | ⚠️ Do uzupełnienia szczegółami parametrów |

### Podkatalogi konfiguracji
- `config/alsa/` — konfiguracja ALSA (asoundrc, wm8960)
- `config/local/` — lokalne nadpisania (git-ignored)

## Dokumentacja istniejąca

### W `docs/modules/`
- ✅ `voice.md` — pełna dokumentacja modułu voice
- ✅ `face.md` — API statycznego renderu buźki
- ✅ `face-lcd.md` — renderowanie buźki na LCD
- ✅ `face-phase5-lcd.md` — faza 5 implementacji LCD
- ✅ `sim.md` — symulator 2D

### W katalogu głównym `docs/`
- ✅ `CONFIG_POLICY.md` — polityka konfiguracji i sekretów
- ✅ `README.md` — indeks dokumentacji

### W `docs/audio/`
- ✅ `wm8960.md` — konfiguracja karty dźwiękowej WM8960

## Braki do uzupełnienia

### Dokumenty apps, ops i config - KOMPLETNE ✅

Wszystkie wymienione dokumenty zostały już utworzone i znajdują się w:
- `docs/apps/` — dokumentacja modułów aplikacyjnych (13 plików) ✅
- `docs/ops/` — dokumentacja skryptów operacyjnych (7 plików) ✅  
- `docs/config/` — szczegółowa dokumentacja parametrów konfiguracji (4 pliki) ✅

**Zadanie bieżące:** Weryfikacja aktualności dokumentów po reorganizacji struktury (skrypty ops/→scripts/)

---

**Ostatnia aktualizacja:** 2025-10 (po migracji skryptów do scripts/)  
**Status:** Większość dokumentów już utworzona - wymaga weryfikacji aktualności
