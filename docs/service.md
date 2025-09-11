##1. Analiza usług wystawianych w katalogu `services` repozytorium `Rider-Pi`:

### 1. `services/_status_api.py` – Status API (REST/SSE, WWW Dashboard)
Wystawia szereg endpointów HTTP (Flask), m.in.:
- `/healthz`, `/health` – sprawdzenie stanu żywotności
- `/state` – stan systemu
- `/sysinfo` – informacje systemowe
- `/metrics` – metryki systemowe
- `/events` – zdarzenia (SSE)
- `/camera/raw`, `/camera/proc`, `/camera/last`, `/camera/placeholder` – obrazy z kamery
- `/snapshots/<fname>` – dostęp do zrzutów
- `/svc` (GET) – lista usług systemd
- `/svc/<name>/status` (GET) – status konkretnej usługi
- `/svc/<name>` (POST) – akcje na usługach (np. restart)
- `/api/move`, `/api/stop`, `/api/preset`, `/api/voice`, `/api/cmd`, `/api/control_legacy` (POST) – komendy ruchu, presetów, głosowe
- `/control` (POST/OPTIONS) – proxy do mostka ruchu (8081)
- `/` – dashboard WWW

### 2. `services/api_server.py` – API Router
Pełni rolę routera HTTP, mapuje endpointy na moduły z `services.api_core.*`. Działa jako:
- Główny punkt wejścia REST, deleguje obsługę do podmodułów.
- Lekki proxy: przekazuje wywołania `/api/move`, `/api/stop`, `/api/control`, `/api/cmd` do web_motion_bridge (8081).
- Udostępnia statyczne pliki WWW (HTML/JS/CSS).
- Integruje podsystemy: dashboard, obsługa snapshotów, Vision API (blueprint na `/vision`).

### 3. `services/broker.py` – Broker ZMQ (XSUB↔XPUB)
- Usługa pośrednicząca (broker) dla komunikacji PUB/SUB za pomocą ZeroMQ.
- Otwiera porty:
  - XSUB (od publisherów): domyślnie `tcp://*:5555`
  - XPUB (dla subscriberów): domyślnie `tcp://*:5556`
- Zapewnia przekazywanie komunikatów pomiędzy komponentami systemu.

### 4. `services/last_frame_sink.py` – Sink klatki z kamery
- Monitoruje katalog z obrazami z kamery (`snapshots`).
- Kopiuje najnowszą klatkę do pliku `data/last_frame.jpg` (atomowo).
- Opcjonalnie publikuje heartbeat ZMQ (`camera.heartbeat`).

### 5. `services/motion_bridge.py` – Mostek ruchu (sterowanie hardware)
- Nasłuchuje na ZMQ na tematy: `cmd.move`, `cmd.stop`, stare komendy `cmd.motion.*`, `motion.cmd`.
- Mapuje komendy na fizyczne ruchy robota XGO.
- Implementuje zabezpieczenia: deadman/auto-stop, debounce, limity czasowe.
- Publikuje stan i zdarzenia na ZMQ (`motion.bridge.event`, `devices.xgo`).

### 6. `services/motion_cmd_shim.py` – Tłumacz komend ruchu (shim)
- SUBskrybuje `motion.cmd` (dashboard legacy)
- Tłumaczy i publikuje na `cmd.move` (nowy format dla motion_bridge)
- Umożliwia kompatybilność starego dashboardu z nowym mostkiem ruchu.

### 7. `services/web_motion_bridge.py` – HTTP→ZMQ bridge do ruchu
- Wystawia HTTP endpointy:
  - GET `/api/move`, `/api/stop`, `/api/balance`, `/api/height`
  - POST `/control` (kompatybilne z dashboardem)
  - GET `/healthz`
- Tłumaczy zapytania HTTP na komunikaty ZMQ (`cmd.move`, `cmd.stop`).
- Umożliwia sterowanie robotem przez WWW/dashboard.

## Wystawiane usługi (`services`):

- **REST API** – status systemu, kontrola ruchu, przeglądanie usług systemd, dashboard WWW.
- **Broker ZMQ** – komunikacja PUB/SUB (ZeroMQ, porty 5555/5556).
- **Mostek HTTP↔ZMQ dla ruchu** – sterowanie robotem przez HTTP/WWW.
- **Serwis synchronizacji obrazu z kamery** – aktualizacja pliku z ostatnią klatką.
- **Translacja komend legacy** – kompatybilność starszych paneli/dashów.
- **Zarządzanie usługami systemd** – status, restart, akcje na usługach.

---

##2.  Jak dodać i zarejestrować nową usługę systemową?

### 1. Stwórz plik unit `.service`
- Plik opisujący Twoją usługę (np. `my-feature.service`) umieść w katalogu `ops/systemd/` w repozytorium.

### 2. Dodaj usługę do listy dozwolonych (whitelist)
- Otwórz plik `ops/service_ctl.sh`.
- W tablicy `ALLOWED_EXACT` umieść dokładną nazwę Twojej usługi, np.:
  ```bash
  ALLOWED_EXACT=(
    "rider-broker.service"
    "rider-api.service"
    "rider-motion-bridge.service"
    "my-feature.service"         # ← DODAJ SWÓJ SERWIS TUTAJ!
  )
  ```
- To jest kluczowe: tylko usługi z tej listy mogą być zarządzane przez dashboard/API/skrypty.

### 3. Zarejestruj usługę w systemie
- Użyj skryptu synchronizującego:
  ```bash
  ./ops/systemd_sync.sh
  ```
  - Skrypt przenosi pliki `.service` do `/etc/systemd/system/` i wykonuje `systemctl daemon-reload`.
