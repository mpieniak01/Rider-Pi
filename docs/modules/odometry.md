# Odometry Module — Position Tracking for Rider-Pi

## Cel

Moduł **odometrii** (ang. *odometry*) śledzi pozycję i orientację robota w czasie rzeczywistym poprzez fuzję danych z komend ruchu oraz czujnika IMU. Jest to kluczowy komponent dla nawigacji autonomicznej, mapowania i powrotu do bazy.

## Architektura

### Przepływ Danych

```text
[Navigator/Manual Control]
        ↓ (motion commands)
    [Motion Bridge] ──────────┐
        ↓                     ↓
    [XGO Robot]           [Odometry]
        ↓ (IMU data)          ↓
    [Motion Bridge] ──────────┘
        ↓
    [Odometry] ──> (robot.pose) ──> [Mapping/Navigation]
```

### Komponenty

1. **OdometryEstimator** — estymator pozy wykorzystujący:
   - **Dead reckoning** z komend ruchu (liniowa i kątowa prędkość)
   - **Korekcja IMU** dla orientacji (kąt yaw z żyroskopu)
   - **Fuzja danych** dla dokładniejszego śledzenia

2. **Odometry** — główny moduł systemowy:
   - Subskrybuje `motion` (komendy ruchu)
   - Subskrybuje `imu.data` (dane z IMU)
   - Publikuje `robot.pose` (estymowana poza)

## API Magistrali

### Subskrybowane Tematy

#### `motion` (TOPIC_MOTION_COMMAND)

Komendy ruchu wysyłane przez navigator lub sterowanie manualne.

**Format:**
```json
{
  "type": "drive",
  "lx": 0.3,      // Prędkość liniowa (forward/backward), zakres -1..1
  "az": 0.0       // Prędkość kątowa (rotation), zakres -1..1
}
```

lub:

```json
{
  "type": "stop"
}
```

#### `imu.data` (TOPIC_IMU_DATA)

Surowe dane z czujnika IMU publikowane przez `motion bridge`.

**Format:**
```json
{
  "roll": 0.5,    // Kąt przechyłu (degrees)
  "pitch": -1.2,  // Kąt pochylenia (degrees)
  "yaw": 45.3,    // Kąt obrotu (degrees) - używany przez odometrię
  "ts": 1234567890.123
}
```

### Publikowany Temat

#### `robot.pose` (TOPIC_ROBOT_POSE)

Estymowana pozycja i orientacja robota w globalnym układzie współrzędnych.

**Format:**
```json
{
  "x": 1.234,         // Pozycja X w metrach
  "y": 0.567,         // Pozycja Y w metrach
  "theta": 0.785,     // Orientacja w radianach
  "theta_deg": 45.0,  // Orientacja w stopniach (dla wygody)
  "ts": 1234567890.123
}
```

**Układ współrzędnych:**
- Początek: pozycja startu robota (domyślnie 0, 0)
- Oś X: kierunek "do przodu" przy starcie
- Oś Y: kierunek "w lewo" przy starcie (standardowa orientacja matematyczna)
- Theta: kąt obrotu od osi X (dodatnie = obrót w lewo)

## Konfiguracja (ENV)

### Podstawowa

| Zmienna | Domyślnie | Opis |
|---------|-----------|------|
| `ODOMETRY_LOG_LEVEL` | `INFO` | Poziom logowania |
| `ODOMETRY_UPDATE_RATE_HZ` | `10.0` | Częstotliwość aktualizacji pozy (Hz) |
| `ODOMETRY_PUBLISH_RATE_HZ` | `5.0` | Częstotliwość publikacji na bus (Hz) |

### Pozycja Początkowa

| Zmienna | Domyślnie | Opis |
|---------|-----------|------|
| `ODOMETRY_INITIAL_X` | `0.0` | Początkowa pozycja X (m) |
| `ODOMETRY_INITIAL_Y` | `0.0` | Początkowa pozycja Y (m) |
| `ODOMETRY_INITIAL_THETA` | `0.0` | Początkowa orientacja (rad) |

