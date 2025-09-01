# Rider‑Pi — ściąga operacyjna (PL)

> Minimalna, praktyczna i *bojowa* ściąga: komendy do startu/stopu, szybkie testy, odblokowanie portów, typowe awarie i jak je naprawić. Zero gadania, same recepty.

---

## 0) Fast‑diag (gdy mało baterii)
```bash
T=2
systemctl is-active rider-broker.service rider-api.service || true
systemctl is-enabled rider-broker.service rider-api.service || true
ss -ltnp | grep -E ':5555|:5556|:8080' || echo 'no broker/api ports'

curl -fsS --max-time $T http://127.0.0.1:8080/health  \
 || curl -fsS --max-time $T http://127.0.0.1:8080/healthz || echo '{"api":"DOWN"}'

curl -fsS --max-time $T http://127.0.0.1:8080/state  || echo '{"state":"ERR"}'

# skrócony sysinfo (CPU/MEM/TEMP/BATT)
curl -fsS --max-time $T http://127.0.0.1:8080/sysinfo | \
  python3 -c 'import sys,json;d=json.load(sys.stdin);print({k:d.get(k) for k in ("cpu_pct","mem_pct","temp_c","load1","battery_pct")})'
```

---

## 1) Usługi — start/stop/restart + logi
```bash
# pełny restart stosu
sudo systemctl restart rider-broker.service rider-api.service rider-motion-bridge.service

# status skrócony
systemctl --no-pager --full status rider-broker.service | sed -n '1,20p'
systemctl --no-pager --full status rider-api.service    | sed -n '1,20p'

# bieżące logi
journalctl -u rider-broker.service -n 80 --no-pager
journalctl -u rider-api.service    -n 80 --no-pager
journalctl -u rider-motion-bridge.service -n 80 --no-pager
```

### 1a) Gdy unit się "rozsypał"
```bash
# unmask i przeładuj definicje
sudo systemctl unmask rider-broker.service || true
sudo systemctl daemon-reload

# upewnij się, że plik istnieje
sudo ls -l /etc/systemd/system/rider-broker.service || echo 'brak pliku unit'

# wgraj z repo (ścieżki dostosuj do siebie)
sudo install -m 0644 systemd/rider-broker.service /etc/systemd/system/

# włącz przy starcie i uruchom teraz
sudo systemctl enable --now rider-broker.service
```

### 1b) Porty zajęte / restart w pętli
```bash
# zabij ręcznie uruchomione brokery i odblokuj porty
sudo pkill -f '/home/pi/robot/services/broker.py' || true
sudo fuser -k 5555/tcp 5556/tcp 2>/dev/null || true

# popraw ExecStartPre w unicie (używaj prefiksu '-')
# (OSTROŻNIE: poniższy blok zastępuje sekcję Service poprawną linią ExecStartPre)
sudo awk '
  BEGIN{inSvc=0;done=0}
  /^\[Service\]/{print;inSvc=1;next}
  inSvc && /^ExecStartPre=/{next}
  inSvc && /^ExecStart=/{print "-ExecStartPre=/usr/bin/fuser -k 5555/tcp 5556/tcp";print;inSvc=0;done=1;next}
  {print}
' /etc/systemd/system/rider-broker.service | sudo tee /etc/systemd/system/rider-broker.service >/dev/null

sudo systemctl daemon-reload && sudo systemctl restart rider-broker.service
```

---

## 2) Porty i ZMQ (od ręki)
```bash
# kto trzyma porty
sudo ss -ltnp4 | grep -E ':5555|:5556' || true
sudo lsof -iTCP -sTCP:LISTEN -nP | grep -E ':5555|:5556' || true

# odblokuj (bez krzyku, idempotentnie)
sudo fuser -k 5555/tcp 5556/tcp 2>/dev/null || true
```

### 2a) Smoke‑test magistrali
```bash
# nowy terminal 1 — sub
python3 tools/sub.py motion &
# terminal 2 — pub
python3 tools/pub.py motion.state '{"ping":"ok"}'
# oczekiwany log: [SUB] motion.state: {"ping":"ok"}
```

---

## 3) REST API i sterowanie
```bash
# health
curl -fsS http://127.0.0.1:8080/health || curl -fsS http://127.0.0.1:8080/healthz

# ruch liniowy (krótki impuls) + auto-stop
curl -fsS -X POST http://127.0.0.1:8080/api/move \
  -H 'Content-Type: application/json' \
  -d '{"vx":0.2,"vy":0,"yaw":0,"duration":0.15}'

# STOP awaryjny
curl -fsS -X POST http://127.0.0.1:8080/api/stop -H 'Content-Type: application/json' -d '{}'
```

### 3a) Skręt w miejscu — preferowana ścieżka (`/api/cmd` → bus `cmd.move{yaw}`)
```bash
# lewo (yaw<0)
curl -fsS -X POST localhost:8080/api/cmd -H 'Content-Type: application/json' \
  -d '{"type":"spin","dir":"left","speed":0.35,"dur":0.45}'
# prawo (yaw>0)
curl -fsS -X POST localhost:8080/api/cmd -H 'Content-Type: application/json' \
  -d '{"type":"spin","dir":"right","speed":0.35,"dur":0.45}'
```

### 3b) Fallback klasyczny przez `/api/move`
```bash
curl -fsS -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0,"vy":0,"yaw":0.35,"duration":0.35}'
```

