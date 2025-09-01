# Rider‑Pi — projekt (wersja FINAL)

## TL;DR
Rider‑Pi to lekki, samodzielny stos do sterowania robotem (XGO/ESP/itp.) na Raspberry Pi. Składa się z magistrali komunikatów **ZeroMQ (XSUB↔XPUB)**, usług **Status API (Flask/REST+SSE)** oraz **Motion Bridge** (most sprzętowy do napędu). Działa jako zestaw usług **systemd**, ma prosty front WWW oraz komplet narzędzi testowych i bezpieczeństw (watchdog, „deadman”/auto‑stop, limity impulsów i odstępów).

---

## Najważniejsze cechy
- **Komunikacja asynchroniczna**: Bus ZMQ z tematami `cmd.*`, `motion.*`, `vision.*`, itp.
- **REST API**: `/api/move`, `/api/stop`, `/healthz` + **SSE** `/events` dla logów i zdarzeń.
- **Most ruchu (Motion Bridge)**: mapuje polecenia z bus/REST na wywołania sprzętowe (np. XGO), z obsługą **DRY_RUN**.
- **Bezpieczeństwo**:
  - twardy limit czasu impulsu: `SAFE_MAX_DURATION` (domyślnie 0.25 s),
  - ogranicznik częstości poleceń: `MIN_CMD_GAP` (domyślnie 0.1 s),
  - automatyczny **deadman/auto_stop**,
  - `SPEED_LINEAR` i `SPEED_TURN` jako skalary prędkości.
- **Usługi systemd** + logi w `/var/log/rider-*.log`.
- **Panel WWW** do sterowania ruchem, dopasowany stylistycznie do głównego dashboardu.
- **Skrypty diagnostyczne i testowe** (w tym „bus spy”).

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
|  curl / bus_spy / vision            |   |  tcp://*:5555 / 5556     |
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

## Komponenty
### 1) `scripts/broker.py`
- Router magistrali: **XSUB tcp://*:5555** ⇄ **XPUB tcp://*:5556**.
- Log: `INFO Broker XSUB tcp://*:5555  <->  XPUB tcp://*:5556`.

### 2) `scripts/status_api.py`
- HTTP API (Flask):
  - `GET /healthz` — stan systemu (bus, urządzenia, tryb).
  - `POST /api/move` — body: `{vx, vy, yaw, duration}` (0..1),
  - `POST /api/stop` — awaryjny stop,
  - `GET /events` — **SSE** (strumień zdarzeń z busa + logi mostka).
- Publikuje / nasłuchuje na busie tematy `cmd.*`, `motion.*`.
- Front WWW: przyciski W/A/S/D/strzałki, suwak prędkości i czasu, log zdarzeń (SSE), dopasowany do głównego dashboardu.

### 3) `scripts/motion_bridge.py`
- Subskrybuje `cmd.move` i `cmd.stop`, wykonuje ruch:
  - **forward/backward** z `SPEED_LINEAR`,
  - **turn_left/right** z `SPEED_TURN` (gdy `|yaw|>0` i `vx=0`),
  - w trybie **DRY_RUN=1** tylko loguje bez wywołań HW.
- Zabezpieczenia:
  - `SAFE_MAX_DURATION` — twardy limit pojedynczego impulsu (sek.),
  - `MIN_CMD_GAP` — minimalna przerwa między komendami,
  - **auto_stop** (deadman) — po upłynięciu czasu ruchu.
- Publikuje telemetrię na busie jako `motion.bridge.event` (np. `ready`, `rx_cmd.move`, `auto_stop`, `stop`, `turn_right`, itp.).
- Log startu (przykład):
  ```
  [bridge] START (PUB:5555 SUB:5556 DRY_RUN=False SAFE_MAX_DURATION=0.25 MIN_CMD_GAP=0.1)
  [bridge] ready: {"ts": ...}
  ```

