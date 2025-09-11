# Rider‑Pi — Release Notes v0.6.0 (2025‑09‑09)

## TL;DR
- ✅ **Nowy podgląd kamery on‑demand**: `rider-cam-preview.service` (uruchamiany jako użytkownik **pi**).
- ✅ **API `/camera/*`**: automatyczne rozpoznawanie rozszerzeń **.jpg/.png/.bmp**, poprawny `Content-Type` i mocne nagłówki **no‑cache**.
- ✅ **apps/camera/preview_lcd.py**: stabilny zapis `data/last_frame.*` (atomowy), Picamera2→V4L2 fallback, tryb headless, opcjonalna detekcja (haar/tflite/ssd), heartbeat z pełną ścieżką pliku.
- ✅ **Ops**: alias `preview` w `ops/service_ctl.sh` wskazuje nową usługę; whitelist zaktualizowany.
- ✅ **Makefile**: nowe cele `preview-*`; usunięte odwołania do starego SSD‑preview.
- 🔒 **Uprawnienia**: usługi działają jako **pi**; `pi` dodany do grup: `video, render, spi, i2c, gpio`.

---

## Zmiany w tej wersji

### 1) Usługi systemd
**Nowa**: `systemd/rider-cam-preview.service`
- Uruchamia `apps/camera/preview_lcd.py` (lekki podgląd, bez ciężkiego przetwarzania).
- `User=pi`, `WorkingDirectory=/home/pi/robot`.
- Konfigurowalna przez `Environment=…` (rotacja, zapis klatek, LCD, itp.).
- `ExecStopPost` gasi LCD: `ops/lcdctl.py off`.
- Restart on‑failure.

**Alias ops**:
- `ops/service_ctl.sh`: alias `preview → rider-cam-preview.service`.
- Whitelist zaktualizowany (dodano nowy unit; stary SSD alias usunięty z domyślnego mapowania).

**Uprawnienia / użytkownik**:
- Usługi działają jako **pi** (bez pytania o hasło przy starcie/stopie przez aliasy ops).
- `pi` dodany do grup: `video, render, spi, i2c, gpio` (dostęp do kamery/LCD/I²C/SPI/GPIO).

---

### 2) Aplikacja podglądu: `apps/camera/preview_lcd.py`
- **Zapis ostatniej klatki**: automatyczny wybór rozszerzenia (**JPG → PNG → BMP**), możliwość wymuszenia `LAST_FRAME_EXT`.
- **Zapis atomowy** (`.tmp` + `os.replace`) – redukcja uszkodzonych plików.
- **Pierwsza klatka** zapisywana natychmiast, dalej co `SAVE_LAST_EVERY`.
- **LCD/Headless**: `DISABLE_LCD`/`NO_DRAW`, rotacja `PREVIEW_ROT` (0/90/180/270).
- **Kamera**: Picamera2 lub fallback V4L2 (`cv2.VideoCapture(0)` + MJPG).
- **Detekcja (opcjonalnie)**: `DETECTOR=none|haar|tflite|ssd`, alias `VISION_HUMAN=1 → haar`.
- **Publikacja**: `camera.heartbeat` (FPS, stan LCD, realna ścieżka last_frame), `vision.detections`, `vision.person`.

---

### 3) API — kamera: `services/api_camera.py`
- Endpointy:
  - `GET /camera/raw`  → najświeższy *raw* (`raw.jpg|png|bmp`), odpowiedni `Content-Type`.
  - `GET /camera/proc` → *proc* (z przetwarzania, jeśli działa), odpowiedni `Content-Type`.
  - `GET /camera/last` → alias do *raw* z nagłówkami **no‑cache** (rozwiązuje „stare klatki”).
  - `GET /camera/placeholder` → SVG placeholder, gdy podgląd wyłączony.
  - `GET /snapshots/<fname>` → bezpieczne serwowanie plików ze `snapshots/` (ochrona przed path traversal).
