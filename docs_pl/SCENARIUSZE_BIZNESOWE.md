# Scenariusze biznesowe Rider-Pi

Dokument porządkuje dotychczasowe funkcje robota ktore wizualizowane sa przez panele sterowainia. Na tej podstawie budujemy katalog scenariuszy biznesowych, który później zamapujemy na konkretne jednostki systemd (nowe lub uproszczone). Wszystkie opisy są w języku polskim, aby można je było bezpośrednio wykorzystać w dokumentacji użytkowej.

## Kontekst panelu sterowania

Panel sterowania jest obecnie głównym interfejsem operatora. Zawiera:

- **Podgląd kamery** – wybór źródła (CAM/EDGE), auto‑refresh, informacje o ostatniej klatce.
- **Sterowanie ruchem** – parametry impulsu, prędkości, przyciski W/S/A/D i przyciski ekranowe, natychmiastowy STOP.
- **Balans i wysokość** – szybkie przełączniki pozycji XGO.
- **Funkcje (features)** – blok „Stan 0”, „Śledzenie” (twarz/dłoń), „Rekonesans”. Każda funkcja wysyła żądania do `/api/logic/feature/<name>` i oczekuje, że zaplecze uruchomi odpowiednie usługi.
- **Kolejka ruchów i telemetria** – śledzenie aktualnych komend, stanu IMU, baterii.
- **Tabela usług (`/svc`)** – wizualizuje bieżące jednostki systemd, ale operator nie powinien zarządzać nimi ręcznie.

Wnioski z panelu:

1. Operator myśli w kategoriach „chcę zobaczyć obraz”, „chcę aby robot mnie śledził”, „chcę zrobić rekonesans”. To są scenariusze, nie pojedyncze usługi.
2. Manualne sterowanie zawsze ma działać; reszta jest dodatkiem.
3. UI nie powinno ujawniać złożoności systemd – potrzebujemy jasnego katalogu funkcji → usług.

## Scenariusze biznesowe

### S0 — Tryb bazowy „read only”
- **Cel**: uruchomić środowisko w trybie odczytu – UI, API, komunikacja z urządzeniem – bez możliwości wydawania komend ruchu.
- **Korzyści dla operatora**: szybkie sprawdzenie stanu robota i telemetrii, bez ryzyka przypadkowego ruchu (np. tryb demo, audyt).
- **Elementy panelu**: główny widok, wskaźniki stanu (bateria, IMU, logi), tabela usług.
- **Jednostki systemd**: `rider-api.service`, `rider-broker.service`, `rider-motion-bridge.service`, `rider-web-bridge.service`, `rider-boot-splash.service`, `wifi-unblock.service` (wspólny target `rider-core.target`).

### S1 — Sterowanie manualne
- **Cel**: aktywować przekazywanie komend ruchu (HTTP → motion bridge) i umożliwić operatorowi sterowanie W/S/A/D.
- **Korzyści**: kontrola pozycji robota, testy kalibracji, możliwość natychmiastowego STOP.
- **Elementy panelu**: sekcja „Sterowanie ruchem” (suwaki prędkości, przyciski, skróty klawiaturowe), przełączniki balansu/wysokości.
- **Jednostki systemd**: S0 + `rider-motion-bridge` w trybie read/write (niektóre środowiska DEV blokują to, dlatego scenariusz opisuje świadome włączenie).
- **Uwagi**: w trybie deweloperskim można odpiąć ruch – ta sekcja ma jasno mówić, kiedy komendy są przekazywane.

### S2 — Podgląd kamery
- **Cel**: operator chce zobaczyć obraz w UI (bez głębokiej analizy), np. do manualnego sterowania lub wstępnego ustawienia robota.
- **Korzyści**: szybko potwierdza pozycję robota, nie uruchamiając całego pipeline’u wizji.
- **Elementy panelu**: sekcja „Podgląd kamery” (CAM/EDGE), tryb auto-refresh.
- **Jednostki systemd**: `rider-camera.service` (planowana konsolidacja `rider-cam-preview`, `rider-edge-preview`, `rider-ssd-preview` → jeden ExecStart + tryb), współdzielony lock `/tmp/camera.lock`.
- **Uwagi**: scenariusz nie powinien startować detektorów ani sterowania śledzeniem; kończy się na przechwycie obrazu.