### Model Ruchu

| Zmiећања | Domyślnie | Opis |
|---------|-----------|------|
| `ODOMETRY_LINEAR_SPEED_SCALE` | `0.2` | Skala prędkości liniowej: m/s na jednostkę prędkości znormalizowanej (0-1) |
| `ODOMETRY_ANGULAR_SPEED_SCALE` | `1.0` | Skala prędkości kątowej: rad/s na jednostkę prędkości znormalizowanej (0-1) |

## Algorytm Estymatora

### 1. Fuzja Danych

Estymator łączy dwa źródła informacji:

**a) Komendy Ruchu (Dead Reckoning):**
- Prędkość liniowa `lx` → przemieszczenie w kierunku orientacji
- Prędkość kątowa `az` → zmiana orientacji (gdy brak IMU)

**b) Dane IMU (Korekcja Orientacji):**
- Kąt `yaw` → bezpośrednia korekcja orientacji `theta`
- Nadpisuje dead reckoning dla orientacji (bardziej dokładne)

### 2. Aktualizacja Pozy

W każdym cyklu aktualizacji (domyślnie 10 Hz):

```python
# Orientacja (priorytet: IMU > dead reckoning)
if imu_available:
    theta = theta + delta_yaw_from_imu
else:
    theta = theta + (az * ANGULAR_SPEED_SCALE * dt)

# Pozycja (dead reckoning w kierunku aktualnej orientacji)
v_linear = lx * LINEAR_SPEED_SCALE
dx = v_linear * cos(theta) * dt
dy = v_linear * sin(theta) * dt
x = x + dx
y = y + dy
```

### 3. Normalizacja Kąta

Wszystkie kąty są normalizowane do zakresu `[-π, π]` aby uniknąć problemów z przeskokami.

## Dokładność i Ograniczenia

### Źródła Błędów

1. **Poślizg kół** — nie jest mierzony, może powodować dryft pozycji
2. **Opóźnienia komunikacji** — niewielkie opóźnienia w magistrali ZMQ
3. **Kalibracja IMU** — może wymagać kalibracji przy starcie
4. **Skala prędkości** — wymaga kalibracji dla specyfiki robota

### Oczekiwana Dokładność

- **Orientacja (z IMU):** ±2-5° (zależnie od jakości IMU)
- **Orientacja (bez IMU):** ±10-20° (akumulacja błędów dead reckoning)
- **Pozycja (1 metr jazdy):** ±5-15 cm (zależnie od nawierzchni)

### Zalecenia

1. **Kalibracja** — uruchom robota, zmierz rzeczywisty dystans i skalibruj `LINEAR_SPEED_SCALE`
2. **Test orientacji** — wykonaj obrót 360° i sprawdź czy `theta` wraca do 0
3. **Korekcja wizualna** — w przyszłych etapach (Stage 3+) można dodać korekcję z vision (SLAM)

## Kalibracja

### Kalibracja Prędkości Liniowej

1. Wyślij komendę: `{"type": "drive", "lx": 1.0, "az": 0.0}` przez 10 sekund
2. Zmierz przebytą odległość fizycznie (np. 2.0 m)
3. Oblicz: `ODOMETRY_LINEAR_SPEED_SCALE = dystans_rzeczywisty / (10 * 1.0)`
4. Przykład: jeśli robot przejechał 2.0m → `SCALE = 2.0 / 10 = 0.2`

### Kalibracja Prędkości Kątowej

1. Wyślij komendę: `{"type": "drive", "lx": 0.0, "az": 1.0}` przez określony czas
2. Zmierz kąt obrotu fizycznie (np. 90° = π/2 rad w 1.57 s)
3. Oblicz: `ODOMETRY_ANGULAR_SPEED_SCALE = kat_rad / czas_s`
4. Przykład: jeśli robot obrócił się o 90° w 1.57s → `SCALE = 1.57 / 1.57 = 1.0`