- Automatyczne wykrywanie rozszerzeń (`.jpg/.png/.bmp`).

---

### 4) Makefile / narzędzia ops
- **Makefile**:
  - Nowe cele: `preview-on`, `preview-off`, `preview-status`, `preview-logs`.
  - `status-all` / `logs-all` nie odwołują się do starego SSD aliasu.
- **ops/service_ctl.sh**:
  - Alias `preview` przełączony na `rider-cam-preview.service`.
  - `logs` pokazuje dziennik systemd; whitelist zaktualizowany.

---

## Zmienne środowiskowe (wybrane)
- Kamera/podgląd: `PREVIEW_ROT`, `DISABLE_LCD`, `NO_DRAW`, `SAVE_LAST_EVERY`, `LAST_FRAME_EXT`.
- Detekcje: `DETECTOR`, `VISION_HUMAN`, `VISION_FACE_EVERY`, `VISION_MIN_SCORE`, `VISION_EVERY`, `TFLITE_MODEL`, `SSD_CLASSES`.
- Bus: `BUS_PUB_PORT`.


## Szybki start / testy
```bash
# API
curl -I http://127.0.0.1:8080/camera/raw
curl -I http://127.0.0.1:8080/camera/proc
curl -I http://127.0.0.1:8080/camera/last

# Podgląd on-demand
ops/service_ctl.sh preview start
sleep 2
curl -I http://127.0.0.1:8080/camera/raw
ops/service_ctl.sh preview stop
```

---

## Migracja
1. Upewnij się, że użytkownik `pi` ma grupy:
   ```bash
   sudo usermod -aG video,render,spi,i2c,gpio pi
   ```
2. Zainstaluj/odśwież jednostki:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable rider-api.service
   sudo systemctl enable rider-cam-preview.service   # opcjonalnie autostart
   sudo systemctl restart rider-api.service
   ```
3. Sterowanie podglądem:
   ```bash
   ops/service_ctl.sh preview start|stop|status|logs
   ```

---

## Znane uwagi
- `/camera/proc` może wskazywać starszy plik, jeśli **usługa przetwarzania** nie jest uruchomiona równolegle (RAW ≠ PROC by design).
- Aby uniknąć „starych obrazów” w UI, używaj `/camera/last` (no‑cache). Upewnij się, że żaden reverse‑proxy nie nadpisuje nagłówków cache.
- Oszczędzanie baterii: trzymaj podgląd **wyłączony** i uruchamiaj **na żądanie**.

---

## Rozwiązywanie problemów
```bash
# 1) Sprawdź, czy nie ma duplikatów procesów i czy kamera jest zwolniona
ps -ef | grep -E 'preview_lcd|camera' | grep -v grep
sudo fuser -v /dev/video0

# 2) Logi usługi
ops/service_ctl.sh preview logs

# 3) Metadane plików i czasy modyfikacji
ls -lh --full-time data/last_frame.* snapshots/raw.* snapshots/proc.*

# 4) Wymuś wyłączenie/włączenie LCD
python3 ops/lcdctl.py off; sleep 1; python3 ops/lcdctl.py on
```

---

## Co dalej (v0.7 — processing service)
- Nowa usługa **przetwarzania** (detekcja obiektów, obstacle ROI, kolizje): wielokrotne instancje z parametrami.
- `/camera/proc` z aktualizacją „live” i SSE/metadanymi detekcji.
- Profil zasilania: duty‑cycle podglądu, adaptive frame rate.
- Refektor api_server - wydzielony viosion_api ale nie podłaczony, dalsze odchudzenie do stany tylko router.

---

## Tag i commit
**Tag**: `v0.6.0-camera-preview`

**Commit message (propozycja):**
```
feat(camera): on-demand cam preview service (pi), atomic last_frame.*; API auto-ext + no-cache; ops alias preview→rider-cam-preview; Makefile preview-*; optional haar/tflite/ssd hooks; heartbeat with last_frame_path; run as pi (video/render/spi/i2c/gpio).
```