### S3 — Follow Me / Śledzenie osoby
- **Cel**: robot automatycznie podąża za twarzą lub dłonią operatora.
- **Korzyści**: demonstracje, prowadzenie robota bez ręcznego sterowania.
- **Elementy panelu**: sekcja „Śledzenie (twarz / dłoń)”, wybór trybu, przyciski Start/Stop.
- **Jednostki systemd**:
  - Wspólna kamera (`rider-camera.service` w trybie `tracking`).
  - `rider-tracker.service` (MediaPipe) lub jego nowszy odpowiednik.
  - `rider-tracking-controller.service` (sterowanie rotacją).
  - `rider-motion-bridge.service` (już aktywny w S0).
- **Uwagi**: FeatureManager musi dopilnować kolejności (kamera → tracker → controller) i blokady innych funkcji korzystających z tej samej kamery.

### S4 — Rekonesans / Patrol
- **Cel**: autonomiczny przejazd z omijaniem przeszkód, tworzeniem mapy i możliwością powrotu.
- **Korzyści**: mapowanie mieszkania, zdalne obchody, pokaz możliwości AI.
- **Elementy panelu**: sekcja „Rekonesans”, przycisk „return home”, monitoring kolejki ruchu.
- **Jednostki systemd**:
  - Wszystko z S2.
  - `rider-obstacle.service` (detekcja przeszkód).
  - `rider-odometry.service` (pozycja/wheel odometry).
  - `rider-mapper.service` (SLAM).
  - `rider-navigator.service` (planowanie i powroty).
- **Uwagi**: wymaga stabilnego podglądu kamery, ale niekoniecznie previewu w UI; FeatureManager powinien zadbać o dodatkowe guardy (bateria > X%, sygnał IMU OK).

### S5 — Komunikacja głosowa
- **Cel**: rozmawiać z robotem oraz wydawać mu komendy mówione (zamiana głosu na tekst, tekstu na komendę, tekstu na głos).
- **Korzyści**: scenariusze asystenta, tryby edukacyjne, sterowanie bez dotykania panelu.
- **Elementy panelu**: przełącznik „Sterowanie głosowe”, log rozpoznanych komend, badge „ASYSTENT”.
- **Jednostki systemd**: `rider-voice.service`, `rider-voice-web.service`, ewentualne mostki (np. `rider-google-bridge.service` lub lokalny back-end ASR/TTS).
- **Uwagi**: sam scenariusz skupia się na funkcjach głosowych, niezależnie od tego czy zasilane są chmurą czy lokalnie.

### S6 — Moduł śledzenia obiektów (Face/Hand Follow)
- **Cel**: uruchomić dedykowaną usługę śledzenia (face/hand) niezależnie od pełnych scenariuszy ruchu – np. tylko do prezentacji wizji.
- **Korzyści**: możliwość testowania i strojenia trackera bez uruchamiania wszystkich usług ruchu.
- **Elementy panelu**: sekcja „Śledzenie (twarz / dłoń)” w trybie eksperckim – start/stop trackera, wybór trybu.
- **Jednostki systemd**: `rider-tracker.service`, `rider-tracking-controller.service` (opcjonalnie w trybie dry-run), wspólna kamera.
- **Uwagi**: pipeline może działać samodzielnie (tylko publikacja telemetrii) lub być spięty z S3/S4 – ważne, aby UI pozwalało go włączyć osobno.

### S7 — Moduł wykrywania przeszkód / obiektów
- **Cel**: analiza obrazu w tle (obstacle detection, klasyfikacja obiektów) na potrzeby alertów i danych dla UI – niezależnie od scenariusza ruchu.
- **Korzyści**: wykrywanie przeszkód podczas postoju, powiadomienia w UI, wzbogacona telemetria.
- **Elementy panelu**: wskaźnik „Obstacle” (już istniejący badge), dodatkowy panel „Detekcje obiektów”.
- **Jednostki systemd**: `rider-obstacle.service`, `rider-vision.service`, opcjonalne previewy (edge/ssd) działające jako sensory; można startować bez `rider-motion-bridge`.
- **Uwagi**: moduł powinien mieć własny lifecycle (start/stop) i nie zależeć od S3/S4; wyniki trafiają do API niezależnie.

