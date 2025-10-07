# Moduł Vision (`apps/vision`)

## Opis

Moduł `apps/vision` implementuje **detekcję obiektów** z kamery — wykrywanie twarzy, osób i innych obiektów w czasie rzeczywistym.

### Główne pliki

- **`dispatcher.py`** — normalizacja i debouncing zdarzeń detekcji
- **`detector_hog.py`** — detektor HOG (Histogram of Oriented Gradients)
- **`detector_tflite.py`** — detektor TensorFlow Lite
- **`edge_preview.py`** — preview z Canny edge detection
- **`obstacle_roi.py`** — detekcja przeszkód w ROI (Region of Interest)

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
