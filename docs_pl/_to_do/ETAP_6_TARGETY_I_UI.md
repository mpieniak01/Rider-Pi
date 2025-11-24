# ETAP 6 – Konsolidacja targetów i UI sterowania

## Kontekst
- Gałąź `feat/app-logic-core-refactor` konsoliduje architekturę wokół targetów (`rider-core`, `rider-followme`, `rider-recon`, `rider-voice`, `rider-mapbuild`, `rider-navigate`) i nowego FeatureManagera (`services/core/features.py`).
- W systemd nadal utrzymujemy pojedyncze unity dla scenariuszy S6/S7 oraz trybów S10/S11. Panel sterowania (`web/control`) pokazuje więc kilkanaście usług zamiast kilku scenariuszy.
- Katalog `systemd/legacy/` trzyma narzędzia dev (`rider-face`, previewy, motion-bridge), jednak główny katalog nadal zawiera wpisy, które docelowo chcemy ukryć za targetami lub przenieść do legacy.

## Cel etapu
1. Zredukować listę ręcznie zarządzanych usług – operator ma widzieć scenariusze (targety), nie pojedyncze unity.
2. Uporządkować obsługę trybów dev/S10/S11 tak, aby były startowane i monitorowane tak samo jak reszta scenariuszy.
3. Dokończyć cleanup systemd (legacy i dokumentacja) i spiąć to z UI + CI.

## Zakres i zadania

### 1. Targety dla modułów wizji (S6/S7)
- [x] Stworzyć dwa dedykowane targety: `rider-tracker.target` (agregujący `rider-tracker.service`, `rider-tracking-controller.service`) oraz `rider-obstacle.target` (agregujący `rider-vision.service`, `rider-obstacle.service`, `rider-vision-offload.service`).
- [x] Uzupełnić FeatureManager (`services/core/features.py`) tak, by `s6_tracker_module` wskazywał na `rider-tracker.target`, a `s7_obstacle_module` na `rider-obstacle.target`.
- [x] Dostosować `scripts/systemd-sync.sh`, `scripts/sys_control.sh` oraz dokumentację (`docs_pl/SCENARIUSZE_BIZNESOWE.md`, `docs_pl/_to_do/CHECKLIST_WDROZENIA.md`), aby nowe targety były jedynym sposobem na start tych modułów (pojedyncze `*.service` zostają w głównym katalogu `systemd/`, ale nie są eksponowane w UI i nie trafiają na allowlistę CLI).
- [ ] Test: `pytest tests/test_features_core.py::TestFeatureManager` + smoke `make vision-status` (sprawdzenie grupy usług).

### 2. Target / profile dla S10/S11 (providerzy AI / tryb dev)
- [x] Zdefiniować `rider-ai-provider.target` obejmujący `rider-voice.service`, `rider-google-bridge.service`, `rider-vision-offload.service`.
- [x] Uporządkować `rider-dev.target`: włączyć tylko narzędzia DEV (Jupyter, preview) i jasno opisać zależności. `rider-face.service` zostaje w `systemd/legacy`, ale dodamy tryb `systemd-sync --with-dev`, który linkuje tę usługę (oraz inne dev-only) do `/etc/systemd/system` na żądanie i dokumentujemy to w `docs_pl/apps/face.md`.
- [x] Zaktualizować FeatureManager (`DEFAULT_REGISTRY` + aliasy) i dokumentację (`docs_pl/apps/face.md`, `docs_pl/_to_do/CHECKLIST_WDROZENIA.md`).
- [ ] Test manualny: `python services/api_server.py` + wywołania `/api/logic/feature/s10_ai_providers` i `/api/logic/feature/s11_dev_mode` (potwierdzenie statusu przez `/api/logic/features`).

