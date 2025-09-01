# CHEATSHEET.md

# Rider-Pi — ściąga operacyjna (aktualna)

## Najczęstsze komendy

### Usługi (restart całego stosu)
```bash
# status + logi skrócone
sudo systemctl --no-pager -l status rider-broker.service rider-status-api.service rider-motion-bridge.service
journalctl -u rider-motion-bridge.service -n 50 --no-pager

# start/stop/restart
sudo systemctl restart rider-broker.service rider-status-api.service rider-motion-bridge.service
sudo systemctl stop rider-motion-bridge.service
sudo systemctl start rider-motion-bridge.service
```

### Porty ZMQ
```bash
sudo fuser -v 5555/tcp 5556/tcp
sudo fuser -k 5555/tcp 5556/tcp || true  # ubij okupantów
```

---

## Health i sterowanie (REST)

### Health
```bash
curl -s http://localhost:8080/healthz | jq .
```

### Ruch liniowy (impuls do przodu 0.6 s) + STOP
```bash
curl -s -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0.6,"vy":0,"yaw":0,"duration":0.6}'
sleep 1
curl -s -X POST localhost:8080/api/stop -H 'Content-Type: application/json' -d '{}'
```

### Skręt w miejscu (nowa, pewna ścieżka)
> Front `/control` wysyła `POST /api/cmd` i backend mapuje to na bus `cmd.move {yaw}`.
```bash
# spin w LEWO (yaw < 0)
curl -s -X POST localhost:8080/api/cmd -H 'Content-Type: application/json' \
  -d '{"type":"spin","dir":"left","speed":0.35,"dur":0.45}'

# spin w PRAWO (yaw > 0)
curl -s -X POST localhost:8080/api/cmd -H 'Content-Type: application/json' \
  -d '{"type":"spin","dir":"right","speed":0.35,"dur":0.45}'
```

### Skręt w miejscu (klasycznie przez `/api/move`)
```bash
# sam skręt 0.2 s (prawo)
curl -s -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0,"vy":0,"yaw":0.35,"duration":0.2}'
```

---

## Test „krótki impuls + auto_stop”
```bash
# SAFE_MAX_DURATION limituje maks. czas ruchu (np. 0.25 s)
curl -s -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0.2,"vy":0,"yaw":0,"duration":0.15}'
sleep 0.4
sudo tail -n 30 /var/log/rider-motion-bridge.log | egrep 'rx_cmd.move|auto_stop|stop'
```

---

## Podsłuch magistrali (debug)
```bash
python3 scripts/bus_spy.py
# oczekuj m.in.:
#   cmd.move {...}
#   cmd.stop {...}
#   motion.bridge.event {"event":"turn_right"...}
#   motion.bridge.event {"event":"auto_stop"...}
```

---

## Skrypty testowe (nowe)

> Wymagają uruchomionej pętli ruchu i/lub mostka. Dla testu fizycznego ustaw `MOTION_ENABLE=1`.

```bash
# Manualne sterowanie impulsami z klawiatury (f/b/l/r/s/q)
MOTION_ENABLE=1 python3 scripts/manual_drive.py

# Test fizyczny wszystkich kierunków (forward/back/left/right)
MOTION_ENABLE=1 python3 scripts/test_motion.py

# Test ścieżki BUS → bridge → adapter (publikuje na topic 'motion.cmd' i echo)
MOTION_ENABLE=1 python3 scripts/test_motion_bus.py
```

**Parametry (domyślne w manual_drive):**
- `RIDER_SPEED_LIN` – prędkość liniowa (0..1) domyślna: `0.08`
- `RIDER_PULSE` – czas impulsu f/b (s) domyślnie: `0.12`
- `RIDER_TURN_THETA` – kąt referencyjny (°) dla logów: `22`
- `RIDER_TURN_MINTIME` – min. czas skrętu (s): `0.35`

Przykłady komend w `manual_drive.py`:
```
f 0.08 0.12   # naprzód (mały impuls)
b 0.08 0.12   # wstecz (mały impuls)
l 22 0.35     # skręt w lewo (ok. 0.35 s)
r 22 0.35     # skręt w prawo (ok. 0.35 s)
s             # STOP
i             # IMU (roll/pitch/yaw)
q             # wyjście
```

