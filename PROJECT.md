# PROJECT.md

# Rider-Pi — sterowanie ruchem (bus ZMQ + REST + panel www)

> Minimalny, bezpieczny stos do zdalnego sterowania robotem XGO na Raspberry Pi: ZeroMQ bus, lekki Flask API, most do sterownika ruchu i prosty panel webowy.

## TL;DR

- **Usługi** (systemd): `rider-broker`, `rider-status-api`, `rider-motion-bridge`  
- **Porty busa**: PUB `5555` ⇄ SUB `5556` (broker: XSUB/XPUB)  
- **REST**: `GET /healthz`, `POST /api/move`, `POST /api/stop`  
- **Panel www**: prosty frontend (HTML/JS) z klawiszami WSAD/↑↓←→ i SSE `/events`  
- **Bezpieczeństwo**: `SAFE_MAX_DURATION`, „deadman” (auto-stop), `MIN_CMD_GAP`, `DRY_RUN`

---

## Architektura

```
[Panel WWW]  ──(REST/SSE)──> [status_api.py] ──(SUB)── ZMQ:5556
                                    │                         ▲
                                    ▼                         │
                             [broker.py XSUB/XPUB]  ZMQ  PUB:5555  SUB:5556
                                    ▲                         │
                                    │                         ▼
                              (PUB/SUB)                [motion_bridge.py]
                                                   (sprzęt XGO / dev/ttyAMA0)
```

- **broker.py** – pośrednik ZMQ (XSUB↔XPUB).  
- **status_api.py** – Flask REST + SSE `/events`; łączy się SUB na `tcp://127.0.0.1:5556`.  
- **motion_bridge.py** – most do napędu XGO; słucha **cmd.move/stop** i publikuje zdarzenia (telemetria, „ready”, „auto_stop” itp.).  
- **UI** – pojedynczy HTML z kontrolkami i skrótami klawiaturowymi; korzysta z REST i żywych zdarzeń (SSE).

---

## Endpoints REST

- `GET /healthz` — stan systemu i urządzeń (kamera, LCD, XGO: IMU, bateria, pozycja).
- `POST /api/move` — **{vx, vy, yaw, duration}** w zakresie **-1..1** (czas w sekundach).  
  - Przykład: `{"vx":0.7,"vy":0,"yaw":0,"duration":0.8}`
- `POST /api/stop` — awaryjne zatrzymanie.

> Mapowanie na napęd:  
> - **vx** → jazda przód/tył  
> - **vy** → strafe (jeśli platforma to wspiera)  
> - **yaw** → skręt w miejscu  
> Skalowanie prędkości kontrolują **SPEED_LINEAR** i **SPEED_TURN**.

---

## Zdarzenia SSE (`/events`)

- `vision.dispatcher.heartbeat` — obecność celu.  
- `motion.bridge.event` — m.in. `ready`, `rx_cmd.move`, `auto_stop`, `stop`.  
- `motion.state` — okresowa telemetria z mostka (watchdog, rampy, limity).

---

## Bezpieczeństwo ruchu

- **SAFE_MAX_DURATION** — twardy limit czasu pojedynczego impulsu (domyślnie 0.25 s).  
- **Deadman / auto_stop** — po czasie `duration` wysyłany jest automatyczny `stop`.  
- **MIN_CMD_GAP** — minimalny odstęp między kolejnymi komendami (anty-spam).  
- **DRY_RUN** — tryb „na sucho”: logi zamiast faktycznych wywołań napędu.  
- **Panel WWW** automatycznie wysyła stop przy wyjściu/ukryciu karty (page hide/unload).

---

## Konfiguracja ( `/etc/default/rider-pi` )

```bash
# Bus / API
BUS_PUB_PORT=5555
BUS_SUB_PORT=5556
STATUS_API_PORT=8080

# Tryb i limity
DRY_RUN=0                  # 1 = tylko logi; 0 = ruch fizyczny
SAFE_MAX_DURATION=0.25     # max czas pojedynczego ruchu (s)
MIN_CMD_GAP=0.10           # min przerwa między komendami (s)

# Skalowanie prędkości
SPEED_LINEAR=12            # m/s (skala wewnętrzna sterownika)
SPEED_TURN=20              # deg/s lub skala kątowa sterownika
```