> **Uwaga dot. Pythona 3.9**: adnotacje typu `Timer | None` wymagają 3.10 lub `from __future__ import annotations`; na 3.9 używamy `Optional[Timer]`.

---

## Tematy busa (ZMQ)
- `cmd.move` — żądania ruchu `{vx, vy, yaw, duration, ts}`
- `cmd.stop` — natychmiastowy stop `{ts}`
- `motion.bridge.event` — zdarzenia mostka `{event, detail, ts}`
- `motion.state` — stan regulatora/sterownika (jeśli dostępny)
- `vision.dispatcher.heartbeat` — heartbeat modułu wizyjnego

Przykładowy podsłuch (bus spy):
```py
# scripts/bus_spy.py
s.setsockopt_string(zmq.SUBSCRIBE, "cmd.")
s.setsockopt_string(zmq.SUBSCRIBE, "motion.")
s.setsockopt_string(zmq.SUBSCRIBE, "vision.")
```

---

## REST API (skrót)
### `GET /healthz`
Zwraca status (ok/degraded), uptime, bus heartbeat, urządzenia (`xgo`, `lcd`, `camera`), stan obecności, itp.

### `POST /api/move`
Body JSON:
```json
{"vx":0.6, "vy":0.0, "yaw":0.0, "duration":0.6}
```
Zasady: wartości w zakresie 0..1 (znak kierunku), realny czas ogranicza `SAFE_MAX_DURATION`.

### `POST /api/stop`
Natychmiastowe zatrzymanie.

### `GET /events` (SSE)
Strumień linii `data: {"ts":..., "topic":"...", "data":"..."}` — log zdarzeń busa i mostka.

---

## Web UI (sterowanie)
- Strona: **„Rider‑Pi — Sterowanie ruchem (REST /api)”**.
- Kontrolki: tryb `turn`/`strafe`, prędkość 0..1, czas (s), STOP, skróty klawiatury (W/A/S/D, strzałki, spacja).
- Status `/healthz` aktualizowany co sekundę; log zdarzeń z **SSE**.
- Styl dopasowany do głównego dashboardu (karty, grid, monospaced log, kbd, itp.).

---

## Instalacja i uruchomienie (systemd)
### Pliki unitów
- `rider-broker.service`
- `rider-status-api.service`
- `rider-motion-bridge.service`

Wspólne:
```
User=pi
WorkingDirectory=/home/pi/robot
EnvironmentFile=/etc/default/rider-pi
ExecStart=/usr/bin/python3 scripts/<...>.py
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1
```

### Konfiguracja (`/etc/default/rider-pi`)
```bash
BUS_PUB_PORT=5555
BUS_SUB_PORT=5556
STATUS_API_PORT=8080
DRY_RUN=0            # 1 = tylko logi
SPEED_LINEAR=12      # skalar liniowy
SPEED_TURN=20        # skalar skrętu
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

### Logi
```bash
# mostek do pliku
sudo sed -i '/^\[Service\]/a StandardOutput=append:/var/log/rider-motion-bridge.log\nStandardError=append:/var/log/rider-motion-bridge.log' \
  /etc/systemd/system/rider-motion-bridge.service
sudo systemctl daemon-reload && sudo systemctl restart rider-motion-bridge.service

