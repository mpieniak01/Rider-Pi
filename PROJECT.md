# Rider‑Pi — PROJECT.md (v0.4.7)

> **Scope (v0.4.7):** kamera + LCD 2" (SPI), podgląd + detekcja, bench, mocniejszy „kill vendorów”, model(e) w repo.

---

**Nowe:**
- `preview_lcd_takeover.py` (HAAR) ~15 FPS @ 320×240.
- `preview_lcd_ssd.py` (MobileNet-SSD; `SSD_EVERY`, `SSD_CLASSES`, `SSD_SCORE`) ~5 FPS.
- `preview_lcd_hybrid.py` (PoC: SSD+tracker+HAAR) ~4–6 FPS.
- `camera_takeover_kill.sh`: opcjonalny `vendor_splash.py` (działa, nawet gdy pliku brak), BL=GPIO13 ON.
- `bench_detect.sh`: logi „[bench] fps=…”, `BENCH_LOG=1`, `KEEP_LCD=1`.
---

**Uruchamianie (skrót):**
```bash
export SKIP_V4L2=1 PREVIEW_ROT=270
# HAAR fast
python3 -u apps/camera/preview_lcd_takeover.py
# SSD
export SSD_EVERY=2 SSD_CLASSES=person SSD_SCORE=0.55
python3 -u apps/camera/preview_lcd_ssd.py
# HYBRID (PoC)
python3 -u apps/camera/preview_lcd_hybrid.py
# Kill / cleanup
./scripts/camera_takeover_kill.sh
# Bench
export BENCH_LOG=1; ./scripts/bench_detect.sh 20

## Modele w repo
```
models/
├─ efficientdet_lite0.tflite        # (pod przyszłe TFLite)
└─ ssd/
   ├─ MobileNetSSD_deploy.prototxt
   └─ MobileNetSSD_deploy.caffemodel
```

---

## Uruchomienia (skrót)

### Podgląd + twarz (HAAR)
```bash
cd ~/robot
export SKIP_V4L2=1 PREVIEW_ROT=270 VISION_HUMAN=1 VISION_FACE_EVERY=5
python3 -u apps/camera/preview_lcd_takeover.py
```

### Podgląd + obiekty (SSD)
```bash
cd ~/robot
export SKIP_V4L2=1 PREVIEW_ROT=270
export SSD_EVERY=2            # detekcja co N klatek (1=każda)
export SSD_CLASSES=person     # (opcjonalnie) tylko wybrane klasy
export SSD_SCORE=0.55         # próg pewności
python3 -u apps/camera/preview_lcd_ssd.py
```

### (EXPERIMENTAL) Hybryda: SSD + tracking + HAAR
```bash
cd ~/robot
export SKIP_V4L2=1 PREVIEW_ROT=270
export SSD_SCORE=0.55 SSD_EVERY=3 FACE_EVERY=5 TRACKER=kcf   # lub csrt
python3 -u apps/camera/preview_lcd_hybrid.py
```

> **Uwaga:** jeśli LCD „miga”/gaśnie — to zwykle konflikt z procesami producenta. Patrz „Kill‑switch”.

---

## Benchmark FPS

### Skrypt
```bash
./scripts/bench_detect.sh 20    # SSD i HAAR po ~20 s
# ENV: PREVIEW_ROT, SSD_SCORE, CAM_W/H, BENCH_LOG=1, KEEP_LCD=1 (ustawiane w środku)
```

### Przykładowy wynik (@320×240)
```
SSD: ~5 fps   |   HAAR: ~15 fps
```

Interpretacja: SSD (pełna detekcja) cięższy — stabilnie wykrywa „person” także bez widocznej twarzy; HAAR szybki, ale znika przy zasłonięciu twarzy.

---

## Kill‑switch (przed uruchomieniem)
```bash
bash scripts/camera_takeover_kill.sh
sudo raspi-gpio set 13 op dh   # backlight ON
```
Co robi: zabija typowe procesy/porty vendora (`yolostream.py`, itp.), zwalnia `/dev/spidev0.*`, czyści nasz lock.

---

## Pliki w tym wydaniu
- `apps/camera/preview_lcd_takeover.py` — podgląd + (opcjonalnie) HAAR, `BENCH_LOG`, `KEEP_LCD`.
- `apps/camera/preview_lcd_ssd.py` — SSD (OpenCV DNN); `SSD_EVERY`, `SSD_CLASSES`, `BENCH_LOG`, `KEEP_LCD`.
- `apps/camera/preview_lcd_hybrid.py` — **experimental**: SSD + tracker (KCF/CSRT) + HAAR.
- `scripts/bench_detect.sh` — benchmark SSD/HAAR (i łatwe do rozszerzenia o HYBRID).
- `scripts/camera_takeover_kill.sh` — mocniejszy pre‑kill i BL=ON.
- `models/...` — patrz wyżej.

---

## Zmienne środowiskowe (wybór)
- **Preview wspólne**: `PREVIEW_ROT`, `PREVIEW_WARMUP`, `PREVIEW_BORDER`, `PREVIEW_ALPHA`, `PREVIEW_BETA`, `SKIP_V4L2`.
- **HAAR**: `VISION_HUMAN`, `VISION_FACE_EVERY`.
- **SSD**: `SSD_SCORE`, `SSD_EVERY`, `SSD_CLASSES`, `SSD_PROTO`, `SSD_MODEL`.
- **Hybryda**: `TRACKER` (`kcf`/`csrt`), `FACE_EVERY`.
- **Bench/UX**: `BENCH_LOG=1` (drukuj FPS), `KEEP_LCD=1` (nie gaś BL na końcu).

---

## Changelog skrót
- **v0.4.7**: preview + HAAR (bench log + KEEP_LCD), SSD (every N, whitelist), HYBRID (exp), bench script, kill‑switch hard.
- **≤ v0.4.6**: patrz historia git.

---

## TODO / kolejne kroki
- Wybór ścieżki produkcyjnej: **HAAR** (interakcja) vs **SSD** (obecność osoby) vs **HYBRID** (gdy podniesiemy FPS).
- Ewentualny powrót do TFLite (EfficientDet‑Lite0) po rozwiązaniu zależności.
- Autonomia: unikanie przeszkód / świadomość przestrzenna (wizja: flow/size) — osobny wątek.

---

## Dev quick actions
```bash
# pre‑kill i BL ON
bash scripts/camera_takeover_kill.sh && sudo raspi-gpio set 13 op dh

# HAAR
SKIP_V4L2=1 PREVIEW_ROT=270 VISION_HUMAN=1 python3 -u apps/camera/preview_lcd_takeover.py

# SSD (person‑only, co 2 klatki)
SKIP_V4L2=1 PREVIEW_ROT=270 SSD_EVERY=2 SSD_CLASSES=person SSD_SCORE=0.55 \
python3 -u apps/camera/preview_lcd_ssd.py

# HYBRID (exp)
SKIP_V4L2=1 PREVIEW_ROT=270 SSD_SCORE=0.55 SSD_EVERY=3 FACE_EVERY=5 TRACKER=kcf \
python3 -u apps/camera/preview_lcd_hybrid.py

# Bench
./scripts/bench_detect.sh 20
```

