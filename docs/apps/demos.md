# Moduł Demos (`apps/demos`)

## Opis

Moduł `apps/demos` zawiera **gotowe demonstracje** ruchu robota — proste trajektorie testowe i pokazowe.

### Główne pliki

- **`trajectory.py`** — demo prostej trajektorii (forward → spin → backward → stop)

### Główne funkcje

- **`_drive_for(sock, lx, az, dur)`** — wysyła komendy ruchu przez określony czas
- **`main()`** — sekwencja demo (forward → spin right → backward → stop)

## Przepływ danych

```
Demo script
    ↓
PUB("motion") → {"type": "drive", "lx": 0.25, "az": 0.0}  (loop @ 10 Hz)
    ↓
Motion bridge (apps.motion) → XGO hardware
```

## Konfiguracja

### Zmienne środowiskowe

| Zmienna | Typ | Domyślna | Opis |
|---------|-----|----------|------|
| `BUS_PUB_ADDR` | str | `tcp://127.0.0.1:5555` | Adres brokera PUB |
| `MOTION_TOPIC` | str | `motion` | Topik komend ruchu |
| `DEMO_RATE_HZ` | float | `10` | Częstotliwość wysyłki komend (Hz) |
| `DEMO_SPEED_FWD` | float | `0.25` | Prędkość ruchu do przodu/tyłu |
| `DEMO_SPEED_ROT` | float | `0.25` | Prędkość obrotu |
| `DEMO_SEG_SEC` | float | `2.0` | Czas trwania każdego segmentu (s) |

## Sekwencja demo trajectory

1. **Forward** — jazda do przodu przez 2 s
2. **Spin right** — obrót w prawo przez 2 s
3. **Backward** — jazda do tyłu przez 2 s
4. **Stop** — zatrzymanie

## Przykład użycia

### Uruchomienie demo

```bash
# Terminal 1: uruchom motion bridge (SIM lub REAL)
export MOTION_ENABLE=0  # tryb SIM dla testów
python -m apps.motion.main

# Terminal 2: uruchom demo
python -m apps.demos.trajectory
```

### Dostosowanie parametrów

```bash
# Szybsze demo (1 s na segment, 50% prędkości)
export DEMO_SEG_SEC=1.0
export DEMO_SPEED_FWD=0.5
export DEMO_SPEED_ROT=0.5
python -m apps.demos.trajectory
```

### Uruchomienie z ops

```bash
# Jeśli istnieje skrypt w ops/
./ops/demo_lemniscate.py  # inna demo (ruch w kształcie lemniskaty)
```

## Błędy i diagnostyka

### Logowanie

Demo używa prostych printów:

```
[DEMO] Connecting PUB to tcp://127.0.0.1:5555 topic='motion'
[DEMO] forward
[DEMO] spin right
[DEMO] backward
[DEMO] stop
[DEMO] done
```

### Typowe problemy

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Brak ruchu | Motion bridge nie uruchomiony | Uruchom `apps.motion.main` w osobnym terminalu |
| Demo nie kończy się | Błąd w pętli | Ctrl+C → demo wysyła stop w `finally` |
| Ruch zbyt szybki/wolny | Nieprawidłowe parametry ENV | Dostosuj `DEMO_SPEED_*` i `DEMO_SEG_SEC` |

### Diagnostyka

```bash
# Monitoruj komendy motion
python -c "from common.bus import BusSub; s=BusSub('motion'); import json; \
while True: print(json.dumps(s.recv()[1]))"
```

## Inne dema

### demo_lemniscate.py (ops/)

⚠️ **Lokalizacja:** `ops/demo_lemniscate.py` (nie w `apps/demos/`)

Demonstracja ruchu w kształcie lemniskaty (∞).

```bash
./ops/demo_lemniscate.py
```

## Zależności

### Wewnętrzne (w repo)
- `apps.motion` — odbiera komendy `motion`

### Zewnętrzne
- `zmq` — ZeroMQ (PUB)

## Tworzenie własnych demo

### Szablon

```python
from apps.demos.trajectory import _mk_pub, _send, _drive_for
import time

def my_demo():
    sock = _mk_pub("tcp://127.0.0.1:5555")
    time.sleep(0.2)  # przebudzenie subskrybentów
    
    try:
        # Twój kod demo
        _drive_for(sock, lx=0.3, az=0.0, dur=1.0)  # forward 1s
        _send(sock, {"type": "stop"})
    finally:
        _send(sock, {"type": "stop"})
        print("[DEMO] done")

if __name__ == "__main__":
    my_demo()
```

## Rozszerzenia (TODO)

- [ ] Więcej gotowych demo w `apps/demos/` (slalom, square, circle)
- [ ] Konfiguracja sekwencji przez TOML/JSON
- [ ] Parametryzacja demo przez CLI args
- [ ] Integracja z UI (wybór demo z menu)

---

**Related docs:**
- [motion.md](motion.md) — bridge ruchu (odbiera komendy)
- [launcher.md](launcher.md) — menu startowe (uruchamianie demo)
- [docs/ops/utility-scripts.md](../ops/utility-scripts.md) — `demo_lemniscate.py`

**Ostatnia aktualizacja:** 2025-01
