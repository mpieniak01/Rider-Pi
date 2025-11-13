# Moduł Vision (`apps/vision`)

## Opis

Moduł `apps/vision` implementuje **detekcję obiektów** z kamery — wykrywanie twarzy, osób i innych obiektów w czasie rzeczywistym.

### Główne pliki

- **`dispatcher.py`** — normalizacja i debouncing zdarzeń detekcji
- **`detector_hog.py`** — detektor HOG (Histogram of Oriented Gradients)
- **`detector_tflite.py`** — detektor TensorFlow Lite
- **`edge_preview.py`** — preview z Canny edge detection
- **`obstacle_roi.py`** — detekcja przeszkód w ROI (Region of Interest)
- **`tracker_mediapipe.py`** — śledzenie twarzy/dłoni dla trybu Follow Me z wizualnym podglądem

## Główne funkcje

### dispatcher.py

**Debouncing i agregacja detekcji:**
- Zbiera zdarzenia z wielu detektorów
- Normalizuje formaty (score, bbox, class)
- Implementuje histerezę: `present=True` po N kolejnych pozytywach
- Auto-off po X sekundach ciszy

### detector_hog.py

**HOG detektor (OpenCV):**
- Szybki detektor osób (CPU-friendly)
- Dobry do pierwszego prototypowania

### detector_tflite.py

**TFLite detektor:**
- Używa modeli MobileNet/SSD
- Wsparcie dla Edge TPU (Coral)
- Wykrywa wiele klas (osoba, samochód, etc.)

### edge_preview.py

**Canny edge detection:**
- Preview krawędzi obrazu
- Użyteczne do debug'u algorytmów wizji

### obstacle_roi.py

**Detekcja przeszkód w ROI:**
- Analizuje wybrany obszar obrazu
- Wykrywa obecność obiektów (np. przeszkoda przed robotem)

### depth_bridge.py (NEW - Rekonesans Stage 3)

**Estymacja głębi dla mapowania SLAM:**
- Monitoruje stan nawigatora (`navigator.state`)
- Aktywuje się automatycznie w trybie Rekonesans
- Konwertuje detekcje przeszkód na dane z dystansem
- Publikuje `vision.obstacle.data` dla konsumpcji przez mapper

**Tryb działania:**
- **Simplified Heuristic** (obecnie): Estymacja dystansu na podstawie confidence i pozycji w obrazie
- **Mono-Depth Estimation** (przyszłość): Model TFLite do estymacji głębi z pojedynczego obrazu

**Topics:**
- Subskrybuje: `navigator.state`, `vision.obstacle`
- Publikuje: `vision.obstacle.data` (pary angle, distance)

**Konfiguracja ENV:**
```bash
VISION_DEFAULT_OBSTACLE_DISTANCE=1.5  # Domyślny dystans przeszkody (m)
VISION_MIN_OBSTACLE_DISTANCE=0.3      # Minimalny dystans (m)
VISION_MAX_OBSTACLE_DISTANCE=3.0      # Maksymalny dystans (m)
VISION_CAMERA_FOV_H=60.0              # Pole widzenia kamery (stopnie)
```

**Format danych vision.obstacle.data:**
```json
{
  "obstacles": [
    {"angle": -15.0, "distance": 1.2},  // kąt w stopniach, dystans w metrach
    {"angle": 0.0, "distance": 1.5},
    {"angle": 15.0, "distance": 1.8}
  ],
  "ts": 1234567890.123
}
```

**Uwaga:** Obecna implementacja używa uproszczonej heurystyki. Dla dokładniejszego mapowania, planowane jest dodanie modelu mono-depth estimation (TFLite).

### tracker_mediapipe.py (Follow Me — Visual Stream)

**Śledzenie twarzy/dłoni z wizualnym podglądem:**
- Używa MediaPipe do detekcji twarzy i dłoni w czasie rzeczywistym
- Publikuje dane offsetu dla `tracking_controller.py` (zachowana funkcjonalność)
- Generuje wizualny strumień wideo z adnotacjami:
  - **FPS** — liczba klatek na sekundę przetwarzania (minimalna akceptowalna: 10 FPS)
  - **Okrąg detekcji** — znacznik wokół wykrytego obiektu (twarz/dłoń)
