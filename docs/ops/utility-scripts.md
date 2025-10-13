# Skrypty pomocnicze i narzędziowe (`ops/`)

## Skrypty testowe

### test_suite.sh

Zestaw testów systemowych — weryfikacja funkcjonalności robota.

```bash
./scripts/diag_test-suite.sh
```

⚠️ **Wymaga weryfikacji:** Zakres testów do uzupełnienia.

Prawdopodobne testy:
- BUS connectivity (Redis/ZMQ)
- Hardware (GPIO, I2C, SPI)
- Kamera (capture, preview)
- Audio (ALSA, playback, capture)
- Usługi systemd (status, startup)

---

### tests_audit.sh

Audyt testów — sprawdzenie pokrycia, brakujące testy, jakość.

```bash
./scripts/diag_tests-audit.sh
```

⚠️ **Wymaga weryfikacji:** Szczegóły do uzupełnienia.

---

### bench_detect.sh

Benchmark detekcji — wydajność detektorów wizyjnych.

```bash
./scripts/diag_bench-detect.sh [detector_type]
```

Prawdopodobnie testuje:
- HOG detector FPS
- TFLite detector FPS
- Edge TPU detector FPS
- Latencja detekcji

---

## Diagnostyka XGO

### check_xgo_sensors.py

Sprawdzenie czujników platformy XGO.

```bash
./scripts/diag_sensors.py
```

Sprawdza:
- IMU (akcelerometr, żyroskop)
- Enkodery silników
- Czujniki dystansu (jeśli są)
- Bateria (napięcie, prąd)

### Przykład output

```
[XGO Sensors Check]
IMU:        OK (ax=0.02, ay=-0.01, az=9.81 m/s²)
Gyro:       OK (gx=0.1, gy=-0.2, gz=0.0 °/s)
Encoders:   OK (FL=0, FR=0, RL=0, RR=0)
Battery:    OK (12.3V, 85%)
```

---

### xgo_bl_probe.py

Diagnostyka bootloadera XGO.

```bash
./scripts/diag_xgo-bootloader.py
```

⚠️ **Wymaga weryfikacji:** Szczegóły do uzupełnienia.

Prawdopodobnie:
- Wersja firmware
- Status połączenia I2C/UART
- Możliwość flash'owania

---

### xgo_safe_init.py

Bezpieczna inicjalizacja XGO — sprawdzenie pre-flight przed ruchem.

```bash
./scripts/sys_xgo-init.py
```

Sprawdza:
- Połączenie I2C/UART z kontrolerem
- Kalibracja IMU
- Stan baterii (min voltage)
- Temperatury silników
- E-STOP status

**Wyjście:** 
- `0` — OK, można używać
- `1` — błąd, nie uruchamiaj ruchu

---

## Demo

### demo_lemniscate.py

Demonstracja ruchu w kształcie lemniskaty (∞).

```bash
./scripts/demo_trajectory.py
```

Parametry (ENV):
```bash
export DEMO_SPEED=0.3
export DEMO_SIZE=1.0  # rozmiar pętli
./scripts/demo_trajectory.py
```

Zobacz także: [docs/apps/demos.md](../apps/demos.md)

---

## Narzędzia systemowe

### export_env.sh

Eksport zmiennych środowiskowych dla robota.

```bash
source ./scripts/util_export-env.sh
```

Ustawia:
- `PYTHONPATH`
- `RIDER_ROOT`
- `CONFIG_DIR`
- Inne globalne zmienne

**Use case:** Source'uj w `.bashrc` lub `.profile`.

---

### volume_hooks.sh

Hooki zmiany głośności — triggerowane przez ALSA/PulseAudio.

⚠️ **Wymaga weryfikacji:** Szczegóły do uzupełnienia.

Prawdopodobnie:
- Synchronizacja hardware volume
- Feedback UI (LED, LCD)
- Ograniczenia głośności (safety)

---

### services_cleanup.sh

Czyszczenie przestarzałych usług i plików tymczasowych.

```bash
./scripts/sys_cleanup.sh
```

Czyści:
- Stare logi (`/var/log/rider/`)
- PID files (`/run/rider/`)
- Temp files (`/tmp/rider-*`)
- Przestarzałe cache

---

### estop.py

Emergency stop — zatrzymanie wszystkich ruchów.

```bash
./scripts/sys_emergency-stop.py
```

Wysyła:
- `motion.cmd = {"type": "stop"}`
- Bezpośrednie zatrzymanie hardware (jeśli dostępne)
- Flaga `ESTOP_ACTIVE = 1`

**Kody wyjścia:**
- `0` — sukces (robot zatrzymany)

Zobacz: [docs/apps/safety.md](../apps/safety.md)

---

## Workflow: uruchomienie z czystego systemu

```bash
# 1. Sync systemd
sudo ./scripts/systemd-sync.sh

# 2. Check XGO
./scripts/sys_xgo-init.py || exit 1

# 3. Start core services
./scripts/sys_control.sh rider-broker.service start
./scripts/sys_control.sh rider-api.service start

# 4. Start aplikacji
./scripts/sys_control.sh rider-voice.service start
./scripts/sys_control.sh rider-vision.service start

# 5. Monitor
./scripts/diag_metrics.sh 10 &
```

---

## Workflow: debug problemu

```bash
# 1. Check sensors
./scripts/diag_sensors.py

# 2. Check services
systemctl status rider-*.service

# 3. Check logs
journalctl -u rider-broker.service --since "5 min ago"

# 4. Test suite
./scripts/diag_test-suite.sh

# 5. Monitor streams
./scripts/diag_stream.sh motion vision.state
```

---

**Related docs:**
- [docs/apps/](../apps/) — moduły aplikacyjne
- [docs/ops/systemd-scripts.md](systemd-scripts.md) — zarządzanie usługami
- [docs/apps/safety.md](../apps/safety.md) — emergency stop

**Ostatnia aktualizacja:** 2025-01  
**Status:** ⚠️ Większość szczegółów wymaga weryfikacji kodu źródłowego