### 3. UI panelu sterowania
- [x] W `web/control` (front + `/svc` backend) pokazywać status targetów (dane z `/api/logic/summary`) jako domyślny widok scenariuszy. Lista usług pozostaje w tej samej stronie w zwijanej sekcji „Diagnostyka”, tak aby operatorzy nadal mogli podejrzeć szczegóły.
- [x] Backend: dodać endpoint podsumowania (`/api/logic/summary`) w `services/api_server.py` + `services/api_core/app_logic`, który zwraca listę targetów, status (`active|inactive|partial`) i ewentualne ostrzeżenia.
- [x] Front-end: komponent scenariuszy z akcjami start/stop oraz osobna sekcja „System → Diagnostyka” z tabelą jednostek (read-only).
- [x] Dodać testy e2e: `tests/test_features_api.py` (sprawdzenie endpointu) oraz scenariuszowy `tests/test_suite.sh` (sekwencyjny start/stop S3–S11 z walidacją `/api/logic/summary`). Testy należy uruchamiać na PC/GitHubie (nie na Rider-Pi).

### 4. Cleanup systemd i dokumentacji
- [x] Nie przenosimy usług będących zależnościami targetów do `systemd/legacy/`. `scripts/systemd-sync.sh` ma flagę `--with-dev`, która opcjonalnie linkuje `rider-face`/preview; domyślnie środowiska produkcyjne widzą tylko główne unity.
- Uporządkować `docs/SYSTEMD_SERVICES_MAPPING.md` i `docs_pl/SYSTEMD_SERVICES_MAPPING.md`: sekcja ma prezentować tylko wspierane targety/usługi.
- `docs_pl/UPGRADE_SCENARIOS.md` → dopisać instrukcję migracji do nowego panelu i targetów dev.
- `docs_pl/_to_do/CHECKLIST_WDROZENIA.md` → checkboxy S6/S7 oraz S10/S11 przechodzą na `[x]` po spełnieniu powyższych punktów.

### 5. CI / diagnostyka
- [x] Uzupełnić `scripts/diag_systemd-smoke.sh` o test uruchamiania nowych targetów (systemd-analyze + walidacja zależności).
- [x] Dodać scenariusz App Logic do `tests/test_suite.sh`: dla każdego scenariusza (S3–S11) wywołujemy API (`/api/logic/feature/<name>` start/stop) i walidujemy przez `/api/logic/summary`, że status `active` zmienił się zgodnie z oczekiwaniami.
- [ ] Włączyć w PR #244 wymaganie zielonego wyniku dla nowego testu UI (`PYTHONPATH=. pytest tests/test_features_api.py` + `bash tests/test_suite.sh`) uruchamianego domyślnie w GitHub Actions/PC (nie na urządzeniu).

### 6. Kryteria zakończenia
1. Panel „Sterowanie” pokazuje wyłącznie scenariusze/targety.
2. W `systemctl list-unit-files | grep rider-` widzimy jedynie:
   - targety scenariuszy (`rider-core.target`, `rider-followme.target`, `rider-recon.target`, `rider-voice.target`, `rider-mapbuild.target`, `rider-navigate.target`, `rider-tracker.target`, `rider-obstacle.target`, `rider-ai-provider.target`, `rider-dev.target`),
   - wspólne usługi core (`camera-capture@.service`, `frame-distributor.service`, `sensor-reader.service`, `motion-executor.service`, `rider-broker.service`, `rider-api.service`, `rider-web-bridge.service`, `lcd-renderer.service`, `wifi-unblock.service`),
   - warstwy audio i integracje (`audio-input.target`, `audio-output.target`, `rider-voice.service`, `rider-voice-web.service`, `rider-google-bridge.service`) oraz ewentualne dev-only (`jupyter.service`, `rider-face.service` gdy włączone `--with-dev`).  
     Polecenie referencyjne:  
     ```bash
     systemctl list-unit-files --type=service --type=target \
       | grep -E '^(rider|camera-capture@|audio-)'
     ```
3. `docs_pl/_to_do/CHECKLIST_WDROZENIA.md` i `SCENARIUSZE_BIZNESOWE.md` mają aktualne statusy.
4. Smoke test `make test` + `bash scripts/diag_systemd-smoke.sh` + UI regression przechodzą na CI.
