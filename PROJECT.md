# Rider‑Pi — projekt

> Minimalny stos do demonstracji wizji (HAAR/SSD/hybrid) na Raspberry Pi z magistralą ZMQ, prostym **dispatcherem** i **Status API** (Flask). Gotowy do uruchomienia jako usługi systemd.

---

## TL;DR (Quickstart)
```bash
# 1) Klon + deps (Raspberry Pi OS)
sudo apt-get update -y && sudo apt-get install -y \
  python3-pip python3-flask python3-zmq libatlas-base-dev \
  libcamera-apps git jq lsof

# 2) Skonfiguruj środowisko
tcp && cd ~/robot
cp .env.sample .env   # potem ewentualnie edytuj porty/parametry

# 3) Systemd: broker + dispatcher + status API
sudo cp systemd/rider-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rider-broker rider-dispatcher rider-api

# 4) Szybki healthcheck
curl -s http://127.0.0.1:8080/healthz | jq
curl -s http://127.0.0.1:8080/state   | jq

# 5) Smoke & bench
a) ./scripts/smoke_test.sh 3
b) DISABLE_LCD=1 NO_DRAW=1 BENCH_LOG=1 ./scripts/bench_detect.sh 10
```

---

## Struktura repo (skrócona)
```
robot/
├─ apps/
│  ├─ camera/
│  │  ├─ preview_lcd_takeover.py   # HAAR
│  │  ├─ preview_lcd_ssd.py        # SSD (lite)
│  │  └─ preview_lcd_hybrid.py     # SSD + tracker (+ opcjonalnie HAAR)
│  └─ vision/
│     └─ dispatcher.py             # normalizacja zdarzeń + histereza -> vision.state
├─ scripts/
│  ├─ broker.py                    # ZMQ XSUB<->XPUB broker
│  ├─ status_api.py                # Flask /healthz, /state
│  ├─ bench_detect.sh              # pomiar FPS; logi [bench] ...
│  ├─ smoke_test.sh                # krótki sanity test 3× preview
│  ├─ camera_takeover_kill.sh      # porządne ubijanie kamerowych procesów
│  └─ sub.py                       # subskrypcja ZMQ (debug)
├─ systemd/
│  ├─ rider-broker.service
│  ├─ rider-dispatcher.service
│  └─ rider-api.service            # Flask Status API (Wants: broker, dispatcher)
├─ .env.sample                     # przykładowa konfiguracja środowiska
└─ PROJECT.md                      # ten dokument
```

---

## Konfiguracja (`.env`)
Skopiuj `.env.sample` do `.env` i dostosuj w razie potrzeby.

```dotenv
# ZMQ bus
BUS_PUB_PORT=5555
BUS_SUB_PORT=5556

# LCD / podgląd
PREVIEW_ROT=270
DISABLE_LCD=0
NO_DRAW=0

# SSD / HYBRID
SSD_EVERY=2
SSD_SCORE=0.55
SSD_CLASSES=person
HYBRID_HAAR=1

# Dispatcher (histereza)
VISION_ON_CONSECUTIVE=3
VISION_OFF_TTL_SEC=2.0
VISION_MIN_SCORE=0.50

# Status API
STATUS_API_PORT=8080
```

> **Uwaga:** plik `.env` jest czytany przez unity systemd (EnvironmentFile=/home/pi/robot/.env). W repo trzymamy **`.env.sample`** (bez sekretów), a `.env` – lokalnie.

---

## Usługi systemd

### rider-broker
- uruchamia broker ZMQ (XSUB\<->XPUB) — łączy publisherów i subskrybentów.
- adresy: `tcp://*:5555` (XSUB), `tcp://*:5556` (XPUB)

### rider-dispatcher
- subskrybuje: `vision.face`, `vision.person`, `vision.detections`
- normalizuje detekcje, stosuje histerezę i publikuje `vision.state`
- **po starcie wysyła stan początkowy** (`present=false`) — żeby `/state` w API nie było puste
- okresowo publikuje heartbeat: `vision.dispatcher.heartbeat`

### rider-api
- prosty Flask z dwoma endpointami:
  - `GET /healthz` — status brokera/dispatchera (na podstawie *age* ostatnich wiadomości)
  - `GET /state` — ostatni stan z `vision.state`
- **Powiązanie**: `Wants=rider-broker.service rider-dispatcher.service` (zamiast `Requires=`), żeby API nie restartowało się na każdy restart dispatchera.

#### Instalacja/zarządzanie
```bash
sudo cp systemd/rider-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rider-broker rider-dispatcher rider-api

# status i logi
systemctl --no-pager --full status rider-*
journalctl -u rider-api -n 50 --no-pager
```