**Uwaga:** Jeśli masz działające IMU, kalibracja kątowa jest mniej krytyczna.

## Testowanie

### Testy Jednostkowe

```bash
pytest tests/test_odometry.py -v
```

### Test Manualny — Jazda Prosto

1. Uruchom odometry: `systemctl start rider-odometry`
2. Subskrybuj pozycję: `mosquitto_sub -h localhost -t 'robot/pose'` (jeśli używasz MQTT bridge)
   lub użyj narzędzia ZMQ do nasłuchu na `robot.pose`
3. Wyślij komendę jazdy: `{"type": "drive", "lx": 1.0, "az": 0.0}` przez 5 sekund
4. Sprawdź czy `x` rośnie o ~1.0m (przy domyślnej skali 0.2 m/s)

### Test Manualny — Obrót w Miejscu

1. Uruchom odometry
2. Wyślij komendę: `{"type": "drive", "lx": 0.0, "az": 1.0}` przez π/2 sekund
3. Sprawdź czy `theta_deg` wzrosło o ~90°

## Integracja z Innymi Modułami

### Navigator (Rekonesans)

Navigator korzysta z odometrii pośrednio — obecnie nie konsumuje `robot.pose`, ale w przyszłych etapach (Stage 3: Mapowanie) będzie zapisywał trajektorię ruchu.

### Motion Bridge

Motion bridge publikuje dane IMU na temat `imu.data`, które odometria wykorzystuje do korekcji orientacji.

### Przyszłe Etapy

- **Stage 3 (Mapowanie):** zapisywanie pozy + wykrywanie przeszkód → budowa mapy
- **Stage 4 (Powrót do bazy):** odtworzenie trajektorii i nawigacja z powrotem

## Uruchamianie

### Systemd Service

```bash
# Start
sudo systemctl start rider-odometry

# Status
sudo systemctl status rider-odometry

# Logi
sudo journalctl -u rider-odometry -f

# Enable at boot
sudo systemctl enable rider-odometry
```

### Standalone (development)

```bash
cd /home/pi/robot
python3 -m apps.odometry.main
```

## Rozwiązywanie Problemów

### Problem: Pozycja nie zmienia się

**Możliwe przyczyny:**
1. Brak komend ruchu na magistrali → sprawdź `motion` topic
2. Motion bridge nie działa → sprawdź `rider-motion-bridge.service`
3. Broker ZMQ nie działa → sprawdź `rider-broker.service`

**Diagnostyka:**
```bash
# Sprawdź czy motion bridge działa
systemctl status rider-motion-bridge

# Sprawdź logi odometry
journalctl -u rider-odometry -n 50

# Testuj ręcznie magistralę
python3 -c "from common.bus import BusPub; p = BusPub(); p.publish('motion', {'type': 'drive', 'lx': 0.5, 'az': 0.0})"
```

### Problem: Orientacja dryfuje

**Możliwe przyczyny:**
1. Brak danych IMU → sprawdź czy motion bridge publikuje `imu.data`
2. IMU nie skalibrowany → wykonaj kalibrację IMU w `drivers/xgo`
3. Wartość `ANGULAR_SPEED_SCALE` źle dobrana

**Diagnostyka:**
```bash
# Sprawdź czy IMU publikuje dane
# (wymaga narzędzia do nasłuchu ZMQ)

# Zresetuj pozę odometry (restart serwisu)
sudo systemctl restart rider-odometry
```

### Problem: Pozycja rośnie za szybko/wolno

**Rozwiązanie:**
Skalibruj `ODOMETRY_LINEAR_SPEED_SCALE` według instrukcji w sekcji Kalibracja.

## Zobacz Również

- `docs/modules/navigator.md` — moduł nawigacji autonomicznej (Stage 1)
- `ARCHITECTURE.md` — ogólna architektura systemu
- `common/bus.py` — definicje tematów magistrali