---

## Konfiguracja (szybki podgląd / zmiana)

```bash
# pokaż wartości bieżącej usługi (PID i env)
PID=$(systemctl show -p MainPID --value rider-motion-bridge.service)
sudo tr '\0' '\n' </proc/$PID/environ | egrep 'DRY_RUN|SAFE_MAX_DURATION|MIN_CMD_GAP|SPEED_|TURN_STEP_'

# edycja /etc/default/rider-pi
sudo nano /etc/default/rider-pi
sudo systemctl restart rider-motion-bridge.service
```

Przykładowy `/etc/default/rider-pi` (ważne nowe zmienne):
```bash
BUS_PUB_PORT=5555
BUS_SUB_PORT=5556
STATUS_API_PORT=8080

DRY_RUN=0
SAFE_MAX_DURATION=0.25
MIN_CMD_GAP=0.10

# skalowanie ruchu liniowego
SPEED_LINEAR=12

# mapowanie skrętu: |yaw|∈[0..1] → step∈[TURN_STEP_MIN..TURN_STEP_MAX]
TURN_STEP_MIN=20
TURN_STEP_MAX=70
```

> **Uwaga:** starszy `SPEED_TURN` nie jest już używany do skrętu. Za skręt odpowiada mapowanie
> `yaw → turnleft/turnright(step)` z zakresu `TURN_STEP_MIN..TURN_STEP_MAX`.

---

## Logi

```bash
# mostek (jeśli włączony append do pliku)
sudo tail -f /var/log/rider-motion-bridge.log

# lub standardowo przez journalctl
journalctl -fu rider-motion-bridge.service --no-pager
```

Linie warte uwagi:
- `START (PUB:... DRY_RUN=... SAFE_MAX_DURATION=... MIN_CMD_GAP=...)`
- `ready { ... }` (mostek gotowy)
- `rx_cmd.move { ... }` / `forward/turn_* ...`
- `turn_method_used {dir:..., method:...}` (jeśli logowane)
- `auto_stop {after_s: ...}` / `stop {}`

---

## Rozwiązywanie problemów (quick fix)

- **Brak skrętu**  
  - sprawdź, czy do mostka dochodzi `rx_cmd.move` z `yaw ≠ 0`.  
  - podnieś `TURN_STEP_MIN` (np. `30`) i `TURN_STEP_MAX` (np. `70`).  
  - upewnij się, że `duration` ≥ `0.35` dla krótkich impulsów testowych.

- **Lewo powoduje „siadanie”**  
  - używasz starego mostka z pivotem przez `translation`. Zaktualizuj `scripts/motion_bridge.py`
    do wersji mapującej na `turnleft/turnright(step)`.

- **Brak reakcji na move**  
  - sprawdź `rx_cmd.move` w logu; jeżeli nie ma — problem po stronie REST/API.  
  - odczekaj ≥ `MIN_CMD_GAP` między impulsami.

- **„Address already in use” (5555/5556)**  
  - `sudo fuser -k 5555/tcp 5556/tcp` i restart usług.

- **Ruch trwa zbyt długo**  
  - ustaw `SAFE_MAX_DURATION=0.25` i testuj krótkimi impulsami, panel web wysyła STOP przy unload.

---

## Dobre praktyki testowe

- Po restarcie mostka daj **~1–2 s** na SUB handshake, zanim wyślesz pierwszy `move`.  
- „Double-tap”: dwa krótkie impulsy (drugi po ~80–120 ms) lepiej trafiają tuż po starcie.  
- **STOP** zawsze pod ręką: spacja w UI, `POST /api/stop` w skryptach.  
- Utrzymuj **przerwę ≥ MIN_CMD_GAP** między komendami.

---

## Szybki restart stosu (one-liner)
```bash
sudo systemctl restart rider-broker.service rider-status-api.service rider-motion-bridge.service
```

---

## TODO / pomysły

- Łagodna krzywa dla niskich wartości yaw (sub-linear mapping przed step).
- E-STOP/HOLD-to-MOVE w panelu WWW.
- Więcej metryk IMU/bateria na `/healthz` i w panelu.  
- Testy e2e i snapshot logów (`scripts/test_suite.sh`).

