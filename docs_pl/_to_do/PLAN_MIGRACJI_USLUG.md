# Plan migracji usług do architektury scenariuszy (draft)

Dokument opisuje, jak w bezpieczny sposób przejść ze stanu obecnego (systemd z licznymi `rider-*.service`) do architektury docelowej opisanej w [Scenariuszach biznesowych](SCENARIUSZE_BIZNESOWE.md) (S0–S11 + warstwy capture/processing/output). Ewentualne przybliżenia wynikają z analizy bieżącej dokumentacji – plan ma być żywy i aktualizowany w trakcie prac.

## Etap 0 – Inwentaryzacja i szybkie porządki

- **1. Spis obecnych usług** – potwierdzić listę `rider-*.service`, `systemd/*.target`. Odnotować, które są aktywne na starcie i w jakich stanach (`systemctl list-unit-files`, `/svc`).
- **2. Zależności sprzętowe** – dla każdej usługi wskazać, jakiego fizycznego zasobu dotyka (kamera, mikrofon, LCD, XGO). Uzupełnić tabelę AS-IS w `SCENARIUSZE_BIZNESOWE.md` i oznaczyć konflikty (np. wiele usług otwierających kamerę).
- **3. Test regresyjny** – uruchomić wszystkie scenariusze z aktualnego panelu (Stan 0, Śledzenie, Rekonesans) i zebrać logi, by później porównać zachowanie.

## Etap 1 – Konsolidacja warstwy capture/output

- **1. Usługa `camera-capture`**  
  - Zastąpić `rider-cam-preview`, `rider-edge-preview`, `rider-ssd-preview` jednym unitem z parametrami `MODE=raw|edge|ssd`.  
  - Wystawić jednolity feed (np. ZMQ + snapshot) używany przez wszystkie moduły wizji.
- **2. Usługa `lcd-renderer`**  
  - Po uporządkowaniu `rider-boot-splash` i `rider-post-splash` pozostawić jedną usługę renderującą status (profil start/stop).
- **3. Warstwa audio** – analogicznie scalić `rider-voice` / `rider-voice-web` w logiczne moduły `audio-input` i `audio-output`.
- **4. Walidacja** – sprawdzić, że po konsolidacji panel/API nadal otrzymuje `snapshots`, a żadne scenariusze nie tracą podglądu.

## Etap 2 – Wydzielenie modułów przetwarzania (processing)

- **1. Tracker / obstacle / SLAM**  
  - Upewnić się, że `rider-tracker`, `rider-obstacle`, `rider-mapper` nie otwierają kamery samodzielnie – pobierają klatki z `camera-capture` / `frame-distributor`.  
  - Dostosować je do publikowania wyników w spójnych topicach (np. `tracking.pose`, `obstacle.map`, `slam.map`).
- **2. `frame-distributor` i `stream-publisher`**  
  - Stworzyć przejściowy moduł (może być skrypt), który buforuje klatki i udostępnia je modułom ML.  
  - Strumień HTTP/`/camera/stream` powinien korzystać z tego samego feedu.
- **3. Sensor reader i motion executor** – uporządkować `rider-motion-bridge`, by wyraźnie oddzielić wejścia (IMU/odometry) od wyjść (komendy XGO).
- **4. Testy** – uruchomić follow-me, rekonesans w trybie testowym, sprawdzić czy pipeline’y dzielą feed bez konfliktów (monitor `/tmp/camera.lock`).

## Etap 3 – Targety scenariuszy i App Logic Core

- **1. Targety**  
  - Zdefiniować systemd targety `rider-core.target`, `rider-followme.target`, `rider-recon.target`, `rider-mapbuild.target`, `rider-navigate.target`, `rider-voice.target`, itp.  
  - Każdy target uruchamia zdefiniowaną listę usług (capture + processing + komunikacja).
- **2. App Logic Core**  
  - Zapewnić jedną instancję (daemon lub wbudowany w API), która:  
    - trzyma rejestr scenariuszy S0–S11,  
    - steruje targetami (start/stop),  
    - publikuje stan (np. `/run/rider/state`).  
  - Aktualizować panel i CLI, by wywoływały App Logic zamiast `systemctl`.
- **3. Warstwa komunikacji** – potwierdzić, że API, bus, web bridge nadal działają po zmianach i że App Logic z nich korzysta (według tabeli „Jak App Logic…”).

## Etap 4 – Walidacja funkcjonalna i regresja

- **1. Test scenariuszy** – przejść przez każdy z S0–S11 (chociaż S8–S11 mogą być draft), potwierdzić że panel/CLI zachowuje się poprawnie.
- **2. Monitoring** – ujednolicić metryki i statusy w `/svc`, dodać informacje o aktualnym scenariuszu i statusie usług, aby UI mogło prezentować spójny obraz.
- **3. Dokumentacja** – odświeżyć `SYSTEMD_SERVICES_MAPPING.md`, `SCENARIUSZE_BIZNESOWE.md` (tablice TO-BE uzupełnić o rzeczywiste nazwy), dodać README do App Logic.

## Etap 5 – Deprecjacja starych usług

- **1. Legacy / dev** – przenieść przestarzałe unit’y (`rider-face`, edge preview itp.) do katalogu `systemd/legacy`.  
- **2. Wersja docelowa** – w mainline repo pozostawić tylko targety + usługi z tabeli TO-BE (plus komponenty komunikacyjne).  
- **3. Instrukcje migracji** – przygotować guide (np. `docs_pl/UPGRADE_SCENARIOS.md`) z opisem kroków, które operator ma wykonać (stop legacy, start targetów, test).

## Uwagi bezpieczeństwa

- Każdy etap powinien być wdrażany w oddzielnej gałęzi, z możliwością rollbacku (ostatnia działająca kombinacja usług).  
- Kluczowe moduły (motion, capture, App Logic) wymagają testów „na sucho” i dopiero potem z robotem.  
- Warto od razu planować włączenie walidacji w CI (np. testy `systemd-analyze verify`, smoke testy scenariuszy).

Plan jest szkicem – priorytety i szczegóły należy dopracować wspólnie z zespołem. Ważne, aby przenosić funkcje stopniowo, weryfikując każdy krok na realnym urządzeniu.