# podgląd
sudo tail -f /var/log/rider-motion-bridge.log
```

---

## Testy i diagnostyka
### Szybki test end‑to‑end
```bash
curl -s http://localhost:8080/healthz | jq .
curl -s -X POST http://localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0.7,"vy":0,"yaw":0,"duration":0.8}'
sleep 1
curl -s -X POST http://localhost:8080/api/stop -H 'Content-Type: application/json' -d '{}'
```

### Bus spy
```bash
python3 scripts/bus_spy.py
```

### Typowe pułapki
- **Port zajęty** (`Address already in use`):
  ```bash
  sudo fuser -k 5555/tcp 5556/tcp
  ```
- **Błąd adnotacji typów na Py 3.9**: zamień `Timer | None` na `Optional[Timer]`.
- **Start repeated too quickly**: sprawdź `journalctl -u ...` – zwykle błąd składni / brak env.
- **Brak skrętu**: zwiększ `SPEED_TURN`, użyj czystego `yaw` (bez `vx`), upewnij się, że podwozie w pozycji „upright”.

---

## Tryb bezpieczeństwa / dobre praktyki
- Zaczynaj testy od **DRY_RUN=1**.
- Najpierw krótkie impulsy (≤ `SAFE_MAX_DURATION`).
- Zawsze miej pod ręką `POST /api/stop` (spacja w UI).
- Pilnuj stanu z IMU/podwozia — gdy `pose != upright`, mostek może odrzucać ruch.

---

## Roadmap (skrót)
- Kalibracja `SPEED_*` per‑urządzenie.
- Priorytety komend i kolejka (odrzucanie w locie).
- Wejście sprzętowe **E‑STOP** + status w `/healthz`.
- Zapis historii zdarzeń do pliku/SQLite.
- Autotesty CI na repo (lint + smoke tests).

---

## Ostatnie zmiany (sesja)
- Dodane: `SAFE_MAX_DURATION`, `MIN_CMD_GAP`, **auto_stop** (deadman) w `motion_bridge.py`.
- Poprawki kompatybilności Py 3.9 (adnotacje typów).
- Rozszerzone logowanie: `motion.bridge.event`, wyjście do `/var/log/rider-motion-bridge.log`.
- Web UI: styl spójny z dashboardem, SSE `/events`, skróty klawiaturowe.
- Jednostki systemd z `EnvironmentFile=/etc/default/rider-pi` i ujednolicone ścieżki.



## Koncepcja 2 — Asystent AI (ChatGPT)

### Cel
Naturalny interfejs sterowania Rider‑Pi przez język (tekst/głos). Użytkownik mówi lub pisze: „Jedź 20 cm do przodu i skręć lekko w prawo”, a moduł AI tłumaczy to na bezpieczne komendy ruchu (`cmd.move` / `cmd.stop`) z pełnymi bezpiecznikami.

### Architektura (z lotu ptaka)
- **`ai_agent`** — proces pośredni (Python) między LLM a magistralą:
  - SUB: `chat.request`, `vision.*`, `motion.state`  
  - PUB: `chat.response`, `chat.error`, **`cmd.move`**, **`cmd.stop`**, `motion.bridge.event` (echo do UI)
  - (opcjonalnie) REST: `POST /api/chat` + SSE: `/events` (tematy `chat.*`).
- **Dashboard / Web** — karta „Chat”: pole tekstowe + przyciski szybkich poleceń, strumień odpowiedzi (SSE), log poleceń, podgląd bezpieczeństwa.
- **Guardrail** (bezpiecznik): parser i walidator komend (limit prędkości, czasu, przerwy między komendami, whitelista czasowników). W razie niepewności — pytanie doprecyzowujące zamiast ruchu.

### Konfiguracja ( `/etc/default/rider-pi` )
```ini
# AI
AI_ENABLE=1
AI_MODEL=gpt-4o-mini
AI_MAX_TOKENS=300
AI_TEMP=0.2
# Offline fallback (regex → komendy gdy brak klucza lub sieci)
AI_OFFLINE_FALLBACK=1
# Ochrona
AI_ALLOW_CMDS=move,turn,stop
AI_MAX_DURATION=0.25        # twardy limit jak w SAFE_MAX_DURATION
AI_MIN_CMD_GAP=0.10         # zgodnie z MIN_CMD_GAP mostka
# Sekrety przez env/Secret Manager (NIE w repo!)
OPENAI_API_KEY=__SET_IN_ENV__
```

### Interfejsy
#### REST
- `POST /api/chat` → `{ "message": "...", "session_id": "opt" }`  → `{ ok, reply, actions[] }`
- Strumień: `/events` (SSE): wiadomości `chat.response`, `chat.error`, echo wykonanych akcji.

#### Magistrala (ZMQ)
- **Wejście**: `chat.request { text, ts }`
- **Wyjście**: `chat.response { text, ts }`, `chat.error { text, reason }`
- **Akcje**: `cmd.move { vx, vy, yaw, duration, ts }`, `cmd.stop { ts }`

### Walidacja i mapowanie poleceń
1. **Parsowanie** (propozycja):
   - Najpierw lekki parser regułowy (PL/EN) dla haseł „jedź / zatrzymaj / skręć / w prawo / 20 cm / pół sekundy…”.  
   - Jeśli parser niepewny → zapytaj LLM o strukturę JSON (`vx, vy, yaw, duration`).
2. **Guardrail**:
   - `|vx|, |vy|, |yaw| ∈ [0..1]`  → przeskaluj mostkiem do `SPEED_LINEAR`, `SPEED_TURN`.
   - `duration ≤ min(AI_MAX_DURATION, SAFE_MAX_DURATION)`.
   - odstęp ≥ `AI_MIN_CMD_GAP`.
   - whitelista: tylko `move/turn/stop`.
   - w niepewności → **bez ruchu**, odpowiedź z prośbą o doprecyzowanie.

### Przykłady (curl)
```bash
# Tekst → odpowiedź + ewentualne działania
curl -s -X POST localhost:8080/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Jedź 15 cm do przodu i lekko w prawo"}' | jq .