- Zapisuje klatki JPEG do `snapshots/tracker.jpg`

**Tryby pracy:**
- `FACE` — śledzenie twarzy
- `HAND` — śledzenie dłoni
- `NONE` — tryb uśpienia (bez przetwarzania)

**Topics:**
- Subskrybuje: `tracking.mode:set` (ujednolicony temat kontroli trybu)
- Publikuje: `vision.tracking.offset` (dane offsetu dla kontrolera ruchu)

**Endpoint API:**
- `/vision/tracker` — GET/HEAD — serwuje ostatnią klatkę z adnotacjami (JPEG)
- `/vision/snap-info` — zawiera informacje o wieku klatki tracker
- `/api/vision/tracking/mode` — POST — ujednolicony endpoint kontroli (payload: `{"mode": "face"|"hand"|"none", "enabled": true|false}`)

**Konfiguracja ENV:**
```bash
TRACKING_DEAD_ZONE=0.1      # Strefa martwa środka (±10%)
TRACKING_MAX_FPS=10.0       # Limit FPS (oszczędność CPU)
SNAP_BASE=/path/to/snapshots # Katalog zapisywania klatek
```

**Adnotacje na klatkach:**
- Zielony tekst FPS w lewym górnym rogu
- Żółty okrąg wokół wykrytego obiektu z punktem centralnym
- Automatyczne obliczanie FPS na podstawie rzeczywistego przetwarzania

**Integracja z UI:**
- Podgląd dostępny w `web/view.html` jako "Camera — TRACKER (Follow Me)"
- Automatyczne odświeżanie co ~2 sekundy
- Wyświetlanie wieku klatki i statusu śledzenia

## Przepływ danych

```
Kamera (apps.camera)
    ↓
Detector (HOG / TFLite / ROI)
    ↓
PUB("vision.face" / "vision.person" / "vision.detections")
    ↓
vision.dispatcher (debouncing, normalizacja)
    ↓
PUB("vision.state") → {"present": true/false, "class": "person", "score": 0.85}
```

## Konfiguracja

### Zmienne środowiskowe (dispatcher)

| ENV | Typ | Domyślna | Opis |
|-----|-----|----------|------|
| `BUS_PUB_PORT` | int | `5555` | Port brokera PUB |
| `BUS_SUB_PORT` | int | `5556` | Port brokera SUB |
| `VISION_ON_CONSECUTIVE` | int | `3` | Ile pozytywów by włączyć `present=True` |
| `VISION_OFF_TTL_SEC` | float | `2.0` | Czas ciszy by wyłączyć `present` |
| `VISION_MIN_SCORE` | float | `0.50` | Minimalny próg score (0.0–1.0) |
| `LOG_EVERY` | int | `10` | Co ile eventów logować |

### Zmienne środowiskowe (detektory)

⚠️ **Wymaga weryfikacji:** Szczegóły ENV do uzupełnienia po analizie kodu.

Możliwe parametry:
- `DETECTOR_TYPE` — typ detektora (hog, tflite, roi)
- `MODEL_PATH` — ścieżka do modelu TFLite
- `USE_CORAL` — użyj Edge TPU (0/1)
- `ROI_X`, `ROI_Y`, `ROI_W`, `ROI_H` — współrzędne ROI

## Struktura payloadów

### vision.detections (input do dispatcher)

```json
{
  "class": "person",
  "score": 0.85,
  "bbox": [100, 150, 200, 300],  // [x, y, width, height]
  "ts": 1704067200.5
}
```

### vision.state (output z dispatcher)

```json
{
  "present": true,
  "class": "person",
  "score": 0.85,
  "last_seen": 1704067200.5,
  "count": 5  // liczba kolejnych pozytywów
}
```

## Przykład użycia

### Uruchomienie dispatcher

