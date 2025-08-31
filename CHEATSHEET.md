# CHEATSHEET.md

# Rider-Pi — ściąga operacyjna

## Najczęstsze komendy

### Usługi
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

### Health i sterowanie
```bash
curl -s http://localhost:8080/healthz | jq .

# impuls do przodu (0.6 s) + stop
curl -s -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0.6,"vy":0,"yaw":0,"duration":0.6}'
sleep 1
curl -s -X POST localhost:8080/api/stop -H 'Content-Type: application/json' -d '{}'
```

### Test „krótki impuls + auto_stop”
```bash
# SAFE_MAX_DURATION=0.25; bez ręcznego stop
curl -s -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0.2,"vy":0,"yaw":0,"duration":0.15}'
sleep 0.4
sudo tail -n 30 /var/log/rider-motion-bridge.log | egrep 'rx_cmd.move|auto_stop|stop'
```

### Skręt w miejscu (yaw)
```bash
# zwiększ tymczasowo czułość skrętu
sudo bash -lc 'sed -i "/^SPEED_TURN=/d" /etc/default/rider-pi; echo SPEED_TURN=40 >> /etc/default/rider-pi'
sudo systemctl restart rider-motion-bridge.service

# sam skręt 0.2 s
curl -s -X POST localhost:8080/api/move -H 'Content-Type: application/json' \
  -d '{"vx":0,"vy":0,"yaw":0.35,"duration":0.2}'
```

### Podsłuch magistrali (debug)
```bash
python3 scripts/bus_spy.py
# oczekuj m.in.:
#   cmd.move {...}
#   motion.bridge.event {"event":"turn_right"...}
#   motion.bridge.event {"event":"auto_stop"...}
```

---

## Konfiguracja (szybki podgląd / zmiana)

```bash
# pokaż wartości bieżącej usługi (PID i env)
PID=$(systemctl show -p MainPID --value rider-motion-bridge.service)
sudo tr '\0' '\n' </proc/$PID/environ | egrep 'DRY_RUN|SAFE_MAX_DURATION|MIN_CMD_GAP|SPEED_'

# edycja /etc/default/rider-pi
sudo nano /etc/default/rider-pi
sudo systemctl restart rider-motion-bridge.service
```

Przykładowy plik:
```bash
BUS_PUB_PORT=5555
BUS_SUB_PORT=5556
STATUS_API_PORT=8080
DRY_RUN=0
SAFE_MAX_DURATION=0.25
MIN_CMD_GAP=0.10
SPEED_LINEAR=12
SPEED_TURN=20
```

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
- `auto_stop {after_s: ...}` / `stop {}`

---

## Rozwiązywanie problemów (quick fix)

- **Brak reakcji na move**  
  - sprawdź, czy w logu pojawia się `rx_cmd.move`; jeśli nie, problem po stronie API/REST.  
  - upewnij się, że `MIN_CMD_GAP` nie filtruje zbyt gęstych impulsów.

- **„Address already in use” (5555/5556)**  
  - `sudo fuser -k 5555/tcp 5556/tcp` i restart usług.

- **Mostek nie startuje (SyntaxError / global / type hints)**  
  - masz aktualne pliki; Python 3.9 nie lubi `| None` w niektórych kontekstach – poprawione.

- **Ruch trwa zbyt długo**  
  - ustaw `SAFE_MAX_DURATION=0.25` i testuj krótkimi impulsami, panel www wysyła auto-stop przy unload.

- **Bateria wygląda OK u dostawcy, ale robot „leży”**  
  - ufamy odczytowi z `/healthz` → `devices.xgo.battery_pct` jest wiarygodny.

---

## Dobre praktyki testowe

- Po restarcie mostka daj **~1–2 s** na SUB handshake, zanim wyślesz pierwszy `move`.  
- Test „dwa strzały” (drugi po 50–100 ms) ułatwia trafienie po handshaku.  
- Zawsze zaczynaj od **STOP**, potem impulsy **≤ SAFE_MAX_DURATION**.  
- Zachowuj **przerwę ≥ MIN_CMD_GAP** między kolejnymi komendami.

---

## TODO/Ideas

- Ujednolicenie skalowania `SPEED_TURN` vs. `yaw` (lepszy low-speed curve).  
- Przyciski **E-STOP** i **HOLD-to-MOVE** w panelu.  
- Więcej metryk w `/healthz` i telemetrii (IMU, pozycja, watchdog).  
- Testy e2e + snapshot logów w `scripts/test_suite.sh`.

