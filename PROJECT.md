# Rider‑Pi — PROJECT.md (v0.4.6)

**Wersja:** v0.4.6\
**Data:** 2025‑08‑28\
**Repo:** `pppnews/Rider-Pi`

---

## Co nowego w v0.4.6

**Kamera + LCD (2") – przejęcie i podgląd**

- Nowy moduł **podglądu z kamery** na SPI LCD 2" producenta z **przejęciem ekranu**:
  - Plik: `apps/camera/preview_lcd_takeover.py` (uruchamiany przez `python3 -m apps.camera`).
  - **Dwa backendy kamery**: V4L2 (UVC) oraz Picamera2/libcamera (CSI – np. OV5647); auto‑wybór.
  - **Lock** `/tmp/rider_spi_lcd.lock` – gwarancja pojedynczej instancji na LCD.
  - **Bezpieczne sprzątanie** przy SIGINT/SIGTERM: czarna klatka + `lcdctl off`.
  - Opcjonalna **detekcja twarzy** (Haar Cascade, CPU‑light): `VISION_HUMAN=1`.
- Skrypty:
  - `scripts/camera_takeover_kill.sh` – agresywne uwolnienie zasobów (zabija stare procesy producenta/libcamera, zwalnia `/dev/video*`, budzi LCD).
  - `scripts/camera_preview.sh` – wygodny wrapper do podglądu.
  - `scripts/smoke_test.sh` – rozszerzony o krok kamery + mocniejszy **power‑save** na końcu.
- **Zero zmian poza repo** – nie dotykamy `/etc`. (Plik unitu do wglądu trzymamy w `systemd/`, ale **nie używamy**.)

Pozostałe:

- Uporządkowano stare/zdublowane pliki kamery i preview (zachowane: `__main__.py`, `preview_lcd_takeover.py`, wrappery w `scripts/`).

---

## Architektura (skrót)

- **ZeroMQ broker** (XSUB↔XPUB):
  - PUB → `tcp://127.0.0.1:5555` (tematy wychodzące)
  - SUB → `tcp://127.0.0.1:5556` (tematy przychodzące)
- **Tematy** (bez zmian):
  - `motion` – polecenia ruchu
  - `motion.state` – telemetria ruchu
  - `vision.state` – sygnały z kamery (np. `human`, `moving`)
  - `ui.control` – sterowanie rysowaniem overleya `{ "draw": bool }`
- **UI**:
  - `apps/ui/face_renderers.py` (LCD/TK)
  - `apps/ui/face.py` (twarz – orchestracja stanu, BUS, heartbeat)
- **Kamera / LCD** (NOWE):
  - `apps/camera/__main__.py` – launcher CLI (mapuje argumenty → ENV) i uruchamia `preview_lcd_takeover.main()`.
  - `apps/camera/preview_lcd_takeover.py` – podgląd do LCD (320×240 RGB), przejęcie i cleanup.
  - `scripts/camera_takeover_kill.sh` – kill + OFF→ON BL + zwolnienie `/dev/video*`.

---

## Szybki start

### 1) Smoke test (pełny)

```bash
cd ~/robot
bash scripts/smoke_test.sh
```

Kroki: clean → compileall → renderers → face(null) → pygame → **camera preview (LCD, 5s)** → power‑save.

### 2) Podgląd kamery na LCD (ręcznie, bez systemd)

**Z wrapperem:**

```bash
cd ~/robot
bash scripts/camera_preview.sh
```

Domyślnie: `SKIP_V4L2=1` (Picamera2), `PREVIEW_ROT=270`, `PREVIEW_WARMUP=12`, `VISION_HUMAN=1`.

**Bez wrappera (wprost):**

```bash
cd ~/robot
bash scripts/camera_takeover_kill.sh
sudo SKIP_V4L2=1 PREVIEW_ROT=270 PREVIEW_WARMUP=12 VISION_HUMAN=1 \
  python3 -m apps.camera
```

Zatrzymanie: `Ctrl+C` (czarna klatka + OFF).

---

## Pliki i rola

- `apps/camera/__init__.py` – znacznik pakietu.
- `apps/camera/__main__.py` – CLI → ENV, start `preview_lcd_takeover.main()`.
- `apps/camera/preview_lcd_takeover.py` – główny podgląd do 2" LCD (SPI):
  - V4L2 (UVC) lub Picamera2 (CSI), format wyjściowy **zawsze** 320×240 RGB.
  - `LOCK_PATH=/tmp/rider_spi_lcd.lock` – jedna instancja.
  - Obsługa SIGINT/SIGTERM → cleanup (czarna klatka, `lcdctl off`).
- `scripts/camera_takeover_kill.sh` – killer: `pkill` znanych procesów, `fuser -k /dev/video*`, ON BL (wybudzenie panelu).
- `scripts/camera_preview.sh` – skrót do uruchomienia podglądu.
- `scripts/smoke_test.sh` – pełny test, w tym krok kamery i **power‑save** (kill/blank/DPMS/`lcdctl off`).
- `scripts/lcdctl.py` – sterowanie podświetleniem i stanem LCD (ON/OFF) – używane przez preview i smoke test.
- `systemd/rider-camera-preview.service` – **tylko do wglądu** (nie wymagane; nie używamy poza repo).

---

## Zmienne środowiskowe (kamera/LCD)

**Preview / obraz:**

- `PREVIEW_ROT` = `0|90|180|270` – obrót programowy (default `270`).
- `PREVIEW_WARMUP` = `int` – rozgrzewka przy Picamera2 (default `12`).
- `PREVIEW_BORDER` = `0|1` – ramka debug (default `1`).
- `PREVIEW_ALPHA` = `float` – mnożnik jasności (default `1.0`).
- `PREVIEW_BETA` = `float` – offset jasności (default `0.0`).

**Backend / wybór kamery:**

- `SKIP_V4L2` = `0|1` – `1` = pomiń V4L2, wymuś Picamera2 (default `0`).
- `CAMERA_IDX` = `int` – indeks V4L2; `-1` = auto‑scan (default `-1`).

**Detekcja twarzy (opcjonalna):**

- `VISION_HUMAN` = `0|1` – włącz (default `0`).
- `VISION_FACE_EVERY` = `int` – co ile klatek sprawdzać (default `5`).

**LCD/Backlight (używane pośrednio przez **``** / killer):**

- `BL_PIN` (np. `13`/`0`), `BL_AH` (`1`=aktywny wysoki), `DC_PIN`, `RST_PIN` – jeśli potrzebne; zwykle nie trzeba zmieniać.

---

## Runbook – scenariusze testowe

1. **Podstawowy podgląd (Picamera2, rot=270, detekcja):**
   ```bash
   bash scripts/camera_preview.sh
   ```
2. **Wymuś V4L2 (UVC) i bez detekcji:**
   ```bash
   SKIP_V4L2=0 VISION_HUMAN=0 bash scripts/camera_preview.sh
   ```
3. **Jasność i offset (rozjaśnienie):**
   ```bash
   PREVIEW_ALPHA=1.2 PREVIEW_BETA=10 bash scripts/camera_preview.sh
   ```
4. **Szybki pełny smoke (z kamerą):**
   ```bash
   bash scripts/smoke_test.sh
   ```

---

## Rozwiązywanie problemów

**„No cameras available” / brak kamery:**

- Sprawdź wykrycie przez libcamera:
  ```bash
  libcamera-hello --list-cameras
  v4l2-ctl --list-devices
  ```
- Jeśli kamera zajęta/busy – zabij procesy:
  ```bash
  bash scripts/camera_takeover_kill.sh
  ```
- Dla CSI (Picamera2) – upewnij się, że taśma i czujnik działają (OV5647/IMX…), a kernel ma sterowniki (standard w Bookworm).

**LCD bieleje/nie reaguje:**

- Uruchom ON/OFF:
  ```bash
  sudo python3 scripts/lcdctl.py on
  sudo python3 scripts/lcdctl.py off
  ```
- Jeśli BL na innym GPIO lub inna polaryzacja → ustaw `BL_PIN`, `BL_AH`.

**Rotacja/odbicie:**

- Zmień `PREVIEW_ROT` (`0/90/180/270`).
- (Jeśli potrzebne odbicie H/V – do dodania jako FLIP\_H/FLIP\_V w preview.)

**Artefakty/paski/„podwójny ekran”:**

- Zawsze poprzedź uruchomienie podglądu: `bash scripts/camera_takeover_kill.sh`.
- Upewnij się, że nie ma drugiej instancji: lock `/tmp/rider_spi_lcd.lock`.

**Po smoke teście wraca „stary” ekran:**

- W preview jest cleanup (czarna klatka + OFF). Smoke test ma na końcu pętlę power‑save (kilkukrotny kill/blank/DPMS/OFF). Jeśli coś i tak „wstaje”, sprawdź:
  ```bash
  pgrep -af 'apps\.camera|apps\.ui\.face|libcamera-|rpicam-|picamera2|xgo'
  ```
  i dodaj proces do listy killer’a.

---

## Porządki w repo

Zostawiamy:

- `apps/camera/__init__.py`, `apps/camera/__main__.py`, `apps/camera/preview_lcd_takeover.py`
- `scripts/camera_takeover_kill.sh`, `scripts/camera_preview.sh`, `scripts/smoke_test.sh`
- `scripts/lcdctl.py`

Usunięte jako duplikaty/stare:

- `apps/camera/preview_lcd.py`, `apps/camera/main.py`, `apps/camera/camera_preview.sh`, `scripts/vendor_splash.py`

Przykładowy `.gitignore` (w repo):

```
__pycache__/
*.py[cod]
*.pyo
logs/
*.log
*.tmp
*~
.trash_*/
.DS_Store
```

---

## Changelog

- **v0.4.6 (2025‑08‑28)**: kamera→LCD takeover (Picamera2/V4L2), lock, SIGTERM cleanup, nowe skrypty (`camera_takeover_kill.sh`, `camera_preview.sh`), smoke test z krokiem kamery + mocny power‑save; porządki plików.
- **v0.4.5 (2025‑08‑27)**: UI Manager (XGO dim/off, auto PWM), overlay draw‑pause, hooki audio, unit systemd (w repo).
- **v0.4.4**: launcher + demo trajektorii, porządki repo, README/PROJECT.
- **v0.4.3**: XgoAdapter, telemetria baterii, doc środowisko/adaptor.

---