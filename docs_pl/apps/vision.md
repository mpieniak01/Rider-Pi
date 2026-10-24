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

## Publikowanie i błędy inicjalizacji

`dispatcher.pub()` i `tracker_mediapipe.pub()` sprawdzają inicjalizację publikatora
przed serializacją danych. Brak `PUB` oznacza pominięcie wysyłki i komunikat
`pub err: publisher not initialized` z prefiksem modułu. Ta kontrola działa także
w Pythonie uruchomionym z `-O` lub `-OO`. Błędy JSON i socketu są nadal
raportowane bez przerywania pętli; kolejne wywołanie może ponowić publikowanie.
Format wiadomości (`topic` i JSON UTF-8) pozostaje taki sam. Testy używają atrap,
bez inicjalizacji detektorów, rzeczywistego BUS lub urządzenia.

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


## Nadzorowana pętla GO/STOP

POST /api/navigation/trial przyjmuje jedno jawne polecenie operatora: request_id, generation, ts i ttl_ms (czas Pi, do 500 ms), config_revision, settings_revision, operator_consent=true, operator_plan, source=manual i execution_context=panel. Pi szereguje przygotowanie usług przez FeatureManager (do 15 s, w tym maksymalnie 5 s na końcowy start po ARM), zachowuje istniejącą konfigurację, wykonuje jeden ARM navigation do 10 s i potwierdza nowy run. Powtórzenie request_id nie powoduje nowego ARM.

Świeża przeszkoda lub niepewny obraz zeruje silniki w ramach aktualnej próby. Trzy kolejne CLEAR mogą wznowić małe impulsy, bez ponownego uzbrojenia i bez wydłużania 10 s. Utrata świeżości/komunikacji, awaria kontraktu/wykonawcy, STOP operatora, ręczne przejęcie i koniec ARM kończą próbę. Obecne progi, prędkość, impulsy i rampy pozostają bez zmian.

Wykonawca musi raportować scoped_stop_generation_supported=true i remote_decision_deadline_supported=true. Opcjonalne expected_generation w STOP/disarm jest sprawdzane atomowo przed odebraniem uprawnienia; stare sprzątanie nie zatrzymuje nowego właściciela. Globalny STOP bez tego pola pozostaje bezwarunkowy. Po aktualizacji kodu wymagana jest aktualna instancja wykonawcy; sam restart panelu nie wystarczy.


### Bliski pas STOP przy wolnym starcie

Nowa konfiguracja domyślnie używa `corridor=[0.35,0.80,0.65,0.95]`: bliższe 15% wysokości obrazu, z tą samą szerokością toru co dawniej. Zapisane konfiguracje nie są automatycznie migrowane. Venom udostępnia wybór Bliska / Dalsza (15% / 30%) zapisujący wyłącznie istniejące pole `corridor` na Pi.

Wybór Bliska nie podnosi prędkości ani czasu impulsu; ogranicza ustawienia do maks. 0,1 SDK i 150 ms. Nie zmienia ramp, deadline, limitu próby 10 s ani działania STOP. Zmiana strefy unieważnia dotychczasowy odbiór i pozostawia tryb observe; sam zapis nie uzbraja i nie uruchamia jazdy. Bieżącą strefę weryfikuje się na świeżym obrazie i zapisuje istniejącym przyciskiem odbioru.

Biała ramka jest strefą STOP. Geometria na Venom zachowuje szerszy kontekst dopasowania podłoża (minimum 30% wysokości obrazu), oznaczony niebieską przerywaną ramką. Nie należy dopasowywać płaszczyzny wyłącznie do mniejszej strefy: duża płaska przeszkoda może wtedy stać się wzorcem podłoża. Obszary są współrzędnymi obrazu, nie skalibrowanym pomiarem centymetrów ani drogi hamowania.


### Przejście z obserwacji do testu bez restartu kamery

Próba najpierw rezerwuje istniejący pasywny cel kamery, potem zwalnia poprzedni
proces obserwacji/jazdy. Kamera i dystrybutor klatek zachowują procesy przy ciepłym
przejściu. Błąd przygotowania pozostawia rezerwację podglądu; nie przywraca jazdy
ani ARM. Nowszy STOP lub przejęcie operatora pozostają nadrzędne.

Status nawigacji zawiera request_id, etap, stan, elapsed_ms i świeżość przygotowania
także bez pliku producenta obrazu. Timeout wskazuje etap awarii. Odczyty jednostek
są współdzielone tylko w transakcji przygotowania i unieważniane po operacjach
usług; uprawnienia ruchu są zawsze odczytywane na świeżo. Przygotowanie usług ma limit 15 s, w tym maksymalnie 5 s na końcowy start
po ARM. Limity ruchu i decyzji pozostają bez zmian.


