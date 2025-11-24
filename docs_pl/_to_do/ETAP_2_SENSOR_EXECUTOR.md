# Etap 2.A – Sensor Reader i Motion Executor

## Cel
Wyprowadzić z `rider-motion-bridge.service` dwie niezależne usługi:
- **sensor-reader** – odpowiedzialną tylko za odczyty IMU/odometrii i publikację na busie (`robot.pose`, `imu.data`).
- **motion-executor** – przyjmującą komendy (`cmd.move`, `cmd.stop`, `tracking.pose`) i wykonującą je na XGO (z zachowaniem istniejących zabezpieczeń: deadman, debounce, readonly tryb).

## Plan działania (szczegółowy)
### 1. Analiza i podział odpowiedzialności
- **Wejścia/sensory** (docelowo `sensor-reader`): w `services/motion_bridge.py` / `apps/motion/main.py` zebrać funkcje odczytu IMU/yaw/battery (`read_xgo_telemetry`, `_read_attitude`, `_get_val`, `get_imu`), publikację `devices.xgo` i ewentualnego `imu.data`/`robot.pose`.
- **Wyjścia/ruch** (docelowo `motion-executor`): obsługa tematów `cmd.move`, `cmd.stop`, `cmd.motion.*`, logika deadmana (`_schedule_deadman`), anty-lag (`DROP_OLD_MS`, `PREEMPT`), filtry prędkości i mapowanie na metody XGO (`_call_move`, `_try_call`).
- **Kontrakty scenariuszy (S0–S4 z SCENARIUSZY)**: manual (S1) musi zawsze działać; S3/S4 korzystają z `tracking.pose` + sterowania ruchem; tryby DEV mogą wymagać readonly.

### 2. Nowe moduły
- `apps.motion.sensor_reader`: start XGO/IMU w trybie tylko-odczyt; PUB `imu.data`, `devices.xgo`, opcjonalnie `robot.pose`; sterowanie częstotliwością ENV (`IMU_HZ`).
- `apps.motion.executor`: SUB `cmd.move`, `cmd.stop`, kompatybilne `cmd.motion.*`, `tracking.pose`; PUB `motion.bridge.event`, `motion.state`; zachowuje deadman, debounce, E-Stop, readonly.
- Wspólne helpery (stabilizacja yaw, mapowanie komend) można wydzielić do `apps.motion.common`.

### 3. Systemd / migracja
- Dodać `sensor-reader.service` i `motion-executor.service` do `systemd/`, `systemd-sync.sh`, `SERVICE_META`.
- Targety (`rider-core`, `rider-followme`, `rider-recon`) przepiąć z `rider-motion-bridge.service` na nowe usługi.
- `rider-motion-bridge.service` przenieść do `systemd/legacy/` po weryfikacji (lub zostawić jako shim wołający motion-executor).

### 4. Kontrakty topiców
- **Wejścia executor**: `cmd.move {vx, vy?, az?, duration, ts}`, `tracking.pose {target:{x,y}, mode, ts}`, kompatybilne `cmd.motion.*`.
- **Wyjścia sensor-reader**: `imu.data {roll,pitch,yaw,yaw_rate,ts,src}`, `devices.xgo {battery_pct,yaw,fw,ts}`, opcjonalnie `robot.pose`.
- **Wyjścia executor**: `motion.bridge.event`, `motion.state` (ostatnie komendy/prędkości, watchdog).

### 5. Testy i walidacja
1) Jednostkowe/symulacja: `DRY_RUN=1`, `BRIDGE_READONLY=1` → publikuj `cmd.move` i sprawdź eventy.  
2) S1 manual: obsługa `cmd.motion.*`/`/api/control` → executor reaguje; deadman stop.  
3) S3 Follow Me: publikacja `tracking.pose` → ruch we właściwą stronę.  
4) S4 Rekonesans: navigator/return_home → brak regresji, prawidłowe eventy.  
5) Integracja: `/svc` pokazuje nowe usługi, `/api/logic/state` wskazuje targety z sensor-reader/em; monitoruj logi deadmana.

## Aktualny stan po iteracji (testy HW + targety)
- **Nowe usługi**: `sensor-reader.service` i `motion-executor.service` są dostępne w systemd, domyślnie włączone przez `rider-core.target`. Stary `rider-motion-bridge.service` został przeniesiony do `systemd/legacy/` (tylko na potrzeby rollbacku).
- **Targety scenariuszy**: dopisano `rider-voice.target` (S5), `rider-mapbuild.target` (S8) i `rider-navigate.target` (S9) – wszystkie korzystają z pary sensor-reader/motion-executor i wspólnego feedu kamer (`frame-distributor`).
- **Dokumentacja**: zaktualizowano `SCENARIUSZE_BIZNESOWE.md` oraz `SYSTEMD_SERVICES_MAPPING.md` (PL/EN) i inventory, żeby odzwierciedlić nową architekturę i status legacy dla motion-bridge.
- **Do potwierdzenia na HW**: logi XGO (łączność, debounce), watchdog/deadman i E‑Stop w `motion-executor` oraz pełen przebieg scenariuszy S5/S8/S9 (Etap 4 – walidacja na robocie).

## Kiedy uznać etap za zakończony
- `sensor-reader.service` i `motion-executor.service` działają poprawnie na robocie.
- `FeatureManager` oraz targety scenariuszy używają nowych usług.
- Stary `rider-motion-bridge.service` oznaczony jako legacy (opcjonalnie w `systemd/legacy/`).
- Dokumentacja (`PLAN_MIGRACJI_USLUG.md`, `SYSTEMD_SERVICES_MAPPING.md`) odzwierciedla nową architekturę.
