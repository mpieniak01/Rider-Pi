# Checklist wdrożenia scenariuszy i pokrycia zasobów (TO‑BE)

## 1. Scenariusze i targety (zgodnie z planem migracji)
- [x] **S0/S1** – baza + sterowanie manualne: `rider-core.target` (z `sensor-reader.service`, `motion-executor.service`).
- [x] **S3 Follow Me** – `rider-followme.target` (capture + frame-distributor + tracker + tracking-controller + motion).
- [x] **S4 Rekonesans** – `rider-recon.target` (capture + frame-distributor + vision/obstacle + odometry + mapper + navigator + motion).
- [x] **S5 Głos** – `rider-voice.target` (audio-input/output + rider-google-bridge).
- [x] **S8 Mapowanie** – `rider-mapbuild.target` (capture + frame-distributor + obstacle + odometry + mapper + motion).
- [x] **S9 Nawigacja** – `rider-navigate.target` (capture + frame-distributor + obstacle + odometry + mapper + navigator + motion).
- [ ] **S6/S7** – moduły wizji (tracker / obstacle) uruchamiane pojedynczymi unitami; brak dedykowanych targetów (nieplanowane w migracji).
- [ ] **S10/S11** – tryby providerów AI / dev działają na istniejących usługach; brak osobnych targetów (poza `rider-dev.target`).

## 2. Zmiany w API / zakresach danych
- [x] Aliasy API `/api/services/<name>`: `xgo`/`motion` kierują teraz na `motion-executor.service`, dodano aliasy `sensors`/`imu` → `sensor-reader.service`.
- [ ] Jeśli pojawią się nowe endpointy lub zmiany zakresów payloadów (np. nowe pola telemetrii z sensor-reader / motion-executor), dodać tutaj krótką notatkę i link do MR/commitu.

## 3. Pokrycie sekcji „Zależność usług od zasobów fizycznych (TO‑BE)” vs systemd
| Nazwa TO‑BE | Pokrywający unit/target systemd | Status/uwagi |
|-------------|---------------------------------|--------------|
| camera-capture | `camera-capture@.service` (raw/edge/ssd) | ✓ |
| lcd-renderer | `lcd-renderer.service` | ✓ |
| audio-input | `audio-input.target` (wants `rider-voice.service`) | ✓ |
| audio-output | `audio-output.target` (wants `rider-voice-web.service`) | ✓ |
| sensor-reader | `sensor-reader.service` | ✓ |
| motion-executor | `motion-executor.service` | ✓ |
| frame-distributor | `frame-distributor.service` | ✓ |
| stream-publisher | brak osobnego unitu; funkcję strumienia pełni `rider-vision-offload.service` (offload) lub API snapshot/stream | odstępstwo: nie utworzono dedykowanego unitu, bo offload/stream realizują istniejące moduły |
| tracker-ml | `rider-tracker.service` | ✓ |
| obstacle-detector | `rider-obstacle.service` | ✓ |
| slam-mapper | `rider-mapper.service` | ✓ |
| navigator | `rider-navigator.service` (w `rider-navigate.target`) | ✓ |
| voice-intelligence | `rider-voice.target` (grupuje voice/web/google-bridge) | ✓ |
| app-logic-core | komponent w `rider-api.service` (FeatureManager), brak osobnego unitu systemd | odstępstwo: to biblioteka/aplikacja w API, nie usługa systemd |

### Odstępstwa – wyjaśnienie
- **stream-publisher**: nie powstał osobny unit; strumień HTTP/offload obsługuje `rider-vision-offload.service` (PC offload) oraz endpointy API snapshot/stream. Osobna usługa nie była potrzebna w obecnej architekturze.
- **app-logic-core**: realizowane jako moduł w `rider-api.service`, więc brak osobnego unitu systemd; zgodne z planem przeniesienia logiki do API zamiast wydzielania nowej usługi.
- **S6/S7/S10/S11 targety**: plan migracji nie zakładał dedykowanych targetów – scenariusze dev/vision/AI korzystają z istniejących unitów. W razie potrzeby można dodać targety pomocnicze w osobnej iteracji.

## 4. Systemd/legacy – co zostaje, co usuwamy
**Katalog `systemd/legacy/`:**
- `rider-motion-bridge.service` – **zostaje tymczasowo** tylko do rollbacku; do usunięcia/maskowania po testach HW nowych usług (`sensor-reader`, `motion-executor`).
- `rider-cam-preview.service`, `rider-edge-preview.service`, `rider-ssd-preview.service` – legacy podglądy DEV; w produkcji niewłączane, można usunąć po potwierdzeniu stabilności `camera-capture@.service` + `frame-distributor`.
- `rider-face.service` – narzędzie DEV (render twarzy); zostaje w legacy dla S11/DEV, nie włączamy w targetach produkcyjnych.
- `rider-post-splash.service` – zastąpiony przez `lcd-renderer.service`; można usunąć po weryfikacji startu LCD renderer na robocie.