# PubSub (debug): zobacz `chat.*` na /events lub bus_spy
```

### Szkic modułu `scripts/ai_agent.py`
> Minimalny „szkielet” produkcyjny (stream, retry, logi, SSE) jest dłuższy — tu esencja:
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
    pub.send_string(topic)
    pub.send_json({"ts": time.time(), **obj}, flags=zmq.SNDMORE)

print("[ai] START", flush=True)
while True:
    try:
        topic = sub.recv_string()
        payload = json.loads(sub.recv_string())
        txt = payload.get('text','').strip()
        if not txt: continue
        with lk:
            now=time.time()
            if now-last_ts < AI_MIN_CMD_GAP:
                publish('chat.error', {"text":"Too soon; ignored"}); continue
            last_ts=now
        # 1) spróbuj prostych reguł (np. "jedź X cm", "skręć w prawo")
        # 2) jeśli niepewne i AI_ENABLE → zapytaj LLM o JSON {vx,vy,yaw,duration}
        # 3) waliduj: clamp + duration ≤ AI_MAX_DURATION
        # 4) wyślij cmd.move / cmd.stop albo pytanie doprecyzowujące
        publish('chat.response', {"text": f"(demo) Zrozumiałem: '{txt}'."})
    except KeyboardInterrupt:
        break
```

### Unit systemd (propozycja)
```ini
# /etc/systemd/system/rider-ai-agent.service
[Unit]
Description=Rider-Pi AI Agent (Chat)
After=network-online.target rider-broker.service
Requires=rider-broker.service

[Service]
User=pi
EnvironmentFile=/etc/default/rider-pi
WorkingDirectory=/home/pi/robot
ExecStart=/usr/bin/python3 scripts/ai_agent.py
Restart=always
RestartSec=1
Environment=PYTHONUNBUFFERED=1
StandardOutput=append:/var/log/rider-ai-agent.log
StandardError=append:/var/log/rider-ai-agent.log

[Install]
WantedBy=multi-user.target
```

### Testy bezpieczeństwa (quick checklist)
- Impulsy `duration` > limit → **odrzuć** + komunikat.
- Sekwencje < `AI_MIN_CMD_GAP` → **zignoruj** (anty-spam).
- Napędy wyłączone / pochylenie ≠ `upright` → **tylko stop** + komunikat.
- Dry‑run → zawsze dodaj `[DRY_RUN]` w odpowiedziach.