---

## Status API

### Endpointy
- `GET /healthz` →
```json
{
  "status": "ok|degraded",
  "uptime_s": 12.345,
  "bus": {
    "last_msg_age_s": 0.123,
    "last_heartbeat_age_s": 2.345
  }
}
```
- `GET /state` →
```json
{
  "present": false,
  "confidence": 0.0,
  "ts": 1756466761.4314544,
  "age_s": 1.234
}
```

### Przykłady
```bash
PORT=${STATUS_API_PORT:-8080}
curl -s http://127.0.0.1:$PORT/healthz | jq
curl -s http://127.0.0.1:$PORT/state   | jq
```

> Jeśli `/healthz` = `degraded`, sprawdź czy dispatcher publikuje heartbeat (`vision.dispatcher.heartbeat`) oraz czy pojawił się pierwszy `vision.state` (dispatcher wysyła go przy starcie).

---

## Podgląd z kamery (preview)
Skrypty wyświetlają pogląd na LCD (jeśli `DISABLE_LCD=0` oraz zainstalowany `xgoscreen`). W testach wydajności zalecane `DISABLE_LCD=1` i `NO_DRAW=1`.

```bash
# HAAR
python3 -u apps/camera/preview_lcd_takeover.py

# SSD (co N klatek)
SSD_EVERY=2 SSD_SCORE=0.55 SSD_CLASSES=person \
python3 -u apps/camera/preview_lcd_ssd.py

# HYBRID (SSD + tracker + opcjonalnie HAAR)
SSD_EVERY=3 HYBRID_HAAR=1 LOG_EVERY=10 \
python3 -u apps/camera/preview_lcd_hybrid.py
```

---

## Dispatcher (logika obecności)
- **Wejście**: `vision.face`, `vision.person`, `vision.detections`
- Normalizacja do: `{kind, present, score, bbox}`
- **Histereza**:
  - `VISION_ON_CONSECUTIVE` — ile kolejnych pozytywów, by uznać `present=true`
  - `VISION_OFF_TTL_SEC` — po ilu sekundach bez pozytywów `present=false`
  - `VISION_MIN_SCORE` — minimalny score, by uznać detekcję
- **Wyjście**: `vision.state {present, confidence, ts}` + heartbeat `vision.dispatcher.heartbeat`

---

## Testy

### Pytest
```bash
pytest -q
# oczekiwane: 1 passed (prosty test importów i sanity check)
```

### Smoke test (3× krótki run podglądu)
```bash
./scripts/smoke_test.sh 3
# oczekiwane: [SMOKE PASS]
```

### Bench (FPS)
```bash
DISABLE_LCD=1 NO_DRAW=1 BENCH_LOG=1 ./scripts/bench_detect.sh 10
# oczekiwane: [bench] PASS: all >= thresholds (HAAR>=12, SSD>=4, HYBRID>=3)
```

---

## Debugging / FAQ

- **Port zajęty** (`Address already in use`):
  ```bash
  sudo lsof -iTCP:5555 -sTCP:LISTEN -n -P
  sudo lsof -iTCP:5556 -sTCP:LISTEN -n -P
  sudo lsof -iTCP:8080 -sTCP:LISTEN -n -P
  ```
- **API „degraded”**: zobacz logi i handshake ZMQ
  ```bash
  journalctl -u rider-api -n 50 --no-pager
  python3 -u scripts/sub.py | grep -E '^vision\.'
  ```
- **LCD** (xgoscreen): sprawdź minimalny test z ramką (patrz historia w wątku). W testach wydajności ustaw `DISABLE_LCD=1`.
- **Systemd**: status + logi
  ```bash
  systemctl --no-pager --full status rider-*
  journalctl -u rider-broker -n 50 --no-pager
  journalctl -u rider-dispatcher -n 50 --no-pager
  journalctl -u rider-api -n 50 --no-pager
  ```

---

## Workflow dev
- Gałąź `main` (jeden deweloper + AI). Tagowanie wersji **opcjonalnie** (na razie bez tagów).
- Commit messages: `feat:`, `fix:`, `chore:`, `docs:` itp.
- PR/Code review – w miarę rozwoju.

---

## Roadmap / TODO
- [ ] UI `/status` (HTML + auto-refresh, wykres FPS i stan obecności)
- [ ] `common/bus.py` (wspólny wrapper ZMQ dla preview/dispatcher/API)
- [ ] Ujednolicenie logów (`structlog`/`logging` JSON)
- [ ] Więcej testów: symulacje zdarzeń, testy histerezy
- [ ] Export metryk (Prometheus) + alerts
- [ ] Opakowanie w `setup.py`/`uv` i/lub Docker dla dev

---