> Zmiana wartości → `sudo systemctl restart rider-motion-bridge.service`

---

## Systemd (usługi)

`/etc/systemd/system/rider-broker.service`
```ini
[Unit]
Description=Rider-Pi ZMQ broker (XSUB/XPUB)
After=network-online.target
[Service]
User=pi
WorkingDirectory=/home/pi/robot
ExecStart=/usr/bin/python3 scripts/broker.py
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1
[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/rider-status-api.service`
```ini
[Unit]
Description=Rider-Pi Status API
After=network-online.target rider-broker.service
Requires=rider-broker.service
[Service]
User=pi
EnvironmentFile=/etc/default/rider-pi
WorkingDirectory=/home/pi/robot
ExecStart=/usr/bin/python3 scripts/status_api.py
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1
[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/rider-motion-bridge.service`
```ini
[Unit]
Description=Rider-Pi Motion Bridge
After=network-online.target rider-broker.service
Requires=rider-broker.service
[Service]
User=pi
EnvironmentFile=/etc/default/rider-pi
WorkingDirectory=/home/pi/robot
ExecStart=/usr/bin/python3 scripts/motion_bridge.py
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1
# (opcjonalnie log do pliku)
StandardOutput=append:/var/log/rider-motion-bridge.log
StandardError=append:/var/log/rider-motion-bridge.log
[Install]
WantedBy=multi-user.target
```

Aktywacja:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rider-broker.service rider-status-api.service rider-motion-bridge.service
```

---

## Testy (skrót)

Szybki smoke test:
```bash
# ports clean
sudo fuser -k 5555/tcp 5556/tcp || true

# restart usług
sudo systemctl restart rider-broker.service rider-status-api.service rider-motion-bridge.service
sleep 2

# /healthz (ok/degraded)
curl -s http://localhost:8080/healthz | jq .

# ruch + stop
curl -s -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0.7,"vy":0,"yaw":0,"duration":0.8}'
sleep 1
curl -s -X POST localhost:8080/api/stop -H 'Content-Type: application/json' -d '{}'
```

Automat:
```bash
chmod +x scripts/test_suite.sh
BUS_PUB_PORT=5555 BUS_SUB_PORT=5556 STATUS_API_PORT=8080 scripts/test_suite.sh
```

Podsłuch busa:
```bash
python3 scripts/bus_spy.py
```

---

## UI – panel WWW

- Sterowanie: **W/S/A/D** lub **↑/↓/←/→**, **Spacja** = stop.  
- Przełącznik **skręt (yaw)** / **strafe (vy)**.  
- Regulacja prędkości (0..1) i czasu [s].  
- Zdarzenia w czasie rzeczywistym: okienko logów (SSE).  
- Link „dashboard” – powrót do głównego widoku.

---

## Diagnostyka i znane przypadki

- **Porty zajęte** → `sudo fuser -v 5555/tcp 5556/tcp` (ubij procesy testowe/nohup).  
- **Błąd typu** `forward() takes 2 positional arguments...` – różnice w sygnaturach vendor API; obsłużone w mostku (log: `hw call error`), ruch i tak przechodzi.  
- **`SyntaxError ... global ... assigned before`** – naprawione w mostku (kolejność deklaracji).  
- **Bateria** – zewnętrzny wskaźnik bywa zawyżony; `/healthz` → `devices.xgo.battery_pct` jest wiarygodny.

---

## Roadmap (wycinek)

- Kalibracja mapowania `yaw` (większa rozdzielczość niskich prędkości).  
- E-stop sprzętowy i soft (GPIO / kombinacja klawiszy w panelu).  
- Tryb „trzymania klawisza” (ciągły ruch z limitem, bez spamowania API).  
- Telemetria IMU/poza w panelu (live).  
- Testy integracyjne „end-to-end” (REST→bus→HW) na CI.