```bash
# Terminal 1: uruchom dispatcher
python -m apps.vision.dispatcher
```

### Uruchomienie detector + dispatcher

```bash
# Terminal 1: dispatcher
python -m apps.vision.dispatcher

# Terminal 2: detektor HOG
python -m apps.vision.detector_hog

# Terminal 3: monitoruj stan
python -c "from common.bus import BusSub; s=BusSub('vision.state'); import json; \
while True: print(json.dumps(s.recv()[1]))"
```

### Edge preview (debug)

```bash
python -m apps.vision.edge_preview
```

## Integracja z systemd

```bash
# Usługi wizyjne
sudo systemctl start rider-vision.service       # dispatcher
sudo systemctl start rider-edge-preview.service # edge preview
sudo systemctl start rider-obstacle.service     # obstacle ROI
```

Zobacz: [docs/ops/systemd-scripts.md](../ops/systemd-scripts.md)

## Błędy i diagnostyka

### Typowe problemy

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Brak detekcji | Score poniżej threshold | Zmniejsz `VISION_MIN_SCORE` |
| Fałszywe pozytyw | Zbyt mała histereza | Zwiększ `VISION_ON_CONSECUTIVE` |
| Długie opóźnienie off | Zbyt długie TTL | Zmniejsz `VISION_OFF_TTL_SEC` |
| Błąd "model not found" | Brak modelu TFLite | Pobierz model, ustaw `MODEL_PATH` |

### Diagnostyka

```bash
# Monitoruj surowe detekcje
python -c "from common.bus import BusSub; s=BusSub('vision.detections'); import json; \
while True: print(json.dumps(s.recv()[1]))"

# Sprawdź stan dispatcher
python -c "from common.bus import BusSub; s=BusSub('vision.state'); import json; \
while True: print(json.dumps(s.recv()[1]))"

# Test detektora (standalone)
python -m apps.vision.detector_hog --debug
```

## Modele TFLite

### Pobieranie modeli

```bash
# MobileNet SSD v2 (COCO dataset)
wget https://storage.googleapis.com/download.tensorflow.org/models/tflite/coco_ssd_mobilenet_v1_1.0_quant_2018_06_29.zip
unzip coco_ssd_mobilenet_v1_1.0_quant_2018_06_29.zip -d models/

# Ustaw ścieżkę
export MODEL_PATH=models/detect.tflite
```

### Edge TPU (Coral)

```bash
# Kompilacja modelu dla Edge TPU
edgetpu_compiler models/detect.tflite

# Użyj skompilowanego modelu
export MODEL_PATH=models/detect_edgetpu.tflite
export USE_CORAL=1
```

## Wydajność

| Detektor | FPS (RPi 4) | Dokładność | CPU |
|----------|-------------|------------|-----|
| HOG | ~15 FPS | Średnia | Niskie |
| TFLite (CPU) | ~8 FPS | Wysoka | Wysokie |
| TFLite (Coral) | ~30 FPS | Wysoka | Niskie |

## Zależności

### Wewnętrzne (w repo)
- `apps.camera` — źródło obrazu
- `common.bus` — komunikacja

### Zewnętrzne
- `opencv-python` (`cv2`) — HOG detector, edge detection
- `tensorflow-lite` — TFLite models
- `pycoral` — Edge TPU (opcjonalne)
- `numpy` — operacje na tablicach

## Rozszerzenia (TODO)

- [ ] Tracking obiektów (KLT, SORT)
- [ ] Więcej detektorów (YOLO, Faster R-CNN)
- [ ] Konfiguracja przez TOML zamiast ENV
- [ ] Stream detekcji przez HTTP/WebSocket
- [ ] Zapisywanie snapshots z detekcją

---

**Related docs:**
- [camera.md](camera.md) — źródło obrazu
- [docs/ops/camera-scripts.md](../ops/camera-scripts.md) — skrypty pomocnicze

**Ostatnia aktualizacja:** 2025-01  
**Status:** ⚠️ Część parametrów wymaga weryfikacji
