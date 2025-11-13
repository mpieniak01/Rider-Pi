# Moduł Motion (`apps/motion`)

## Opis

Moduł `apps/motion` to **bridge ruchu** Rider-Pi — odbiera komendy `motion.cmd` z BUS i przekształca je na sterowanie hardware XGO. Implementuje bezpieczeństwo, watchdog, rampy prędkości i telemetrię.

### Główne pliki

- **`main.py`** — pętla główna motion, watchdog, telemetria
- **`xgo_adapter.py`** — adapter do hardware XGO (drive, spin, stop)
- **`rider_control.py`** — ⚠️ starszy kontroler (wymaga weryfikacji użycia)

### Główne funkcje

- **Watchdog:** Auto-stop po braku komend (domyślnie 500 ms)
- **Rampa prędkości:** Miękki start/stop (ramp_lx, ramp_az)
- **Sterowanie impulsowe:** Krótkie impulsy ruchu zamiast ciągłego sterowania
- **Bezpieczeństwo:** E-STOP, limity prędkości, flagi enable/disable
- **Telemetria:** Publikacja `motion.state` (prędkość, timestamp, bateria)

## Przepływ danych

```
Wejście:  SUB("motion") → {"type": "drive", "lx": 0.5, "az": 0.0}
                        → {"type": "stop"}
          ↓
Filtr:    E-STOP check, MOTION_ENABLE flag, safe_speed clamp
          ↓
Rampa:    Miękki start/stop (ramp_lx/ramp_az)
          ↓
Adapter:  XgoAdapter.drive(dir, speed, dur) lub .spin(dir, speed, dur)
          ↓
Wyjście:  PUB("motion.state") → {"lx": ..., "az": ..., "ts": ..., "battery": ...}
```

## Konfiguracja

### Zmienne środowiskowe

| Zmienna | Typ | Domyślna | Opis |
|---------|-----|----------|------|
| `MOTION_WATCHDOG_MS` | int | `500` | Timeout watchdog (ms) — auto-stop bez komend |
| `MOTION_LOOP_DT` | float | `0.02` | Okres pętli głównej (s) → 50 Hz |
| `MOTION_SPEED_LIMIT` | float | `0.6` | Maksymalna prędkość (clamp 0.0–1.0) |
| `MOTION_RAMP_LX` | float | `1.0` | Rampa liniowa (jednostki/s) |
| `MOTION_RAMP_AZ` | float | `2.0` | Rampa obrotowa (jednostki/s) |
| `MOTION_EPS` | float | `0.01` | Próg "ruch = 0" (ignore małe wartości) |
| `MOTION_DRIVE_IMPULSE_SEC` | float | `0.15` | Czas impulsu ruchu liniowego (s) |
| `MOTION_YAW_IMPULSE_SEC` | float | `0.18` | Czas impulsu obrotu (s) |
| `BUS_SUB_ADDR` | str | `tcp://127.0.0.1:5556` | Adres SUB (XPUB broker) |
| `MOTION_TOPIC` | str | `motion` | Topik subskrypcji komend |
| `BUS_PUB_ADDR` | str | `tcp://127.0.0.1:5555` | Adres PUB telemetrii |
| `MOTION_STATE_TOPIC` | str | `motion.state` | Topik publikacji stanu |
| `MOTION_TELEM_HZ` | float | `5.0` | Częstotliwość telemetrii (Hz) |
| `MOTION_LOG_LEVEL` | str | `INFO` | Poziom logów (DEBUG, INFO, WARNING) |

### Tryby adaptera

- **Real:** `MOTION_ENABLE=1` → XgoAdapter (prawdziwy ruch)
- **Sim:** `MOTION_ENABLE=0` → _SimAdapter (logi, brak ruchu)

## Struktura komend motion

### Drive (jazda liniowa)
```json
{
  "type": "drive",
  "lx": 0.5,     // -1.0 (do tyłu) do 1.0 (do przodu)
  "az": 0.0      // opcjonalny: -1.0 (w prawo) do 1.0 (w lewo)
}
```

### Spin (obrót w miejscu)
```json
{
  "type": "drive",
  "lx": 0.0,
  "az": 0.5      // -1.0 (w prawo) do 1.0 (w lewo)
}
```

### Stop
```json
{
  "type": "stop"
}
```

