# Rider‑Pi — projekt (FINAL)

## TL;DR
Rider‑Pi to lekki, samodzielny stos do sterowania robotem (XGO/ESP/itp.) na Raspberry Pi. Składa się z magistrali **ZeroMQ (XSUB↔XPUB)**, usługi **Status API (Flask/REST + SSE)** oraz **Motion Bridge** (most sprzętowy do napędu). Działa jako zestaw usług **systemd**, ma prosty front WWW i komplet bezpieczników (watchdog, deadman/auto‑stop, limity impulsów i odstępów). Wspiera kompatybilnościowy endpoint **/control** (PUB na busie).

---

## Najważniejsze cechy
- **Asynchroniczna szyna ZMQ**: tematy `cmd.*`, `motion.*`, `vision.*`, `chat.*`.
- **REST API**: `/api/move`, `/api/stop`, `/healthz` + **SSE** `/events` (log/telemetria).
- **Motion Bridge**: mapowanie komend bus/REST → wywołania HW (np. XGO); tryb **DRY_RUN**.
- **Bezpieczeństwo**:
  - twardy limit czasu impulsu: `SAFE_MAX_DURATION` (domyślnie 0.25 s),
  - ogranicznik częstości: `MIN_CMD_GAP` (domyślnie 0.1 s),
  - automatyczny **deadman/auto_stop**,
  - skalary prędkości: `SPEED_LINEAR`, `SPEED_TURN`.
- **systemd** + spójne logi (opcjonalnie do plików w `/var/log/`).
- **Web UI**: sterowanie W/A/S/D/strzałki, status health, log SSE.
- **Narzędzia testowe**: pub/sub, bus‑spy, testy ruchu.

---

## Architektura
```
        +------------------+            +----------------------+
        |  Web UI (HTML)   |  REST/SSE  |  status_api.py       |
        |  / sterowanie     +----------->  /healthz, /api/*     |
        +---------+--------+            +----------+-----------+
                  ^                                  |
                  |                                  | PUB/SUB (ZMQ)
                  |                                  v
+-----------------+--------------------+   +---------+----------------+
|  Klienci (testy, skrypty, itp.)     |   |  broker.py (XSUB↔XPUB)   |
|  curl / bus_spy / vision / chat     |   |  tcp://*:5555 / 5556     |
+-----------------+--------------------+   +---------+----------------+
                                                      |
                                                      v
                                          +-----------+------------+
                                          | motion_bridge.py       |
                                          |  DRY_RUN / HW (XGO)    |
                                          +-----------+------------+
                                                      |
                                                      v
                                                Sprzęt (napęd)
```
Porty domyślne: **5555** (XSUB), **5556** (XPUB), **8080** (HTTP API).

---

## Struktura repo (konwencja)
```
robot/
├─ services/                    # runtime (broker/API/bridge/diag)
│  ├─ broker.py
│  ├─ status_api.py
│  ├─ motion_bridge.py
│  ├─ bus_spy.py
│  ├─ manual_drive.py
│  ├─ test_motion.py
│  └─ test_motion_bus.py
├─ web/
│  └─ control.html             # panel sterowania (REST/SSE)
├─ systemd/
│  ├─ rider-broker.service
│  ├─ rider-status-api.service
│  ├─ rider-motion-bridge.service
│  ├─ robot-chat.service       # opcjonalne
│  └─ robot-voice.service      # opcjonalne
├─ tools/                      # prosty pub/sub, itp.
│  ├─ pub.py
│  └─ sub.py
├─ Makefile
└─ README.md
```

---

## Komponenty
### 1) `services/broker.py`
- Router magistrali: **XSUB tcp://*:5555** ⇄ **XPUB tcp://*:5556**.
- Log startu: `INFO Broker XSUB tcp://*:5555  <->  XPUB tcp://*:5556`.

### 2) `services/status_api.py`
- HTTP API (Flask):
  - `GET /healthz` — przegląd stanu (bus, urządzenia, tryb).
  - `POST /api/move` — `{vx, vy, yaw, duration}` (zakres −1..1, clamp do 0..1 magnitudy),
  - `POST /api/stop` — natychmiastowy stop,
  - `GET /events` — **SSE** (log zdarzeń busa + telemetria mostka),
  - (kompat) `POST /control` — surowy PUB `{topic, ...}` na magistralę.
- Publikuje / nasłuchuje: `cmd.*`, `motion.*`.

### 3) `services/motion_bridge.py`
- SUB: `cmd.move`, `cmd.stop`; wykonuje ruchy HW:
  - **forward/backward** skalar `SPEED_LINEAR`,
  - **turn_left/right** skalar `SPEED_TURN` (gdy `|yaw|>0` i `vx≈0`),
  - **DRY_RUN=1** — tylko loguje.
