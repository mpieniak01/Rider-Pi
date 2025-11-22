# Symulator 2D Rider-Pi

Niezależny symulator 2D dla Rider-Pi umożliwiający testowanie algorytmów nawigacji bez sprzętu fizycznego.

## Funkcjonalności

- **Symulacja fizyki w czasie rzeczywistym**: Symuluje ruch robota z realistyczną kinematyką
- **Integracja MQTT**: Wykorzystuje ten sam protokół magistrali MQTT co prawdziwy robot
- **Wizualna informacja zwrotna**: 
  - Widok z góry robota i środowiska
  - Widok kamery z perspektywy pierwszej osoby z renderowaniem perspektywicznym
  - Wyświetlanie telemetrii w czasie rzeczywistym
- **Wczytywanie map**: Wczytywanie własnych środowisk z prostych plików tekstowych
- **Publikowanie danych sensorów**: Wirtualny żyroskop i kamera publikują dane do tematów MQTT

## Szybki start

### Uruchamianie symulatora

```bash
python scripts/sim/run_simulation.py
```

### Zmienne środowiskowe

- `SIM_MAP`: Ścieżka do pliku mapy (domyślnie: `sim/maps/simple.txt`)
- `SIM_WIDTH`: Szerokość okna w pikselach (domyślnie: 1280)
- `SIM_HEIGHT`: Wysokość okna w pikselach (domyślnie: 720)
- `SIM_FPS`: Liczba klatek symulacji (domyślnie: 30)
- `SIM_LOG_LEVEL`: Poziom logowania (domyślnie: INFO)

### Tematy MQTT

Symulator wykorzystuje te same tematy MQTT co prawdziwy robot:

**Subskrybowane (wejścia):**
- `motion` - Komendy sterowania: `{"type": "drive", "lx": 0.5, "az": 0.2}` lub `{"type": "stop"}`

**Publikowane (wyjścia):**
- `rider.gyro.angle` - Orientacja robota w stopniach
- `rider.camera.frame` - Obraz z kamery jako bajty JPEG

### Sterowanie robotem

Użyj istniejących narzędzi do sterowania symulowanym robotem:

```bash
# Monitorowanie ruchu MQTT
python scripts/diag_bus-spy.py

# Wysyłanie ręcznych komend
python scripts/dev_send-cmd.py
```

Lub publikuj komendy bezpośrednio:

```python
import zmq
import json

ctx = zmq.Context.instance()
pub = ctx.socket(zmq.PUB)
pub.connect("tcp://127.0.0.1:5555")

# Jazda do przodu
pub.send_multipart([
    b"motion",
    json.dumps({"type": "drive", "lx": 0.5, "az": 0.0}).encode()
])

# Stop
pub.send_multipart([
    b"motion",
    json.dumps({"type": "stop"}).encode()
])
```

## Format mapy

Mapy to proste pliki tekstowe z następującymi znakami:

- `X` - Ściana/przeszkoda
- `R` - Pozycja startowa robota
- `M` - Cel/punkt docelowy
- ` ` (spacja) - Pusta przestrzeń

Przykład:

```
XXXXXXXXXX
X        X
X   R    X
X        X
X    M   X
XXXXXXXXXX
```

### Dostępne mapy

- `sim/maps/simple.txt` - Podstawowe środowisko testowe
- `sim/maps/corridor.txt` - Długi korytarz
- `sim/maps/maze.txt` - Złożone środowisko z przeszkodami

## Architektura

Symulator jest całkowicie niezależny od pakietu `rider_pi` i nie ma bezpośrednich importów z niego. Komunikuje się wyłącznie przez magistralę MQTT, działając jako cyfrowy bliźniak fizycznego robota.

### Komponenty

- **`sim/world.py`** - Główne środowisko symulacji i renderowanie Pygame
- **`sim/robot.py`** - Wirtualny robot z fizyką i sterowaniem MQTT
- **`sim/sensors.py`** - Wirtualny żyroskop i kamera z publikowaniem MQTT
- **`scripts/sim/run_simulation.py`** - Skrypt punktu wejścia

## Rozwój

### Testowanie

```bash
# Uruchom testy symulatora
pytest tests/test_simulator.py -v

# Uruchom z konkretną mapą
SIM_MAP=sim/maps/maze.txt python scripts/sim/run_simulation.py
```

### Linting

```bash
ruff check sim/ scripts/sim/run_simulation.py
ruff format sim/ scripts/sim/run_simulation.py
```

## Integracja z algorytmami nawigacji

Ten sam kod algorytmu nawigacji może sterować zarówno symulatorem, jak i prawdziwym robotem, po prostu łącząc się z magistralą MQTT. Nie są wymagane żadne zmiany w kodzie.

Przykład:

```python
# Ten kod działa zarówno z symulatorem, jak i prawdziwym robotem
from common.bus import BusPub, BusSub

pub = BusPub()
sub = BusSub("rider.gyro.angle")

# Wyślij komendę ruchu
pub.publish("motion", {"type": "drive", "lx": 0.5, "az": 0.0})

# Odbierz dane z sensorów
for topic, payload in sub:
    print(f"Angle: {payload['angle']}")
```

## Sterowanie klawiaturą

- `ESC` - Zakończ symulację

Komendy sterowania muszą być wysyłane przez MQTT w celu realistycznego testowania.