### Dalsze kroki
- Integracja mikrofonu (`arecord`) + **STT** (Whisper/Vosk) + **TTS** (pyttsx3/edge‑tts).
- Prompt systemowy z wiedzą o parametrach robota (skale prędkości, limity itp.).
- Krótka pamięć sesji (ostatnie N intencji) z TTL.
- UI: karta „Chat” w dashboardzie + skróty (np. „pokaż status baterii”).


## Moduł Chat/Voice (koncepcja 2)

Drugi filar projektu to interakcja głosowa i czat z LLM, uruchamiane jako osobne usługi systemd:

- **`robot-voice.service`** – wejście z mikrofonu (ASR) i wyjście na głośnik (TTS). Ma służyć do prostych komend („start”, „stop”, „w prawo 15 cm”) i krótkiej nawigacji bez patrzenia w ekran.
- **`robot-chat.service`** – sesja dialogowa z modelem (ChatGPT/Realtime). Może przyjmować polecenia wysokiego poziomu („podjedź pod łóżko i skręć w lewo”), które będą mapowane na prymitywy ruchu przez warstwę logiki.

> Obie usługi są niezależne od **`status_api`** i **`motion_bridge`**, ale korzystają z tej samej szyny ZMQ oraz wspólnego pliku konfiguracyjnego **`/etc/default/rider-pi`**.

### Minimalny przepływ
1. **Wejście audio** → rozpoznawanie mowy (ASR).
2. **NLP/LLM** – klasyfikacja intencji lub pełny dialog (opcjonalnie z pamięcią sesji).
3. **Generacja poleceń ruchu** – publikacja na busie (docelowo: komendy o tym samym formacie co REST `/api/move`), albo wywołanie REST API.
4. **Wyjście audio** (TTS) – potwierdzenia i komunikaty o błędach („OK, 15 cm do przodu”).

### Tryby aktywacji (zalecenia)
- **PTT (push‑to‑talk)** – bezpieczny domyślny tryb do testów w domu.
- **Wake‑word** – dopiero gdy mikrofon i detekcja słowa kluczowego są stabilne; dodaj timeout bezczynności.
- **Tryb pół‑offline** – gdy internet niestabilny, TTS/ASR lokalne + proste reguły (fall‑back na komendy skrótowe: *stop*, *do przodu*, *skręt w prawo*).

### Bezpieczeństwo
- „**Deadman**” (watchdog) po stronie ruchu już działa – komendy z głosu muszą **respektować** `SAFE_MAX_DURATION` i publikować **awaryjny STOP** przy utracie sesji audio.
- Wymuś filtrację parametrów (`|vx|,|vy|,|yaw| ≤ 1.0`) i klamp czasu trwania ≤ `SAFE_MAX_DURATION`.
- E‑stop z panelu/klawiatury zawsze wygrywa: komendy z czatu/głosu muszą się podporządkować (`/api/stop`).

### Modele i zasoby (`models/`)
Katalog **`models/`** przechowuje pliki modeli/etykiet dla wizji (np. ONNX, `.names`). Ustalony konwencjonalny układ:
- `models/<nazwa-modelu>/model.onnx`
- `models/<nazwa-modelu>/labels.names`
- `models/README.md` – krótki opis, źródła i licencja.

> Docelowo warstwa „vision” będzie publikować obecność/przeszkody na busie; panel i mostek mogą je konsumować.

---

## Usługi systemd — chat/voice

Szablony jednostek znajdują się w repozytorium w `systemd/` jako **`robot-chat.service`** i **`robot-voice.service`**. Integrują się podobnie jak pozostałe usługi (broker/API/bridge).

### Włączenie / wyłączenie
```bash
sudo cp systemd/robot-*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now robot-voice.service robot-chat.service
# zatrzymanie/wyłączenie
# sudo systemctl disable --now robot-voice.service robot-chat.service
```