- Bezpieczniki:
  - `SAFE_MAX_DURATION` — twardy limit czasu impulsu (s),
  - `MIN_CMD_GAP` — min. przerwa między komendami,
  - **deadman/auto_stop** — po upływie czasu ruchu wymuszony `stop()`.
- PUB: `motion.bridge.event` (np. `ready`, `rx_cmd.move`, `auto_stop`, `stop`).
- Uwaga Py 3.9: adnotacje typu `Timer | None` → użyj `Optional[Timer]`.

---

## Tematy busa (ZMQ)
- `cmd.move` — `{vx, vy, yaw, duration, ts}`
- `cmd.stop` — `{ts}` (natychmiast)
- `motion.bridge.event` — `{event, detail, ts}`
- `motion.state` — stan regulatora/sterownika (opcjonalnie)
- `vision.dispatcher.heartbeat` — heartbeat modułu wizji
- (opcjonalnie) `chat.request/response/error` — kanał konwersacyjny

**Podsłuch (bus_spy):**
```py
# tools/sub.py
s.setsockopt_string(zmq.SUBSCRIBE, "cmd.")
s.setsockopt_string(zmq.SUBSCRIBE, "motion.")
s.setsockopt_string(zmq.SUBSCRIBE, "vision.")
```

---

## REST API (skrót)
### `GET /healthz`
Zwraca status (ok/degraded), uptime, heartbeat busa, urządzenia (`xgo`, `lcd`, `camera`), obecność, itp.

### `POST /api/move`
Body JSON:
```json
{"vx":0.6, "vy":0.0, "yaw":0.0, "duration":0.6}
```
Zasady: wartości normalizowane do magnitudy ≤ 1; rzeczywisty czas ogranicza `SAFE_MAX_DURATION` po stronie mostka.

### `POST /api/stop`
Natychmiastowe zatrzymanie.

### `GET /events` (SSE)
Strumień `data: {"ts":..., "topic":"...", "data":"..."}` — log busa i mostka.

### (Kompat) `POST /control`
Publikacja raw na bus: `{topic:"motion.cmd", ...}` → używaj głównie do debug.

---

## Web UI (sterowanie)
- Strona: **„Rider‑Pi — Sterowanie ruchem (REST /api)”**.
- Kontrolki: tryb `turn`/`strafe`, prędkość 0..1, czas (s), STOP; skróty W/A/S/D, strzałki, spacja (STOP).
- `/healthz` odświeżane 1 Hz; log zdarzeń z **SSE**; styl jak dashboard.

---

## Instalacja i uruchomienie (systemd)
### Pliki unitów
- `rider-broker.service`
- `rider-status-api.service`
- `rider-motion-bridge.service`

**Wspólne ustawienia:**
```
User=pi
WorkingDirectory=/home/pi/robot
EnvironmentFile=/etc/default/rider-pi
ExecStart=/usr/bin/python3 services/<...>.py
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1
```

### Konfiguracja (`/etc/default/rider-pi`)
```bash
BUS_PUB_PORT=5555
BUS_SUB_PORT=5556
STATUS_API_PORT=8080
DRY_RUN=0             # 1 = tylko logi
SPEED_LINEAR=12       # skalar liniowy
SPEED_TURN=20         # skalar skrętu
SAFE_MAX_DURATION=0.25
MIN_CMD_GAP=0.1
```

### Pierwszy start / restart
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rider-broker.service rider-status-api.service rider-motion-bridge.service
# aktualizacja / restart
sudo systemctl restart rider-broker.service rider-status-api.service rider-motion-bridge.service
```

### Logi (opcjonalne do pliku)
```bash
# mostek → plik
sudo sed -i '/^\[Service\]/a StandardOutput=append:/var/log/rider-motion-bridge.log\nStandardError=append:/var/log/rider-motion-bridge.log' \
  /etc/systemd/system/rider-motion-bridge.service
sudo systemctl daemon-reload && sudo systemctl restart rider-motion-bridge.service

