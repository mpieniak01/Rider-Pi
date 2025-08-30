# Rider-Pi — PROJECT.md

Mały, samowystarczalny system wizyjny na Raspberry Pi z magistralą ZMQ, lekkim **dispatcherem** obecności i **mini-dashboardem** w Flasku.

> **Stan:** stabilny build (29.08.2025) – broker + dispatcher + API + testy smoke/bench.

---

## 1) Architektura (skrót)

- **Bus (ZMQ)**  
  `scripts/broker.py` – prosty XSUB⇄XPUB.  
  *IN/OUT porty:* `BUS_PUB_PORT` (PUB) / `BUS_SUB_PORT` (SUB).

- **Producenci zdarzeń (kamera)**  
  - `apps/camera/preview_lcd_takeover.py` – HAAR (szybkie).  
  - `apps/camera/preview_lcd_ssd.py` – SSD (dokładniejsze).  
  - `apps/camera/preview_lcd_hybrid.py` – tracker + SSD co N.  
  Publikują:
  - `vision.face` (HAAR), `vision.person` (SSD/hybrid)
  - **`camera.heartbeat`** (tryb, fps, stan LCD)
  - (opcjonalnie) snapshoty do `snapshots/cam.jpg` (RAW) i `snapshots/proc.jpg` (po obróbce)

- **Dispatcher obecności**  
  `apps/vision/dispatcher.py` – normalizacja + histereza/debouncing.  
  IN: `vision.face/person/detections` → OUT:
  - `vision.state` (boolean + confidence + ts)
  - `vision.dispatcher.heartbeat` (co 5 s)

- **Status API + Dashboard**  
  `scripts/status_api.py` (Flask 1.x) + **zewnętrzny HTML** `web/view.html`  
  - `/` – dashboard (przegląd systemu + 2× podgląd: RAW/PROC)  
  - `/healthz`, `/state`, `/sysinfo`, `/metrics`, `/events` (SSE)  
  - **`/snapshots/<fn>`** – serwowanie JPG (cam.jpg, proc.jpg, lcd.jpg)

---

## 2) Wymagane pakiety

Raspberry Pi OS (libcamera):

```bash
sudo apt-get update
sudo apt-get install -y python3-flask python3-pip python3-opencv \
                        python3-zmq python3-pil
# (opcjonalnie Picamera2 / zależne od obrazu)
# sudo apt-get install -y python3-picamera2
```

---

## 3) Zmienne środowiskowe (`.env`)

W repo jest **`.env.sample`** – skopiuj jako `.env` i dopasuj:

```ini
# Bus (ZMQ)
BUS_PUB_PORT=5555
BUS_SUB_PORT=5556

# API
STATUS_API_PORT=8080
```

# Vision dispatcher
VISION_ON_CONSECUTIVE=3     # ile kolejnych pozytywów żeby włączyć present=true
VISION_OFF_TTL_SEC=2.0      # czas bez pozytywnych, po którym gasimy
VISION_MIN_SCORE=0.50       # minimalny score pozytywu

# Kamera / preview
PREVIEW_ROT=270             # rotacja LCD (90/180/270)
DISABLE_LCD=0               # 1 = bez rysowania na LCD (headless)
NO_DRAW=0                   # 1 = nie rysuj ramek/tekstów (oszczędza CPU)
SKIP_V4L2=1                 # preferuj Picamera2; gdy brak, video0

# SSD/Hybrid
SSD_EVERY=2                 # co ile klatek uruchomić SSD
SSD_SCORE=0.55              # minimalny score detekcji
SSD_CLASSES=person          # whitelist klasa/klasy (CSV)
HYBRID_HAAR=1               # hybrid: HAAR w ROI trackera (0/1)
LOG_EVERY=10                # co ile klatek logować fps (hybrid)

# Snapshoty (RAW/PROC/LCD)
SNAPSHOT_ENABLE=1
SNAP_CAM_EVERY=1       # co ile klatek RAW
SNAP_PROC_EVERY=1      # co ile klatek PROC
SNAP_LCD_EVERY=5       # co ile klatek LCD (jeśli dostępny fb)