### Logi i diagnostyka
```bash
journalctl -u robot-voice.service -f --no-pager
journalctl -u robot-chat.service  -f --no-pager
```

### Konfiguracja (przez `/etc/default/rider-pi`)
Zachowujemy **jeden** plik środowiskowy dla całego systemu. Przykładowe wpisy (dopasuj do faktycznych opcji w serwisach):
```bash
# Dostęp do LLM/TTS
OPENAI_API_KEY=...
CHAT_MODEL=gpt-4o-mini           # lub inny model czatu
VOICE_TTS_MODEL=tts-1            # model syntezy
VOICE_LANG=pl-PL                 # język rozpoznawania/generacji

# Audio
VOICE_INPUT_DEVICE=default       # lub hw:1,0 – mikrofon
VOICE_OUTPUT_DEVICE=default      # głośnik
WAKE_WORD= "hej rider"           # jeśli używamy trybu wake‑word

# Zachowanie
PTT_ONLY=1                       # domyślnie PTT w testach
MAX_UTTERANCE_S=8                # limit długości wypowiedzi
```
> Rzeczywiste nazwy zmiennych i `ExecStart` sprawdź bezpośrednio w plikach `robot-voice.service` i `robot-chat.service` (w repo `systemd/`).

### Interakcja z ruchem
- „Czat” może wołać REST `/api/move` + `/api/stop` **albo** publikować na busie komunikaty zgodne z wzorcem `cmd.move`.
- W obu przypadkach obowiązują limity z mostka (`SAFE_MAX_DURATION`, `MIN_CMD_GAP`), więc ścieżka głosowa jest naturalnie ograniczona.

### TODO (Chat/Voice)
- [ ] Stabilny wybór urządzeń audio (UID karty/USB, a nie tylko index ALSA)
- [ ] PTT vs wake‑word (lokalne VAD + debounce)
- [ ] Prosty „intent parser” → mapowanie na prymitywy ruchu
- [ ] Odsłuch komunikatów (TTS) z priorytetem nad innymi dźwiękami
- [ ] Testy regresyjne bez mikrofonu (pliki WAV jako wejście)

---



## Usługi systemd (pełna lista)
Ta sekcja zbiera w jednym miejscu wszystkie serwisy z katalogu `systemd/` w repo oraz te, które już uruchamiamy na RPi. Daje to szybki obraz co **startuje przy boot** i jaką pełnią rolę.

> Uwaga: nazwy i ścieżki w `ExecStart`, `WorkingDirectory` itp. powinny odpowiadać Twojej instalacji w `/home/pi/robot`. Jeśli masz inny użytkownik/katalog – dopasuj odpowiednio.

### 1) `rider-broker.service` – szyna komunikatów (ZMQ XSUB/XPUB)
- **Rola:** pośrednik PUB/SUB (ZeroMQ) spajający procesy.  
- **Porty:** `BUS_PUB_PORT=5555` (XSUB) i `BUS_SUB_PORT=5556` (XPUB).  
- **Zależności:** startuje **przed** innymi usługami, które wysyłają/odbierają komunikaty.  
- **Szybkie komendy:**
  ```bash
  sudo systemctl status rider-broker.service
  sudo journalctl -u rider-broker.service -n 50 --no-pager
  ```

### 2) `rider-status-api.service` – REST API + panel WWW
- **Rola:** Flask API (port `8080`) + serwowanie panelu sterowania (REST `/api/*`, SSE `/events`, health `/healthz`).  
- **Subskrybuje:** szynę (np. telemetria, heartbeat), wystawia `/api/move`, `/api/stop`.  
- **Zmienne:** korzysta z `BUS_SUB_PORT`, `BUS_PUB_PORT`.  
- **Szybkie komendy:**
  ```bash
  sudo systemctl status rider-status-api.service
  curl -s http://localhost:8080/healthz | jq .
  ```