### Czas produkcyjny: permit napędu a czas próby

Zapis próby Pi wykazał GO i wygaśnięcie krótkiego permitu w trakcie odbierania
następnej świeżej odpowiedzi. Runner rozdziela teraz termin impulsu/komendy,
egzekwowany przez wykonawcę, od żywotności odbioru. Po końcu permitu napęd już
zeruje wyjście; stare GO nie upoważnia do dalszej jazdy. Ta sama próba może czekać
w postoju do ostatniej poprawnej odpowiedzi plus istniejący decision_budget_ms.
Dopiero nowa poprawna klatka/rewizja/sekwencja dopuszcza kolejny ograniczony impuls.
Nie odnawia to ARM i nie podnosi limitów ruchu ani terminów. Brak odpowiedzi w tym
limicie, stare/błędne dane, STOP, błąd transportu lub utrata uprawnień kończą próbę.

Status rozdziela permit_remaining_ms i feedback_remaining_ms. API pokazuje
waiting_feedback oraz odpowiedź STOP po końcu permitu napędu. Monotoniczny czas
startu procesu jest sprawdzany lokalnie na Pi, bez porównywania z zegarem karty.
Jeśli własny proces wystartował i zakończył się w czasie obsługi HTTP, zwracany jest
jego rzeczywisty wynik. Wyłączenie już zakończonego celu zwraca potwierdzony opis
celu, co zapobiega wtórnemu 502 kontraktu HTTP.

Regresje zawierają liczbowy zapis produkcyjnej próby z 2026-10-15 o 12:45,
niezależne zerowanie impulsu, awarię sieci, opóźnione HTTP i odrzucenie obcego runa.
Odbiór fizyczny pozostaje osobnym etapem.


### Odbiór bieżącej sceny

Dnia 2026-10-15 operator potwierdził stabilną pracę pętli GO/STOP w aktualnie
skalibrowanej scenie na fizycznym Rider-Pi. Odbiór dotyczy tej sceny i zapisanych
parametrów wolnej jazdy; nie jest pomiarem odległości ani gwarancją dla innych scen.

Poprawna decyzja z czasem krótszym niż 50 ms na impuls daje tylko ZERO i oczekiwanie
w istniejącym budżecie feedback. Nowa świeża decyzja GO może wznowić tę samą zgodę
ARM, bez odnowienia jej terminu i zwiększania prędkości lub impulsu. Brak feedback,
stary obraz, obca tożsamość i błąd wykonawcy nadal kończą próbę. Panel rozdziela
ocenę obrazu od faktycznego polecenia wykonawczego.

## Pasywny detektor HOG

Przy lokalnym providerze każda poprawnie odczytana klatka przechodzi przez
wykrywanie, zapis podglądu i heartbeat, a następnie ograniczenie FPS. Te etapy
należą do wnętrza pętli przechwytywania. Błędny odczyt lub provider PC pomija
analizę; zakończenie zamyka kamerę i subskrypcję zmiany trybu. Detektor publikuje
obserwację obecności i sam nie uzbraja ani nie uruchamia ruchu.

### Odniesienia pomiarowe widoczne na obrazie

`GET/POST /api/navigation/image-reference` odczytuje i zapisuje niezależne od sterowania odniesienia obrazu. POST przyjmuje `revision` i `values`; konflikt rewizji zwraca 409. Pi przechowuje je w `data/navigation_image_reference.json`. Odpowiedź ma `version=1` i `purpose=visual_reference_only`.

Dane obejmują rozmiar źródłowej klatki, szerokość toru i robota, wysokość kamery, dwie krawędzie toru oraz pary odległość/współrzędna pionowa znaczników. Odniesienia dotyczą zmierzonej najniższej pozycji i są przybliżoną nakładką. Nie zastępują parametrów obiektywu, nie zapisują akceptacji jazdy i nie zmieniają progów modelu, polityki nawigacji, ARM ani ruchu. Panel pozwala przesuwać punkty przed jawnym zapisem na Pi.

## Własne parametry operatora

Profile w wersji 2 są stałymi zestawami wartości. Korekta tworzy ustawienia własne na bazie wybranego profilu; przywrócenie profilu usuwa korekty. Zapis odbywa się na Pi z kontrolą rewizji i bez uruchamiania jazdy. Wersja 1 zachowuje poprzednie wartości. [Parametry, zakresy i diagnostyka](../../docs/vision-policy-parameters.md).