## Struktura telemetrii motion.state

```json
{
  "lx": 0.5,           // aktualna prędkość liniowa
  "az": 0.0,           // aktualna prędkość obrotowa
  "ts": 1704067200.5,  // timestamp
  "battery": 0.85      // poziom baterii (0.0–1.0)
}
```

## Przykład użycia

### Uruchomienie ręczne (SIM)

```bash
# Tryb symulacji (bez prawdziwego ruchu)
export MOTION_ENABLE=0
python -m apps.motion.main
```

### Uruchomienie na urządzeniu (REAL)

```bash
# Prawdziwy ruch (wymaga XGO)
export MOTION_ENABLE=1
sudo python -m apps.motion.main  # sudo jeśli wymagane dla GPIO/I2C
```

### Wysyłanie komend testowych

```bash
# Terminal 1: uruchom motion
python -m apps.motion.main

# Terminal 2: wyślij komendę
python -c "from common.bus import BusPub; BusPub().publish('motion', {'type': 'drive', 'lx': 0.3, 'az': 0.0})"

# Terminal 3: stop
python -c "from common.bus import BusPub; BusPub().publish('motion', {'type': 'stop'})"
```

## Błędy i diagnostyka

### Logowanie

Logger `motion` → poziom `INFO` (domyślnie):

```
[INFO] Init RealAdapter (XgoAdapter) — real movement ENABLED
[INFO] [SIM] move lx=0.500 az=0.000
[INFO] WATCHDOG: no command for 500ms → STOP
```

### Typowe problemy

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Brak ruchu mimo komend | `MOTION_ENABLE=0` (tryb SIM) | Ustaw `MOTION_ENABLE=1` |
| Auto-stop zbyt szybki | Watchdog timeout za krótki | Zwiększ `MOTION_WATCHDOG_MS` |
| Ruch zbyt gwałtowny | Rampa zbyt duża | Zmniejsz `MOTION_RAMP_LX`/`MOTION_RAMP_AZ` |
| E-STOP blokuje ruch | Flaga bezpieczeństwa aktywna | Sprawdź `apps/safety/estop.py` |

### Diagnostyka

```bash
# Sprawdź tryb adaptera
env | grep MOTION_ENABLE

# Monitoruj telemetrię
python -c "from common.bus import BusSub; import json; s=BusSub('motion.state'); print(json.dumps(s.recv()[1], indent=2))"

# Debuguj logi
export MOTION_LOG_LEVEL=DEBUG
python -m apps.motion.main
```

## Zależności

### Wewnętrzne (w repo)
- `apps.safety.estop` — sprawdzanie E-STOP, flagi MOTION_ENABLE
- `apps.motion.xgo_adapter.XgoAdapter` — hardware adapter
- `common.pidlock.single_instance` — blokada pojedynczej instancji
- `common.bus` — komunikacja ZeroMQ/Redis

### Zewnętrzne
- `zmq` — ZeroMQ (BUS)
- Hardware XGO (I2C, GPIO) — tylko w trybie REAL

## XgoAdapter API

### `drive(direction, speed, dur, block=False)`
- **direction:** `"forward"` | `"backward"`
- **speed:** `0.0–1.0`
- **dur:** czas trwania (s)
- **block:** czekaj na zakończenie (domyślnie `False`)

### `spin(direction, speed, dur, deg=None, block=False)`
- **direction:** `"left"` | `"right"`
- **speed:** `0.0–1.0`
- **dur:** czas trwania (s)
- **deg:** opcjonalny kąt obrotu (°)
- **block:** czekaj na zakończenie

### `stop()`
Natychmiastowy stop (przerywa impulsy w toku).

## Rozszerzenia (TODO)

- [ ] Konfiguracja przez TOML zamiast tylko ENV
- [ ] Precyzyjniejsza odometria (enkodery, IMU fusion)
- [ ] Feedback z hardware (rzeczywista prędkość, błędy)
- [ ] Wsparcie dla różnych platform (nie tylko XGO)

---

**Related docs:**
- [nlu.md](nlu.md) — generuje komendy `motion.cmd`
- [safety.md](safety.md) — E-STOP, flagi bezpieczeństwa
- [demos.md](demos.md) — demonstracje wykorzystujące motion

**Ostatnia aktualizacja:** 2025-01