### 3) `rider-motion-bridge.service` – most do napędu XGO
- **Rola:** odbiera `cmd.move` / `cmd.stop` ze szyny i woła funkcje sterownika XGO (`forward`, `backward`, `turn_left`, `turn_right`, ewentualnie `strafe`).  
- **Bezpieczeństwo (ważne):**
  - `SAFE_MAX_DURATION` – **twardy limit** czasu pojedynczego impulsu (s).  
  - `MIN_CMD_GAP` – minimalny odstęp między komendami (anty-spam), domyślnie `0.1s`.  
  - **Deadman/auto‑stop** – po upływie czasu ruchu publikowany jest `auto_stop`, a most wzywa `stop()` bez udziału użytkownika.  
  - `DRY_RUN` – tryb bez wywołań HW (loguje zamiast ruszać robotem).  
- **Skalowanie prędkości:**
  - `SPEED_LINEAR` – skala przód/tył (np. 12 => `vx=1.0` → ~12 jednostek sterownika).  
  - `SPEED_TURN` – skala obrotu (np. 20; tymczasowo można zwiększyć – np. 40 – gdy skręt jest mało widoczny).  
- **Typowe zmienne w `/etc/default/rider-pi`:**
  ```env
  BUS_PUB_PORT=5555
  BUS_SUB_PORT=5556
  STATUS_API_PORT=8080
  DRY_RUN=0
  SPEED_LINEAR=12
  SPEED_TURN=20
  SAFE_MAX_DURATION=0.25
  MIN_CMD_GAP=0.1
  ```
- **Podgląd logów (opcjonalne przekierowanie do pliku):**
  W unicie można dodać:
  ```ini
  StandardOutput=append:/var/log/rider-motion-bridge.log
  StandardError=append:/var/log/rider-motion-bridge.log
  ```
  i potem:
  ```bash
  sudo tail -f /var/log/rider-motion-bridge.log
  ```

### 4) `robot-voice.service` – wejście/wyjście głosowe (voice I/O)
- **Rola:** warstwa mikrofon → transkrypcja oraz TTS → głośnik; może publikować/pobierać zdarzenia z szyny (np. `voice.*`).  
- **Integracje:** lokalne ASR/TTS lub chmurowe (konfigurowalne), sterowanie bazą na komendach głosowych.  
- **Zależności sugerowane:** broker; opcjonalnie `robot-chat.service` (gdy głos ↔ czat).  
- **Diagnoza:**
  ```bash
  sudo systemctl status robot-voice.service
  sudo journalctl -u robot-voice.service -n 50 --no-pager
  ```

### 5) `robot-chat.service` – agent rozmowy (Chat + sterowanie)
- **Rola:** agent konwersacyjny (np. OpenAI) łączący się ze szyną – potrafi przyjmować polecenia w języku naturalnym i publikować kontrolowane `cmd.move` (po nałożeniu polityk bezpieczeństwa).  
- **Konfiguracja:**
  - Klucze API (np. `OPENAI_API_KEY`) trzymamy w `/etc/default/rider-pi` lub w osobnym pliku `EnvironmentFile=`.  
  - Ograniczenia bezpieczeństwa: zawsze respektuje `SAFE_MAX_DURATION` i dopuszczalne zakresy prędkości.  
- **Diagnoza:**
  ```bash
  sudo systemctl status robot-chat.service
  sudo journalctl -u robot-chat.service -n 50 --no-pager
  ```

---

## Kolejność startu i zależności
1. **`rider-broker.service`** (szyna)  
2. **`rider-status-api.service`** (API + WWW) i **`rider-motion-bridge.service`** (napęd) – oba *After=broker*  
3. **`robot-voice.service`** i **`robot-chat.service`** – opcjonalne warstwy interakcji; również *After=broker*  

> Jeżeli jakaś usługa nie wstaje po restarcie systemu, sprawdź `Requires=`/`After=` w unicie oraz konflikty portów (np. broker: 5555/5556 zajęte przez inny proces).