### S8 — Rekonesans mapujący
- **Cel**: samodzielne tworzenie mapy przestrzeni (SLAM) z kompletnej telemetrii (odometria, przeszkody, wizja).
- **Korzyści**: precyzyjne plany pomieszczeń, możliwość przyszłego wykorzystania mapy do nawigacji.
- **Elementy panelu**: tryb „Tworzenie mapy” (wizualizacja postępu, heatmapa obszarów, log alertów).
- **Jednostki systemd**: `rider-vision.service`, `rider-obstacle.service`, `rider-odometry.service`, `rider-mapper.service`, archiwizacja map (np. zapis do `/data/maps`), kamera w trybie SLAM.
- **Uwagi**: podczas mapowania robot może poruszać się według z góry ustalonego wzoru (np. spirala). Scenariusz kończy się zapisaniem mapy i powrotem do S1/S0.

### S9 — Nawigacja po mapie (A→B)
- **Cel**: wykonywanie poleceń „idź do punktu X” na podstawie wcześniej zapisanej mapy.
- **Korzyści**: powtarzalne misje, np. patrol korytarza, powrót do stacji ładowania, dostawy.
- **Elementy panelu**: widok mapy, wybór punktu docelowego, log trasy, status „return home”.
- **Jednostki systemd**: `rider-navigator.service`, `rider-motion-bridge.service`, `rider-odometry.service`, `rider-obstacle.service` (w trybie runtime), loader map.
- **Uwagi**: scenariusz zależy od S8 (mapy muszą istnieć). Wymaga guardów bezpieczeństwa (bateria, komunikacja).

### S10 — Wybór providerów AI (głos / wizja)
- **Cel**: przełączać konfigurację pomiędzy lokalnymi a chmurowymi modelami dla różnych pipeline’ów (ASR, TTS, NLU, detekcja przeszkód, klasyfikacja obiektów).
- **Korzyści**: kontrola kosztów i prywatności, możliwość miksowania (np. lokalny detector przeszkód + chmurowy opis sceny).
- **Elementy panelu**: sekcja „Provider AI” z listą modułów (Głos→Tekst, Tekst→Komenda, Tekst→Głos, Kamera→Detekcje) i możliwością wyboru `local / cloud / custom`.
- **Konfiguracja**: zmienne środowiskowe (np. `VOICE_ASR_PROVIDER`, `VISION_DETECTOR_PROVIDER`) i/lub osobne usługi (`rider-voice.service`, `rider-google-bridge.service`, `rider-vision-offload.service`, lokalne pipeline’y). Scenariusz nie uruchamia nowych usług – zmienia ustawienia tych istniejących i może wymagać restartu.
- **Uwagi**: spójny interfejs wyboru providerów powinien obejmować zarówno głos, jak i wizję; trzeba przewidzieć synchronizację przy przełączaniu (np. stop → zmiana → start).

### S11 — Tryb deweloperski / diagnostyka
- **Cel**: praca inżynierska, testowanie nowych modeli, korzystanie z JupyterLab.
- **Korzyści**: szybkie prototypowanie bez ingerencji w profile produkcyjne.
- **Elementy panelu**: brak (sterowanie CLI), ale w UI można dodać badge „DEV mode”.
- **Jednostki systemd**: `jupyter.service`, `rider-dev.target` (agreguje wszystkie narzędzia), eksperymentalne previewy (`rider-face.service`, `rider-edge-preview.service`, `rider-ssd-preview.service` itp.) świadomie oznaczone jako legacy.

## Kolejne kroki

1. **Walidacja listy** – wspólnie potwierdzić czy S0–S11 pokrywają wszystkie realne przypadki użycia panelu.
2. **Spójne nazewnictwo usług** – dla scenariuszy S1–S3 przygotować konkretne targety (`rider-camera.target`, `rider-followme.target`, `rider-recon.target`). Legacy i dev przenieść do osobnych folderów lub jasno oznaczyć.
3. **Aktualizacja FeatureManagera** – zamiast manualnego startu usług, przełączać targety scenariuszy. Dzięki temu UI/CLI wysyła polecenie „uruchom S2”, a reszta dzieje się automatycznie.
4. **Uproszczenie panelu** – w UI wyświetlać tylko te scenariusze, które są gotowe (np. S0–S6). Pozostałe (S7–S11) w sekcji „opcjonalne” z krótkim opisem i ostrzeżeniem.