# podgląd
sudo tail -f /var/log/rider-motion-bridge.log
```

---

## Makefile – skrót użycia
Najważniejsze cele (w repo):
```
make install     # kopiuje unity + tworzy /etc/default/rider-pi (jeśli brak)
make enable      # enable --now dla broker/api/bridge
make up          # restart całego stosu
make status      # skrócony status
make logs-...    # podgląd logów
make diag        # szybka diagnostyka usług/portów/API
make spy         # podsłuch szyny
```

---

## Testy i diagnostyka
### Szybki test end‑to‑end
```bash
curl -s http://localhost:8080/healthz | jq .
curl -s -X POST http://localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0.7,"vy":0,"yaw":0,"duration":0.2}'
sleep 1
curl -s -X POST http://localhost:8080/api/stop -H 'Content-Type: application/json' -d '{}'
```

### Bus spy
```bash
python3 tools/sub.py motion
```

### Typowe pułapki
- **Port zajęty** (`Address already in use`):
  ```bash
  sudo fuser -k 5555/tcp 5556/tcp
  ```
- **Start repeated too quickly**: sprawdź `journalctl -u ...` — zwykle błąd w unicie / brak env.
- **Py 3.9 adnotacje**: `Timer | None` → `Optional[Timer]`.
- **Brak skrętu**: zwiększ `SPEED_TURN`, testuj `yaw` bez `vx`, upewnij się, że podwozie jest „upright”.

---

## Tryb bezpieczeństwa / dobre praktyki
- Pierwsze testy na **DRY_RUN=1**.
- Zaczynaj od krótkich impulsów (≤ `SAFE_MAX_DURATION`).
- Zawsze miej pod ręką `POST /api/stop` (spacja w UI).
- Gating na pozie/IMU: gdy `pose≠upright`, mostek może odrzucać ruch.

---

## Roadmap (skrót)
- Kalibracja `SPEED_*` per‑urządzenie.
- Priorytety/kolejka komend.
- Wejście sprzętowe **E‑STOP** + status w `/healthz`.
- Historia zdarzeń (plik/SQLite) + proste raporty.
- CI smoke tests.

---

## Ostatnie zmiany (sesja)
- Dodane: `SAFE_MAX_DURATION`, `MIN_CMD_GAP`, **auto_stop** w `motion_bridge.py`.
- Poprawki zgodności z Py 3.9 (adnotacje typów).
- Szersze logowanie: `motion.bridge.event` + opcjonalny log do pliku.
- Web UI: styl zgodny z dashboardem, SSE `/events`, skróty klawiaturowe.
- Unity systemd z `EnvironmentFile=/etc/default/rider-pi`, spójne ścieżki (`scripts/`).
- (Kompat) `/control` w API — surowy PUB na busie dla debug/testów.

---

## Koncepcja 2 — Asystent AI (Chat/Voice)
**Cel**: naturalny interfejs (tekst/głos) → bezpieczne `cmd.move`/`cmd.stop` z pełnymi bezpiecznikami.

### Architektura
- **`ai_agent`** — proces pośredni między LLM a bus:
  - SUB: `chat.request`, `vision.*`, `motion.state`
  - PUB: `chat.response`, `chat.error`, **`cmd.move`**, **`cmd.stop`**
  - REST: `POST /api/chat` (opcjonalnie) + SSE `/events` (tematy `chat.*`).
- **Web (dashboard)** — karta „Chat”: input + szybkie komendy, log SSE.
- **Guardrail**: parser/validator poleceń (limity prędkości/czasu, whitelista czasowników). W niepewności → pytanie zamiast ruchu.

### Konfiguracja (`/etc/default/rider-pi` — fragment)
```ini
# AI
AI_ENABLE=1
AI_MODEL=gpt-4o-mini
AI_MAX_TOKENS=300
AI_TEMP=0.2
AI_OFFLINE_FALLBACK=1
AI_ALLOW_CMDS=move,turn,stop
AI_MAX_DURATION=0.25
AI_MIN_CMD_GAP=0.10
OPENAI_API_KEY=__SET_IN_ENV__
```

### Interfejsy
- REST: `POST /api/chat` → `{ ok, reply, actions[] }`
- ZMQ: `chat.request/response/error` + `cmd.move/stop`

### Walidacja i mapowanie
1) Reguły PL/EN (np. „jedź X cm”, „skręć w prawo”).  
2) Gdy niepewne i `AI_ENABLE=1` → LLM prosi o JSON `{vx,vy,yaw,duration}`.  
3) Guardrail: clamp |v|≤1, `duration ≤ min(AI_MAX_DURATION, SAFE_MAX_DURATION)`, `gap ≥ AI_MIN_CMD_GAP`.  
4) Wyślij `cmd.move`/`cmd.stop` lub poproś o doprecyzowanie.

### Szkic `services/ai_agent.py` (esencja)
```python
#!/usr/bin/env python3
import os, json, time, zmq
from threading import Lock
BUS_PUB_PORT=int(os.getenv('BUS_PUB_PORT','5555'))
BUS_SUB_PORT=int(os.getenv('BUS_SUB_PORT','5556'))
AI_ENABLE=os.getenv('AI_ENABLE','0')=='1'
AI_MIN_CMD_GAP=float(os.getenv('AI_MIN_CMD_GAP','0.10'))
AI_MAX_DURATION=float(os.getenv('AI_MAX_DURATION','0.25'))
ctx=zmq.Context.instance()
pub=ctx.socket(zmq.PUB); pub.connect(f"tcp://127.0.0.1:{BUS_PUB_PORT}")
sub=ctx.socket(zmq.SUB); sub.connect(f"tcp://127.0.0.1:{BUS_SUB_PORT}")
for t in ("chat.request",): sub.setsockopt_string(zmq.SUBSCRIBE, t)
last_ts=0.0; lk=Lock()

