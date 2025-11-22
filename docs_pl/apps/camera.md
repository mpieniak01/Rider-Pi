# Moduł Camera (`apps/camera`)

## Opis

Moduł `apps/camera` implementuje **preview z kamery** na wyświetlaczu LCD z opcjonalną detekcją twarzy.

### Główne pliki

- **`__main__.py`** — launcher kamery z parametrami CLI
- **`preview_lcd.py`** — główny preview LCD
- **`preview_lcd_hybrid.py`** — hybrydowy preview (V4L2 + Picamera2)
- **`preview_lcd_ssd.py`** — preview z SSD detection
- **`preview_lcd_takeover.py`** — preview z automatycznym przejęciem kamery
- **`cam_motion.py`** — detekcja ruchu z kamery

## Parametry CLI

Uruchamianie przez `python -m apps.camera`:

| Parametr | Typ | Wartości | Opis |
|----------|-----|----------|------|
| `--human` | int | `0`, `1` | Włącz/wyłącz detekcję twarzy |
| `--every` | int | >0 | Co ile klatek sprawdzać twarze |
| `--rot` | int | `0`, `90`, `180`, `270` | Rotacja obrazu (°) |
| `--skip-v4l2` | flag | — | Wymuś Picamera2 (pomiń V4L2) |
| `--warmup` | int | >0 | Liczba klatek rozgrzewki (Picamera2) |
| `--alpha` | float | — | Jasność (OpenCV `convertScaleAbs` alpha) |
| `--beta` | float | — | Offset jasności (beta) |

## Zmienne środowiskowe

Parametry CLI są mapowane na ENV:

| ENV | Źródło CLI | Opis |
|-----|------------|------|
| `VISION_HUMAN` | `--human` | Detekcja twarzy (0/1) |
| `VISION_FACE_EVERY` | `--every` | Co ile klatek detekcja |
| `PREVIEW_ROT` | `--rot` | Rotacja obrazu |
| `SKIP_V4L2` | `--skip-v4l2` | Pomiń V4L2 |
| `PREVIEW_WARMUP` | `--warmup` | Klatki rozgrzewki |
| `PREVIEW_ALPHA` | `--alpha` | Jasność (alpha) |
| `PREVIEW_BETA` | `--beta` | Offset jasności |

## Przepływ danych

```
Kamera (V4L2 lub Picamera2)
    ↓
Capture frame @ N Hz
    ↓
Detekcja twarzy (opcjonalnie, co N-tą klatkę)
    ↓
Rotacja + korekcja jasności (alpha/beta)
    ↓
LCD framebuffer (sink_lcd lub bezpośrednio /dev/fb*)
```

## Przykład użycia

### Preview podstawowy (bez detekcji)

```bash
python -m apps.camera
```

### Preview z detekcją twarzy

```bash
python -m apps.camera --human 1 --every 3
```

### Preview z rotacją 90° i jasnością

```bash
python -m apps.camera --rot 90 --alpha 1.2 --beta 10
```

### Preview Picamera2 (bez V4L2)

```bash
python -m apps.camera --skip-v4l2 --warmup 30
```

## Warianty preview

### preview_lcd.py
Podstawowy preview — uniwersalny, obsługa V4L2/Picamera2.

### preview_lcd_hybrid.py
Hybrydowy: próbuje V4L2, fallback na Picamera2.

### preview_lcd_ssd.py
Preview z SSD (Single Shot Detector) — detekcja obiektów w czasie rzeczywistym.

### preview_lcd_takeover.py
**Automatyczne przejęcie kamery:** jeśli inny proces używa kamery, zabija go i przejmuje dostęp.

**Bezpieczeństwo:** Używa whitelist procesów które można zabić (patrz `camera_takeover_kill.sh`).

## Integracja z systemd

```bash
# Uruchom preview jako usługa
sudo systemctl start rider-cam-preview.service
sudo systemctl status rider-cam-preview.service
```

Zobacz: [docs/ops/systemd-scripts.md](../ops/systemd-scripts.md)

## Błędy i diagnostyka

### Typowe problemy

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Kamera zajęta | Inny proces używa `/dev/video0` | Użyj `--takeover` lub `./scripts/sys_camera-kill.sh` |
| Brak obrazu na LCD | Nieprawidłowe urządzenie framebuffer | Sprawdź `/dev/fb0` lub `/dev/fb1` |
| Obraz do góry nogami | Brak/niewłaściwa rotacja | Użyj `--rot 180` |
| Niska jakość obrazu | Brak korekcji jasności | Dodaj `--alpha 1.2 --beta 10` |

### Diagnostyka

```bash
# Sprawdź dostępność kamery
v4l2-ctl --list-devices

# Sprawdź procesy używające kamery
lsof /dev/video0
fuser /dev/video0

# Zabij procesy kamery (bezpiecznie)
./scripts/sys_camera-kill.sh

# Test framebuffera
cat /dev/urandom > /dev/fb0  # powinno pokazać noise na ekranie
```

## Zależności

### Wewnętrzne (w repo)
- `apps.hw.sink_lcd` — sink do LCD framebuffer
- `apps.vision.*` — detektory (HOG, TFLite, SSD)

### Zewnętrzne
- `opencv-python` (`cv2`) — przetwarzanie obrazu
- `picamera2` — dostęp do kamery Raspberry Pi (opcjonalne)
- `v4l2` — Video4Linux2 (Linux kernel)

## Konfiguracja sprzętowa

### Kamery wspierane
- **Picamera (ribbon):** Natywna kamera RPi (CSI)
- **USB webcam:** Przez V4L2
- **Arducam IMX219:** Kompatybilna z Picamera2

### LCD wspierane
- **ILI9341** — SPI LCD (320×240)
- **Waveshare 4"** — HDMI/DSI
- **Framebuffer `/dev/fb0`** — uniwersalny

Zobacz: [docs/modules/face-lcd.md](../modules/face-lcd.md)

## Rozszerzenia (TODO)

- [ ] Konfiguracja przez TOML zamiast ENV/CLI
- [ ] Wybór detektora przez CLI (HOG, TFLite, SSD)
- [ ] Stream preview przez HTTP/MJPEG
- [ ] Zapis klatek do pliku (timelapse, motion capture)

---

**Related docs:**
- [vision.md](vision.md) — detektory obiektów
- [hw.md](hw.md) — sink LCD
- [docs/ops/camera-scripts.md](../ops/camera-scripts.md) — skrypty pomocnicze
- [docs/modules/face-lcd.md](../modules/face-lcd.md) — rendering na LCD

**Ostatnia aktualizacja:** 2025-01