Podgląd aktywnych ENV uruchomionej usługi:
```bash
PID=$(systemctl show -p MainPID --value rider-broker)
sudo tr '\0' '\n' < /proc/$PID/environ | sort
```

---

## 4) Usługi systemd

Pliki:
- `systemd/rider-broker.service`
- `systemd/rider-dispatcher.service`
- `systemd/rider-api.service`

Instalacja/aktualizacja:
```bash
sudo cp systemd/rider-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rider-broker rider-dispatcher rider-api
systemctl --no-pager --full status rider-broker rider-dispatcher rider-api
```

> Wszystkie jednostki ładują `/home/pi/robot/.env` przez `EnvironmentFile=` i mają krótkie `ExecStartPre=/bin/sleep 0.5` (sekwencja: broker → dispatcher → api).

---

## 5) Endpoints API

- `GET /` – mini dashboard  
  - karty: *Health*, *Presence*, *System* (CPU, load, mem, disk, temp)  
  - wykres **CPU% / MEM% (60 s, 1–2 s refresh)**
- `GET /healthz` → `{status, uptime_s, bus:{last_msg_age_s, last_heartbeat_age_s}}`
- `GET /state`   → `{present, confidence, ts, age_s}`
- `GET /sysinfo` → `{cpu_pct, load1/5/15, mem_* , disk_*, temp_c, ts, age_s}`
- `GET /metrics` → Prometheus-style (`rider_*` metryki)
- `GET /events`  → SSE (ostatnie zdarzenia z busa, do podglądu live)
- `GET /snapshots/<fn> → cam.jpg, proc.jpg, lcd.jpg

Przykład:
```bash
curl -s http://127.0.0.1:8080/healthz | jq
curl -s http://127.0.0.1:8080/sysinfo  | jq
```

---

## 6) Uruchomienie podglądu z kamery (manual)

A) Kamera + snapshoty (bez fizycznego LCD)
cd ~/robot
export PYTHONPATH=$PWD
export DISABLE_LCD=1 NO_DRAW=0 PREVIEW_ROT=270
export SNAPSHOT_ENABLE=1 SNAP_CAM_EVERY=1 SNAP_PROC_EVERY=1
python3 -u apps/camera/preview_lcd_ssd.py

B) Dispatcher obecności
cd ~/robot
export PYTHONPATH=$PWD
python3 -u apps/vision/dispatcher.py

C) Dashboard / API
cd ~/robot
export PYTHONPATH=$PWD STATUS_API_PORT=8008
python3 -u scripts/status_api.py
# otwórz: http://<IP_RPi>:8008/
```

**Uwaga:** wyniki fps są niższe, gdy rysujemy na LCD – do benchmarku używaj trybu *headless* (patrz niżej).

---

## 7) Testy: smoke & bench

### Smoke (z LCD)
Szybkie sprawdzenie, że wszystkie trzy pipeline’y (HAAR → SSD → HYBRID) startują i sprzątają kamerę/LCD:
```bash
./scripts/smoke_test.sh 3
# [SMOKE PASS] + exit 0
```

### Bench (headless domyślnie)
Trzy przebiegi (HAAR/SSD/HYBRID), parsowanie fps i progi PASS/FAIL:
```bash
DISABLE_LCD=1 NO_DRAW=1 BENCH_LOG=1 ./scripts/bench_detect.sh 10
# [bench] HAAR/SSD/HYBRID: fps=...
# [bench] PASS: all >= thresholds (HAAR>=12, SSD>=4, HYBRID>=3)
```

**Tip:** `LOG_EVERY=10` ogranicza spam logów w hybrid.

---

## 8) Debug busa (narzędzia)

- Subskrypcja wszystkiego:
  ```bash
  python3 -u scripts/sub.py
  ```
- Ręczne wysłanie stanu:
  ```python
  import os, zmq, time, json
  s=zmq.Context.instance().socket(zmq.PUB)
  s.connect(f"tcp://127.0.0.1:{os.getenv('BUS_PUB_PORT','5555')}")
  s.send_string("vision.state "+json.dumps({"present": True, "confidence": 0.9, "ts": time.time()}))
  ```

---

## 9) LCD sanity-check

