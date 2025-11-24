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
- Stworzyć target `rider-vision-dev.target`, który agreguje `rider-tracker.service`, `rider-tracking-controller.service`, `rider-vision.service`, `rider-obstacle.service`, `rider-vision-offload.service`.
- Uzupełnić FeatureManager (`services/core/features.py`) tak, by `s6_tracker_module` i `s7_obstacle_module` wskazywały nowy target (lub dwa targety: `rider-tracker.target`, `rider-obstacle.target`).
- Dostosować `scripts/systemd-sync.sh`, `scripts/sys_control.sh` oraz dokumentację (`docs_pl/SCENARIUSZE_BIZNESOWE.md`, `docs_pl/_to_do/CHECKLIST_WDROZENIA.md`), aby nowe targety były jedynym sposobem na start tych modułów.
- Test: `pytest tests/test_features_core.py::TestFeatureManager` + smoke `make vision-status` (sprawdzenie grupy usług).

### 2. Target / profile dla S10/S11 (providerzy AI / tryb dev)
- Zdefiniować `rider-ai-provider.target` obejmujący `rider-voice.service`, `rider-google-bridge.service`, `rider-vision-offload.service`.
- Uporządkować `rider-dev.target`: upewnić się, że zawiera tylko narzędzia DEV (Jupyter, preview). `rider-face.service` zostaje w `systemd/legacy`, ale target powinien mieć opcję startu przez FeatureManagera (S11).
- Zaktualizować FeatureManager (`DEFAULT_REGISTRY` + aliasy) i opis w API (`docs_pl/apps/face.md`, `docs_pl/_to_do/CHECKLIST_WDROZENIA.md`).
- Test manualny: `python services/api_server.py` + wywołania `/api/logic/feature/s10_ai_providers` i `/api/logic/feature/s11_dev_mode`.

### 3. UI panelu sterowania
- W `web/control` (front + `/svc` backend) pokazywać status targetów (dane z `/api/logic/features`) zamiast listy usług. Wymaga:
  - Endpointu z podsumowaniem (status + aktywne scenariusze) – rozbudowa `services/api_server.py` oraz `services/api_core/app_logic`.
  - Aktualizacji komponentów front-end (lista scenariuszy + akcje start/stop).
  - Sekcja „System” zachowuje detale usług dla diagnostyki.
- Dodać testy e2e: `tests/test_features_api.py`, ewentualnie snapshot HTTP w `tests/watch.sh`.

### 4. Cleanup systemd i dokumentacji
- Po dodaniu targetów dev/AI przenieść zbędne unity do `systemd/legacy/` (np. pojedyncze `rider-tracker.service`, `rider-obstacle.service` zostaną zależnościami targetu, ale nie powinny być eksponowane osobno).
- Uporządkować `docs/SYSTEMD_SERVICES_MAPPING.md` i `docs_pl/SYSTEMD_SERVICES_MAPPING.md`: sekcja ma prezentować tylko wspierane targety/usługi.
- `docs_pl/UPGRADE_SCENARIOS.md` → dopisać instrukcję migracji do nowego panelu i targetów dev.
- `docs_pl/_to_do/CHECKLIST_WDROZENIA.md` → checkboxy S6/S7 oraz S10/S11 przechodzą na `[x]` po spełnieniu powyższych punktów.

### 5. CI / diagnostyka
- Uzupełnić `scripts/diag_systemd-smoke.sh` o test uruchamiania nowych targetów (systemd-analyze + walidacja zależności).
- Dodać scenariusz App Logic do `tests/test_suite.sh` – start kolejno S3, S4, S5, S6, S7, S8, S9, S10, S11 i potwierdzenie stanu.
- Włączyć w PR #244 wymaganie zielonego wyniku dla nowego testu UI (gdy tylko front będzie gotowy).

### 6. Kryteria zakończenia
1. Panel „Sterowanie” pokazuje wyłącznie scenariusze/targety.
2. W `systemctl list-unit-files | grep rider-` widzimy jedynie:
   - targety scenariuszy,
   - wspólne usługi core (capture, sensor, motion, voice, web-bridge, api),
   - oficjalne narzędzia (audio-input/output, google-bridge).
3. `docs_pl/_to_do/CHECKLIST_WDROZENIA.md` i `SCENARIUSZE_BIZNESOWE.md` mają aktualne statusy.
4. Smoke test `make test` + `bash scripts/diag_systemd-smoke.sh` + UI regression przechodzą na CI.
