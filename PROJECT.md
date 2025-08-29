# Rider‑Pi — projekt i szybki start

> Ten projekt to **sandbox** do ćwiczenia programowania robota Rider‑Pi (CM4 + LCD 2''). Repo nie jest oficjalnym firmware producenta.

## Spis treści
- [Struktura repozytorium](#struktura-repozytorium)
- [Szybki start (podgląd + eventy)](#szybki-start-podgląd--eventy)
- [Komunikacja (bus ZMQ)](#komunikacja-bus-zmq)
- [Dispatcher wizji](#dispatcher-wizji)
- [Podglądy kamery](#podglądy-kamery)
- [Testy: smoke i bench](#testy-smoke-i-bench)
- [Jednostkowe: pytest](#jednostkowe-pytest)
- [Systemd (autostart podglądu)](#systemd-autostart-podglądu)
- [Zmienne środowiskowe (FAQ)](#zmienne-środowiskowe-faq)
- [Troubleshooting](#troubleshooting)

---

## Struktura repozytorium
```
apps/
  camera/
    preview_lcd_takeover.py   # HAAR face; szybki FPS
    preview_lcd_ssd.py        # MobileNet-SSD (person)
    preview_lcd_hybrid.py     # SSD + tracker (+ opcj. HAAR w ROI)
  vision/
    dispatcher.py             # łączy eventy detektorów -> vision.state

common/                       # (wspólne rzeczy; prosty bus jest inline)

scripts/
  broker.py                   # prosty ZMQ XPUB/XSUB broker
  sub.py                      # subskrybent do podglądu topiców
  camera_takeover_kill.sh     # gasi kamerę/preview i vendor overlay
  smoke_test.sh               # krótki test pipelines
  bench_detect.sh             # benchmark FPS (headless domyślnie)

systemd/
  rider-camera-preview.service

PROJECT.md, README.md, .gitattributes, .gitignore
```

> Uwaga: **tagów Git** nie używamy na start (1 dev + AI). Podpisy GPG wyłączone. `.gitattributes` wymusza `LF` dla `.py/.sh`.

---

## Szybki start (podgląd + eventy)
W 3 terminalach:

**T1 — broker:**
```bash
cd ~/robot
python3 -u scripts/broker.py
```

**T2 — dispatcher:**
```bash
cd ~/robot
python3 -u apps/vision/dispatcher.py
```

**T3 — podgląd (HAAR):**
```bash
cd ~/robot
export PREVIEW_ROT=270
python3 -u apps/camera/preview_lcd_takeover.py
```

Podgląd na LCD; eventy zobaczysz tak:
```bash
python3 -u scripts/sub.py | grep -E 'vision\.(face|person|state|dispatcher\.heartbeat)'
```
Zatrzymanie i sprzątanie:
```bash
./scripts/camera_takeover_kill.sh
```

---

## Komunikacja (bus ZMQ)
- Domyślne porty: `BUS_PUB_PORT=5555` (publisher), `BUS_SUB_PORT=5556` (subscriber).
- Wszystkie moduły czytają porty z **ENV**.
- Szybki test busa:
```bash
# terminal A
python3 -u scripts/sub.py | grep test.bus &
# terminal B
python3 - <<'PY'
import os, zmq; s=zmq.Context.instance().socket(zmq.PUB)
s.connect(f"tcp://127.0.0.1:{os.getenv('BUS_PUB_PORT','5555')}")
s.send_string('test.bus {"hi":1}')
PY
```

---

## Dispatcher wizji
Plik: `apps/vision/dispatcher.py`

Zadania:
- normalizuje eventy z topiców **IN**: `vision.face`, `vision.person`, `vision.detections` →
  `{kind,present,score,bbox}`
- histereza: `VISION_ON_CONSECUTIVE` pozytywów włącza `present=true`, brak pozytywów przez `VISION_OFF_TTL_SEC` gasi stan
- publikuje topic **OUT**: `vision.state {present, confidence, ts}` + heartbeat `vision.dispatcher.heartbeat`

Domyślne progi (ENV):
```
VISION_ON_CONSECUTIVE=3
VISION_OFF_TTL_SEC=2.0
VISION_MIN_SCORE=0.50
```

---

## Podglądy kamery
Trzy skrypty LCD z przełącznikami:

- `preview_lcd_takeover.py` — HAAR (twarze), szybki
- `preview_lcd_ssd.py` — MobileNet‑SSD (klasa `person` i whitelista klas)
- `preview_lcd_hybrid.py` — SSD co N klatek + tracker (KCF domyślnie) + opcj. HAAR w ROI

Wspólne **ENV**:
```
PREVIEW_ROT=270           # rotacja LCD (90/180/270)
DISABLE_LCD=0             # 1 = bez rysowania na LCD (headless)
NO_DRAW=0                 # 1 = nie rysuj ramek/tekstów (oszczędza CPU)
SKIP_V4L2=1               # preferuj Picamera2; gdy brak, wideo0
```

Specyficzne **ENV**:
```
# SSD/Hybrid
SSD_EVERY=2               # co ile klatek uruchomić SSD
SSD_SCORE=0.55            # minimalny score detekcji
SSD_CLASSES=person        # whitelista nazw klas (CSV)
HYBRID_HAAR=1             # w hybrid: HAAR w ROI trackera (0/1)
LOG_EVERY=20              # co ile klatek logować fps (hybrid)
```

Publikowane topiki:
- `vision.face {present, score, count}` (HAAR / HAAR w ROI)
- `vision.person {present, score, bbox}` (SSD / tracker)

---

## Testy: smoke i bench

### Smoke (z podglądem na LCD)
```bash
./scripts/smoke_test.sh 3
# [SMOKE PASS] i exit 0
```
Test uruchamia po ~3 s: HAAR → SSD → HYBRID i sprząta kamerę/LCD.

### Bench (headless domyślnie)
```bash
DISABLE_LCD=1 NO_DRAW=1 BENCH_LOG=1 ./scripts/bench_detect.sh 10
# [bench] HAAR/SSD/HYBRID: fps=...  → PASS/FAIL progów
```
Progi (konfigurowalne):
```
BENCH_MIN_FPS_HAAR=12
BENCH_MIN_FPS_SSD=4
BENCH_MIN_FPS_HYB=3
```
> Tip: headless zwykle +5–20% FPS vs LCD ON.

---

## Jednostkowe: pytest
Test logiki histerezy dispatchera:
```bash
pytest -q
# 1 passed in ...s
```
Plik: `tests/test_vision_dispatcher.py` (sprawdza włączenie/wyłączenie `present`).

---

## Systemd (autostart podglądu)
Plik usługi: `systemd/rider-camera-preview.service` (przeniesiony z `apps/camera/`).

Szkic (przykład):
```ini
[Unit]
Description=Rider-Pi Camera Preview (HAAR)
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/pi/robot
Environment=PREVIEW_ROT=270
ExecStart=/usr/bin/python3 -u apps/camera/preview_lcd_takeover.py
ExecStop=/home/pi/robot/scripts/camera_takeover_kill.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
```
Instalacja:
```bash
sudo cp systemd/rider-camera-preview.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rider-camera-preview
```

---

## Zmienne środowiskowe (FAQ)
```
BUS_PUB_PORT=5555  BUS_SUB_PORT=5556
PREVIEW_ROT=270    SKIP_V4L2=1
DISABLE_LCD=0      NO_DRAW=0
SSD_EVERY=2        SSD_SCORE=0.55    SSD_CLASSES=person
HYBRID_HAAR=1      LOG_EVERY=20
VISION_ON_CONSECUTIVE=3  VISION_OFF_TTL_SEC=2.0  VISION_MIN_SCORE=0.5
KEEP_LCD=0         # 1 = nie wygaszaj BL po killerze
```

---

## Troubleshooting
- **Port 5555 zajęty** → broker już działa. Albo użyj istniejącego, albo `pkill -f scripts/broker.py`.
- **„device info” na LCD** → uruchom `./scripts/camera_takeover_kill.sh`, upewnij się że nie masz `DISABLE_LCD=1`. Test LCD:
  ```bash
  python3 - <<'PY'
  from xgoscreen.LCD_2inch import LCD_2inch
  from PIL import Image, ImageDraw
  lcd=LCD_2inch(); lcd.rotation=270
  img=Image.new('RGB',(320,240),(0,0,0))
  ImageDraw.Draw(img).text((20,20),'LCD OK', fill=(255,255,255))
  lcd.ShowImage(img)
  PY
  ```
- **Zero sequence expected…** (pierwsza klatka V4L2) — informacja; ignoruj.
- **Brak `pyzmq`/`opencv-python`** → `pip3 install pyzmq opencv-python`.

---

### Notatki implementacyjne
- `vendor_splash.py` wyłączany warunkowo w killerze (gdy istnieje).
- LCD import odporny na różne struktury pakietu: `from xgoscreen.LCD_2inch import LCD_2inch` z fallbackiem.
- Bench zbiera całe stdout i parsuje ostatnie `fps=…`; liczby zwraca „czysto”, logi na stderr.

---

## Publikacja zmian (Git)
1. Zapisz pliki i sprawdź testy:
   ```bash
   ./scripts/smoke_test.sh 3 && \
   DISABLE_LCD=1 NO_DRAW=1 BENCH_LOG=1 ./scripts/bench_detect.sh 10 && \
   pytest -q
   ```
2. Commit & push:
   ```bash
   git add PROJECT.md apps/camera/preview_lcd_* scripts/bench_detect.sh scripts/camera_takeover_kill.sh
   git commit -m "docs(PROJECT): quick start, bus, dispatcher, LCD switches; smoke/bench; troubleshooting"
   git push
   ```