### 3c) /control — ręczny PUB (debug)
```bash
curl -fsS -H 'Content-Type: application/json' \
  -d '{"topic":"motion.state","via":"/control","ping":"ok"}' \
  http://127.0.0.1:8080/control
```

---

## 4) Most ruchu — szybka kontrola i parametry
```bash
# podejrzyj ENV uruchomionego mostka
PID=$(systemctl show -p MainPID --value rider-motion-bridge.service)
sudo tr '\0' '\n' </proc/$PID/environ | egrep 'DRY_RUN|SAFE_MAX_DURATION|MIN_CMD_GAP|SPEED_|TURN_STEP_'

# edycja wspólnego pliku
sudo nano /etc/default/rider-pi
sudo systemctl restart rider-motion-bridge.service
```

### 4a) Ważne zmienne (`/etc/default/rider-pi`)
```bash
BUS_PUB_PORT=5555
BUS_SUB_PORT=5556
STATUS_API_PORT=8080

DRY_RUN=0
SAFE_MAX_DURATION=0.25
MIN_CMD_GAP=0.10

# ruch liniowy
SPEED_LINEAR=12

# mapowanie skrętu: |yaw|∈[0..1] → step∈[TURN_STEP_MIN..TURN_STEP_MAX]
TURN_STEP_MIN=20
TURN_STEP_MAX=70
```
> Uwaga: stary `SPEED_TURN` nie steruje już skrętem.

---

## 5) Typowe awarie → szybkie fixy

### A) „Address already in use” na 5555/5556
- Zabij procesy i odblokuj porty:
```bash
sudo pkill -f 'services/broker.py' || true
sudo fuser -k 5555/tcp 5556/tcp 2>/dev/null || true
sudo systemctl restart rider-broker.service
```

### B) Broker aktywny, ale *systemd* krzyczy o `-ExecStartPre`
- Systemd **ignoruje** klucz z `-` w *nazwie* (prawidłowe jest `ExecStartPre=` z prefiksem `-` **przed** wartością).
- Napraw automatem z sekcji **1b**.

### C) API żyje, logi lecą, robot nie rusza
1) Sprawdź, czy most dostaje `cmd.move`:
```bash
journalctl -u rider-motion-bridge.service -n 100 --no-pager | egrep 'rx_cmd.move|turn_|forward|auto_stop'
```
2) Jeśli nie — wina ścieżki REST → BUS (upewnij `/api/cmd` lub `/api/move`).
3) Jeśli tak — podnieś `TURN_STEP_MIN/MAX` i daj `duration ≥ 0.35`.
4) Sprawdź tryb `DRY_RUN`.

### D) „Start request repeated too quickly”
```bash
journalctl -u <usługa> -n 80 --no-pager      # szukaj syntaksu/ścieżek/env
sudo systemctl daemon-reload
sudo systemctl restart <usługa>
```

### E) Konflikt ze starymi unitami dostawcy
```bash
# wyłącz i usuń stare API/bridge dostawcy
sudo systemctl disable --now rider-status-api.service rider-motion-bridge.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/rider-status-api.service \
           /etc/systemd/system/multi-user.target.wants/rider-status-api.service
# analogicznie: inne legacy jednostki właściciela
sudo systemctl daemon-reload
```

---

## 6) Dobre praktyki
- Zaczynaj testy od **DRY_RUN=1** i impulsów ≤ `SAFE_MAX_DURATION`.
- Po starcie usług daj **1–2 s** na handshake SUB przed pierwszym `move`.
- Zachowuj **≥ `MIN_CMD_GAP`** między komendami; w UI spacja=STOP.
- Zawsze miej otwarty szybki *one‑liner* restartu (poniżej).

### One‑liner restartu stosu
```bash
sudo systemctl restart rider-broker.service rider-api.service rider-motion-bridge.service
```

---

## 7) Narzędzia testowe (skrót)
```bash
# manualne impulsy (f/b/l/r/s/q)
MOTION_ENABLE=1 python3 scripts/manual_drive.py

# wszystkie kierunki (fizycznie)
MOTION_ENABLE=1 python3 scripts/test_motion.py

# ścieżka BUS → bridge → adapter
MOTION_ENABLE=1 python3 scripts/test_motion_bus.py
```

---

## 8) Słowniczek logów (co wypatrywać)
- `Broker XSUB tcp://*:5555 <-> XPUB tcp://*:5556` — broker OK.
- `[api] GET /healthz` / `[api] XGO RO connected: /dev/ttyAMA0` — API żyje / sprzęt złapany.
- `[bridge] START (... SAFE_MAX_DURATION=... MIN_CMD_GAP=...)` — most gotowy.
- `rx_cmd.move { ... }` — komenda dotarła; dalej szukaj `turn_*`/`forward` i `auto_stop`.

---

## 9) Checklista „robot nie jedzie”
1. **Porty**: `ss -ltnp | grep -E ':5555|:5556|:8080'` — muszą słuchać.
2. **Health**: `/health` lub `/healthz` → `{ok:true}`.
3. **Bus**: `sub.py` widzi `motion.cmd`/`cmd.move`?
4. **Bridge**: log `rx_cmd.move` i brak `DRY_RUN=1`.
5. **Parametry**: `TURN_STEP_MIN/MAX` i `duration ≥ 0.35` dla skrętu.
6. **Stare unity**: wyłącz/usuń legacy.
7. **Bateria**: `battery_pct` z `/sysinfo` ≥ *bezpieczny próg* (np. 15%).