Dokument będzie ewoluował, gdy dopracujemy rejestr usług. Wersja robocza (ta) ma pomóc w wspólnej dyskusji i „przepięciu” katalogu usług na realne korzyści biznesowe.

## Tabela podsumowująca scenariusze

| Scenariusz | Cel | Kluczowe jednostki systemd / komponenty |
|-----------|-----|------------------------------------------|
| **S0 – Tryb bazowy** | UI + komunikacja w trybie read only | • rider-api<br>• rider-broker<br>• rider-motion-bridge (readonly)<br>• rider-web-bridge<br>• rider-boot-splash<br>• wifi-unblock |
| **S1 – Sterowanie manualne** | Włączanie przekazywania komend ruchu | • S0<br>• rider-motion-bridge (write)<br>• kontrola XGO |
| **S2 – Podgląd kamery** | Uzyskanie obrazu bez przetwarzania | • rider-camera.service (raw/edge/ssd) |
| **S3 – Follow Me** | Śledzenie twarzy/dłoni z ruchem | • rider-camera (tracking)<br>• rider-tracker<br>• rider-tracking-controller<br>• rider-motion-bridge |
| **S4 – Rekonesans / Patrol** | Autonomiczny patrol z przeszkodami i mapą | • rider-obstacle<br>• rider-odometry<br>• rider-mapper<br>• rider-navigator |
| **S5 – Komunikacja głosowa** | Asystent/sterowanie głosem | • rider-voice<br>• rider-voice-web<br>• rider-google-bridge (opcjonalnie) |
| **S6 – Moduł śledzenia obiektów** | Samodzielny tracker do testów wizji | • rider-tracker<br>• rider-tracking-controller<br>• kamera |
| **S7 – Moduł wykrywania przeszkód** | Analiza obrazu w tle, alerty | • rider-obstacle<br>• rider-vision<br>• edge/ssd preview |
| **S8 – Rekonesans mapujący** | Tworzenie mapy (SLAM) | • rider-vision<br>• rider-obstacle<br>• rider-odometry<br>• rider-mapper |
| **S9 – Nawigacja po mapie** | Wykonywanie tras A→B | • rider-navigator<br>• rider-motion-bridge<br>• rider-odometry<br>• rider-obstacle<br>• loader map |
| **S10 – Wybór providerów AI** | Przełączanie lokal/chmura dla głosu i wizji | • rider-voice<br>• rider-google-bridge<br>• rider-vision-offload<br>• zmienne `VOICE_*`/`VISION_*` |
| **S11 – Tryb deweloperski** | Narzędzia, previewy dev | • jupyter.service<br>• rider-dev.target<br>• rider-face<br>• rider-edge-preview<br>• rider-ssd-preview |

## Zależność usług od zasobów fizycznych

| Usługa / komponent | Kamera | LCD | Mikrofon | Głośnik | Odczyt stanu urządzenia (IMU / sensory) | Sterowanie ruchem |
|--------------------|:------:|:---:|:--------:|:-------:|:---------------------------------------:|:-----------------:|
| rider-camera / rider-cam-preview / rider-edge-preview / rider-ssd-preview | ✔ | ✔ | – | – | – | – |
| rider-tracker | ✔ | – | – | – | – | – |
| rider-tracking-controller | – | – | – | – | ✔ (IMU/odometry) | ✔ |
| rider-motion-bridge | – | – | – | – | ✔ (monitoring urządzenia) | ✔ |
| rider-obstacle | ✔ | – | – | – | – | – |
| rider-vision (dispatcher) | ✔ | – | – | – | – | – |
| rider-vision-offload | ✔ | – | – | – | – | – |
| rider-odometry | – | – | – | – | ✔ | – |
| rider-mapper | ✔ | – | – | – | ✔ | – |
| rider-navigator | – | – | – | – | ✔ | ✔ |
| rider-voice | – | – | ✔ | ✔* | – | – |
| rider-voice-web | – | – | ✔* | ✔* | – | – |
| rider-google-bridge | – | – | – | – | – | – |
| rider-boot-splash / rider-post-splash | – | ✔ | – | – | – | – |
| rider-web-bridge / rider-api / rider-broker | – | – | – | – | – | – (pośrednio przekazują komendy) |

\* w zależności od konfiguracji providerów (np. lokalny TTS vs urządzenie zewnętrzne).