## Procedury operacyjne (skrót)
- **Pełny restart stosu ruchu:**
  ```bash
  sudo systemctl restart rider-broker.service \
    rider-status-api.service \
    rider-motion-bridge.service
  ```
- **Szybki test linii komend:**
  ```bash
  # ruch do przodu 150 ms (auto-stop)
  curl -s -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
    -d '{"vx":0.2,"vy":0,"yaw":0,"duration":0.15}'

  # awaryjny STOP
  curl -s -X POST localhost:8080/api/stop -H 'Content-Type: application/json' -d '{}'
  ```
- **Podsłuch szyny (debug):**
  ```bash
  python3 scripts/bus_spy.py
  # nasłuchuje m.in. cmd.*, motion.*, vision.*
  ```

  ---

## Ostatnie zmiany — obsługa skrętów (v0.4.8)

- Dodano pełną obsługę skrętów **w lewo / w prawo**:
  - `motion_bridge.py` mapuje teraz poprawnie `cmd.move {yaw}` na wywołania
    `turnleft(step)` / `turnright(step)` (zamiast wcześniejszego `translation`).
  - Zdefiniowano aliasy metod (`turnleft/turnright`, `step`) zgodne z FW producenta.

- **Nowe skrypty testowe**:
  - `scripts/manual_drive.py` — ręczne sterowanie z klawiatury (`f/b/l/r` + czas/impuls).
  - `scripts/test_motion.py` — fizyczny test wszystkich kierunków (forward/back/left/right).
  - `scripts/test_motion_bus.py` — test przez magistralę ZMQ (symulacja `/api/move`).

- **Web UI (`web/control.html`)**:
  - Przyciski **← / →** wysyłają poprawne komendy `spin` → `cmd.move {yaw}`.
  - Skróty klawiaturowe (W/A/S/D, strzałki, spacja=STOP) obsługują wszystkie kierunki.

- **Status API (`scripts/status_api.py`)**:
  - `/api/move` przyjmuje `{vx, vy, yaw, duration}` i publikuje na bus `cmd.move`.
  - `/api/stop` → `cmd.stop`.

### Jak testować
```bash
# test manualny
MOTION_ENABLE=1 python3 scripts/manual_drive.py

# test fizyczny
MOTION_ENABLE=1 python3 scripts/test_motion.py

# test przez bus
MOTION_ENABLE=1 python3 scripts/test_motion_bus.py


## Najczęstsze problemy i wskazówki
- **„Address already in use” na brokerze:** porty 5555/5556 zajęte – ubij ręczne procesy i `fuser -k 5555/tcp 5556/tcp`.  
- **Brak auto‑stopu:** upewnij się, że `SAFE_MAX_DURATION` > 0 i mostek jest zaktualizowany (log „auto_stop”).  
- **Skręt niewidoczny:** tymczasowo zwiększ `SPEED_TURN` (np. 40), testuj krótkimi impulsami `yaw` 0.25–0.6; wróć do wartości bezpiecznej po kalibracji.  
- **Rozjazd wskazań baterii:** wyświetlacz producenta ≠ telemetria z API – ufamy **dashboardowi** (FW XGO raportuje dokładniej przez UART).  
- **Błąd typu w Pythonie na RPi (annotacje typu `Timer | None`):** używaj składni kompatybilnej z Py3.9 (`Optional[Timer]` lub zwykłe przypisania bez `| None`).  

## Roadmap (fragment)
- **Asystent głosowo‑konwersacyjny**: połączenie `robot-voice` + `robot-chat` (wake‑word, reguły bezpieczeństwa, potwierdzenia ruchu).  
- **Vision**: niezależny proces `vision.*` (heartbeat już widać na szynie) – integracja z `models/` i włączenie *presence/pose gating* dla ruchu.  
- **Web‑panel**: gotowy minimalny front (styl jak „główny panel”), rozbudowa o preset-y i raporty telemetrii w czasie rzeczywistym.

