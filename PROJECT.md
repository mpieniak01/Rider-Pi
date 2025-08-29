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
  - `apps/camera/preview_lcd_ssd.py` – SSD (dokładniejsze, wolniejsze).  
  - `apps/camera/preview_lcd_hybrid.py` – tracker + SSD co N.

  Publikują:  
  - `vision.face` (HAAR)  
  - `vision.person` (SSD/hybrid)

- **Dispatcher obecności**  
  `apps/vision/dispatcher.py` – normalizacja + histereza/debouncing.  
  Subskrybuje `vision.face/person/detections`, publikuje:
  - `vision.state` (boolean + confidence)  
  - `vision.dispatcher.heartbeat` (co 5 s)  

- **Status API + Dashboard**  
  `scripts/status_api.py` (Flask 1.x – zgodny na Buster/Bullseye)  
  - `/` – mini dashboard (HTML/JS, auto-refresh co 2 s)
  - `/healthz`, `/state`, **`/sysinfo`** (CPU/MEM/LOAD/DISK/TEMP)
  - **`/metrics`** (Prometheus-style, opcjonalne scrapowanie)
  - **`/events`** (SSE – podgląd ostatnich zdarzeń z busa)

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

# API
STATUS_API_PORT=8080
```

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

Przykład:
```bash
curl -s http://127.0.0.1:8080/healthz | jq
curl -s http://127.0.0.1:8080/sysinfo  | jq
```

---

## 6) Uruchomienie podglądu z kamery (manual)

```bash
# HAAR
PREVIEW_ROT=270 python3 -u apps/camera/preview_lcd_takeover.py

# SSD (co 2–3 klatki)
PREVIEW_ROT=270 SSD_EVERY=3 SSD_SCORE=0.55 python3 -u apps/camera/preview_lcd_ssd.py

# HYBRID (tracker + SSD co N)
PREVIEW_ROT=270 SSD_EVERY=3 SSD_SCORE=0.55 HYBRID_HAAR=1 LOG_EVERY=10 \
python3 -u apps/camera/preview_lcd_hybrid.py
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

## 12) Roadmap (krótko)

- Przyciski **Pause / Clear** wykresu + link do `/events` na dashboardzie.  
- (opcjonalnie) prosty alarm na UI (kolory) przy wysokim CPU/MEM.  
- Persistencja konfiguracji w `common/` i ujednolicenie importów.

---

## 13) Changelog (wycinek)

- **2025-08-29 – stable**
  - `scripts/status_api.py`: mini-dashboard + `/sysinfo` + wykres CPU/MEM (60 s) + `/metrics` + `/events`.
  - `apps/vision/dispatcher.py`: debouncing/histereza + `vision.state` + heartbeat.
  - `systemd` jednostki: broker, dispatcher, api (ENV z `.env`).
  - Testy: `smoke_test.sh`, `bench_detect.sh` (progi PASS/FAIL).

- **2025-08-28 – camera preview updates**
  - HAAR/SSD/Hybrid, whitelist klas SSD, log fps, cleanup kill.

---