def publish(topic, obj):
    pub.send_string(topic); pub.send_json({"ts": time.time(), **obj}, flags=zmq.SNDMORE)

print("[ai] START", flush=True)
while True:
    topic = sub.recv_string(); payload = json.loads(sub.recv_string())
    txt = (payload.get('text','') or '').strip()
    if not txt: continue
    with lk:
        now=time.time()
        if now-last_ts < AI_MIN_CMD_GAP: publish('chat.error', {"text":"Too soon; ignored"}); continue
        last_ts=now
    publish('chat.response', {"text": f"(demo) Zrozumiałem: '{txt}'."})
```

### Usługa `robot-chat.service` (systemd)
```ini
[Unit]
Description=Rider-Pi AI Agent (Chat)
After=network-online.target rider-broker.service
Requires=rider-broker.service
[Service]
User=pi
WorkingDirectory=/home/pi/robot
EnvironmentFile=/etc/default/rider-pi
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 -u /home/pi/robot/services/ai_agent.py
Restart=always
RestartSec=1
StandardOutput=append:/var/log/rider-ai-agent.log
StandardError=append:/var/log/rider-ai-agent.log
[Install]
WantedBy=multi-user.target
```

### Bezpieczeństwo (checklist)
- `duration` > limit → **odrzuć** (komunikat do UI).
- Sekwencje < `AI_MIN_CMD_GAP` → **ignoruj**.
- Poza/napęd w złym stanie → **tylko STOP** + komunikat.
- DRY_RUN → odpowiedzi oznaczaj `[DRY_RUN]`.

---

## Usługi systemd (pełna lista)
1) **`rider-broker.service`** — ZMQ XSUB/XPUB (porty 5555/5556).  
2) **`rider-status-api.service`** — REST/SSE + panel WWW (8080).  
3) **`rider-motion-bridge.service`** — napęd (cmd.move/stop → HW).  
4) *(opc.)* **`robot-voice.service`** — wejście/wyjście głosowe.  
5) *(opc.)* **`robot-chat.service`** — agent konwersacyjny.

**Kolejność startu:** broker → (API, bridge) → (voice/chat).  
**Diagnoza:** `systemctl status ...`, `journalctl -u ... -n 50 --no-pager`.

---

## Procedury operacyjne (skrót)
- **Pełny restart stosu:**
```bash
sudo systemctl restart rider-broker.service \
  rider-status-api.service \
  rider-motion-bridge.service
```
- **Szybki test z linii poleceń:**
```bash
curl -s -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0.2,"vy":0,"yaw":0,"duration":0.15}'
# STOP
curl -s -X POST localhost:8080/api/stop -H 'Content-Type: application/json' -d '{}'
```
- **Podsłuch szyny:**
```bash
python3 tools/sub.py motion
```

---

## Najczęstsze problemy i wskazówki
- **„Address already in use” (broker):** ubij ręczne procesy i `fuser -k 5555/tcp 5556/tcp`.
- **Brak auto‑stopu:** upewnij się, że `SAFE_MAX_DURATION` > 0; sprawdź log `auto_stop`.
- **Skręt słaby:** na czas kalibracji zwiększ `SPEED_TURN` (np. do 40), testuj krótkie impulsy `yaw` 0.25–0.6; wróć do bezpiecznej wartości po próbach.
- **Rozjazd baterii:** ufaj telemetrii z API (UART), nie wskazaniu LCD.
- **RPi Python 3.9:** unikaj `Timer | None`; używaj `Optional[Timer]`.

---

## Roadmap (fragment)
- Asystent głosowo‑konwersacyjny (wake‑word/PTT, reguły bezpieczeństwa, potwierdzenia ruchu).
- Vision: proces `vision.*` + integracja z `models/`, presence/pose gating.
- Web‑panel: presety ruchu, raporty telemetrii.
- CI: lint + smoke tests.

