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

## Skrypty operacyjne (`ops/*`)

### Skrypty głosowe (voice)
- `voice-run.sh` — uruchamianie aplikacji głosowej (legacy z ENV)
- `voice-once.sh` — pojedyncze polecenie głosowe

### Skrypty systemd
- `service_ctl.sh` — kontrola usług systemd (whitelist)
- `systemd_sync.sh` — synchronizacja definicji systemd z repo
- `boot_prepare.sh` — przygotowanie systemu przy starcie

### Skrypty wyświetlacza
- `lcdctl.py` — kontrola LCD (brightness, power, clear)
- `ledctl.py` — kontrola diod LED
- `fbgrab.py` — zrzut ekranu z framebuffera
- `splash_device_info.py` — ekran powitalny z informacjami o urządzeniu
- `splash_device_info.sh` — wrapper bash dla splash
- `vendor_splash.py` — ekran powitalny producenta

### Skrypty kamery
- `camera_preview.sh` — preview z kamery
- `camera_takeover_kill.sh` — wymuszenie dostępu do kamery (kill procesów)
- `kill_cam.sh` — szybkie zabicie procesów kamery
- `vision_ctl.sh` — kontrola usług wizyjnych

### Skrypty monitoringu
- `monitor_metrics.sh` — monitorowanie metryk systemu
- `monitor_stream.sh` — monitorowanie strumieni

### Skrypty testowe i diagnostyczne
- `test_suite.sh` — zestaw testów
- `tests_audit.sh` — audyt testów
- `bench_detect.sh` — benchmark detekcji
- `check_xgo_sensors.py` — sprawdzenie czujników XGO
- `xgo_bl_probe.py` — diagnostyka bootloadera XGO
- `xgo_safe_init.py` — bezpieczna inicjalizacja XGO

### Skrypty pomocnicze
- `export_env.sh` — eksport zmiennych środowiskowych
- `volume_hooks.sh` — hooki głośności
- `services_cleanup.sh` — czyszczenie usług
- `estop.py` — emergency stop
- `demo_lemniscate.py` — demo ruchu w kształcie lemniskaty

## Pliki konfiguracyjne (`config/*`)

| Plik | Moduł | Status dokumentacji |
|------|-------|---------------------|
| `voice_file.toml` | voice (tryb plikowy) | ⚠️ Do uzupełnienia szczegółami parametrów |
| `voice_streaming.toml` | voice (tryb strumieniowy) | ⚠️ Do uzupełnienia szczegółami parametrów |
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

### Nowe katalogi do utworzenia
- `docs/apps/` — dokumentacja modułów aplikacyjnych
- `docs/ops/` — dokumentacja skryptów operacyjnych
- `docs/config/` — szczegółowa dokumentacja parametrów konfiguracji

### Dokumenty do stworzenia (13 modułów apps)
1. `docs/apps/camera.md`
2. `docs/apps/chat.md`
3. `docs/apps/demos.md`
4. `docs/apps/draw.md`
5. `docs/apps/hw.md`
6. `docs/apps/launcher.md`
7. `docs/apps/menu.md`
8. `docs/apps/motion.md`
9. `docs/apps/nlu.md`
10. `docs/apps/safety.md`
11. `docs/apps/ui.md`
12. `docs/apps/vision.md`
13. `docs/apps/README.md` (indeks)

### Dokumenty ops (7 plików tematycznych)
1. `docs/ops/README.md` (indeks)
2. `docs/ops/voice-scripts.md`
3. `docs/ops/systemd-scripts.md`
4. `docs/ops/display-scripts.md`
5. `docs/ops/monitoring-scripts.md`
6. `docs/ops/camera-scripts.md`
7. `docs/ops/utility-scripts.md`

### Dokumenty config (4 pliki)
1. `docs/config/README.md` (indeks parametrów)
2. `docs/config/voice.md`
3. `docs/config/face.md`
4. `docs/config/alsa.md`

---

**Ostatnia aktualizacja:** 2025-01 (automatyczna inwentaryzacja)  
**Całkowita liczba dokumentów do stworzenia:** 24 pliki