**Zasada:** w środowisku produkcyjnym włączamy tylko unity spoza `systemd/legacy/`. Po pozytywnych testach HW: zamaskować/usunąć `rider-motion-bridge.service` i podglądy preview; zostawić ewentualnie `rider-face.service` jako narzędzie deweloperskie.

## 5. Jednostki w `systemd/` (bieżące) – co zostaje po testach
- **Do utrzymania (produkcyjne/targety):** `rider-core.target`, `rider-followme.target`, `rider-recon.target`, `rider-voice.target`, `rider-mapbuild.target`, `rider-navigate.target`, `camera-capture@.service`, `frame-distributor.service`, `sensor-reader.service`, `motion-executor.service`, `rider-broker.service`, `rider-api.service`, `rider-web-bridge.service`, `rider-vision.service`, `rider-obstacle.service`, `rider-odometry.service`, `rider-mapper.service`, `rider-navigator.service`, `rider-tracker.service`, `rider-tracking-controller.service`, `rider-vision-offload.service`, `lcd-renderer.service`, `audio-input.target`, `audio-output.target`, `rider-google-bridge.service`, `wifi-unblock.service`.
- **DEV/tools (zostają jako pomocnicze, nie rozwijamy w produkcji):** `rider-dev.target`, `jupyter.service`, `rider-voice.service`/`rider-voice-web.service` gdy używane standalone, ewentualne offload/debug narzędzia.
- **Do usunięcia po testach (jeśli okaże się zbędne):** nic poza katalogiem `legacy`; jeśli po walidacji okaże się, że któryś z powyższych nie jest używany w scenariuszach (np. `rider-vision-offload.service` w środowisku bez offload), przenosimy go do `legacy` zamiast rozwijać dalej.

## 6. Autostart (boot) – które unity powinny startować z systemem
- **Minimalny boot:** `multi-user.target` + `rider-boot-splash.service` (oneshot) + `rider-core.target` (agreguje broker, API, web-bridge, sensor-reader, motion-executor, wifi-unblock).  
  - `rider-minimal.target` istnieje, ale jest równoważny bazie; po testach można go pozostawić wyłączonego i trzymać się `rider-core.target` jako jedynego bazowego.
- **Domyślne enable:** `rider-core.target`, `rider-boot-splash.service`, `lcd-renderer.service` (jeśli LCD).  
- **Opcjonalne scenariusze (start ręczny / App Logic):** `rider-followme.target`, `rider-recon.target`, `rider-voice.target`, `rider-mapbuild.target`, `rider-navigate.target`.
- **Co nie powinno mieć autostartu:** jednostki z `systemd/legacy/` oraz narzędzia DEV (`rider-dev.target`, `jupyter.service`, previewy). Trzymać je disabled, by uniknąć przypadkowego rozwijania/uruchamiania.

## 7. Testy i diagnostyka po migracji
- [x] Unit testy FeatureManager/API: `pytest tests/test_features_core.py tests/test_features_api.py` – zielone po zmianie na `motion-executor`/`sensor-reader`.
- [x] Skrypty diag/smoke dostosowane: `tests/reboot_safety_check.sh`, `tests/diag_snapshot.sh`, `tests/watch.sh`, `tests/web_control_diag.sh`, `tests/test_suite.sh`, `tests/count_rx_since.sh` używają nowych usług; brak referencji do `rider-motion-bridge`.
- [ ] Jeżeli dodane zostaną nowe testy scenariuszy (Etap 4), uzupełnić je o status nowych targetów (`rider-voice.target`, `rider-mapbuild.target`, `rider-navigate.target`).

## 8. Pliki uruchomieniowe / CLI po migracji
- `scripts/robot_ctl.py` – obsługuje start/stop/status scenariuszy przez FeatureManager (registry na targetach: followme/recon/voice/mapbuild/navigate). Brak odniesień do legacy.
- `scripts/sys_control.sh` – whitelist zawiera tylko aktualne unity (motion-executor, sensor-reader, camera-capture@, frame-distributor, targety S3/S4/S5/S8/S9, core). Legacy/out-of-scope jednostki są blokowane.
- `scripts/systemd-sync.sh` – allowlist tworzy symlinki tylko dla nowych usług/targetów; `systemd/legacy/*` pomijane.