Jeśli dashboard działa, ale nic nie widać na LCD – szybki test:
```python
from xgoscreen.LCD_2inch import LCD_2inch
from PIL import Image, ImageDraw
lcd = LCD_2inch(); lcd.rotation = 270
img = Image.new("RGB",(320,240),(0,0,0))
d = ImageDraw.Draw(img); d.rectangle([10,10,310,230], outline=(0,255,0), width=3); d.text((20,20),"LCD OK",(255,255,255))
lcd.ShowImage(img)
```

---

## 10) Prometheus (opcjonalnie)

Nie wymagany. Jeśli chcesz, endpoint `/metrics` jest gotowy do scrapowania.
Przykładowy minimalny scrap:
```yaml
scrape_configs:
  - job_name: riderpi
    scrape_interval: 15s
    metrics_path: /metrics
    static_configs: [{ targets: ['192.168.1.71:8080'] }]
```
Na RPi nie uruchamiamy Prometheusa (oszczędność CPU/RAM) – lepiej z zewnętrznego hosta.

---

## 11) FAQ / Troubleshooting

- **Address already in use (tcp://*:5555)**  
  Broker już działa. Sprawdź:
  ```bash
  systemctl status rider-broker
  sudo ss -ltnp | grep ':5555\|:5556'
  ```
- **API bez danych z busa**  
  Upewnij się, że `rider-dispatcher` działa i że pipeline kamery publikuje eventy.  
  Health `status: degraded` → brak heartbeatów >10 s.

- **Bench nie widzi fps (HYBRID)**  
  Upewnij się, że `apps/camera/preview_lcd_hybrid.py` jest wykonany `chmod +x` i loguje linie `[hybrid] fps=...`.

- **LCD zjada fps**  
  Do bench używaj `DISABLE_LCD=1 NO_DRAW=1`.

---


# 13) LCD & Camera heartbeat

- **Heartbeat kamery** – wszystkie trzy pipeline’y (`takeover`, `ssd`, `hybrid`) publikują teraz event:
  - `camera.heartbeat` → `{ ts, mode, fps, lcd:{rot, active, presenting, no_draw} }`
  - dzięki temu `/healthz` i dashboard wiedzą, czy kamera działa, nawet jeśli pipeline został uruchomiony ręcznie (spoza systemd).
  - TTL kontrolowany przez `CAMERA_ON_TTL_SEC` (domyślnie 3 s).

- **Dashboard – Devices → Camera**
  - Pokazuje teraz:
    - tryb (`haar` / `ssd` / `hybrid`)
    - rozdzielczość i fps
    - stan LCD (`ON/OFF`, `rot`, `presenting`, `no_draw`)
    - wiek ostatniego heartbeat (s).
  - Gdy kamera jest OFF, widać czas od ostatniego heartbeat – ułatwia debug.

- **LCD**
  - Obsługa rysowania przez `xgoscreen.LCD_2inch`.
  - Możliwość wyłączenia całkowicie (`DISABLE_LCD=1`) lub tylko ramek (`NO_DRAW=1`).
  - Dodana opcja rotacji (`PREVIEW_ROT=90/180/270`).
  - Test sanity: `PROJECT.md → §9 LCD sanity-check`.

- **API rozszerzone o devices.camera**
  ```json
  "camera": {
    "on": true,
    "age_s": 0.25,
    "mode": "haar",
    "fps": 12.3,
    "lcd": { "rot": 270, "active": true, "presenting": true, "no_draw": false }
  }

# 14) Changelog (wycinek)

2025-08-30

 - Wydzielenie frontu do web/view.html (czystszy status_api.py).
 - Nowy moduł common/snap.py + endpoint /snapshots/<fn>.
 - Dashboard: dwie kolumny podglądu Camera view: RAW (cam.jpg) i PROC (proc.jpg).
 - camera.heartbeat (tryb/fps/lcd) konsumowany w /healthz.
 - Uporządkowane /sysinfo z historią CPU/MEM (60 pkt).

2025-08-29 – stable

- status_api.py: mini-dashboard + /sysinfo + /metrics + /events.
- apps/vision/dispatcher.py: debouncing/histereza + vision.state + heartbeat.
- Jednostki systemd, testy: smoke/bench.

---


