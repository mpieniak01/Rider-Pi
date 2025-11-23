# Scenariusze biznesowe Rider-Pi

Dokument porządkuje funkcje robota widoczne w panelach sterowania. Na tej podstawie budujemy katalog scenariuszy biznesowych, który później zamapujemy na konkretne jednostki systemd (nowe lub uproszczone). Wszystkie opisy są po polsku, gotowe do użycia w dokumentacji użytkowej.  
**Powiązane**: plan wdrożenia scenariuszy znajduje się w [Plan migracji usług](PLAN_MIGRACJI_USLUG.md).

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

## Definicja celu dla usług

Aby zredukować chaos w katalogu usług, każda jednostka systemd powinna mieć z góry określony cel (biznesowy lub techniczny). Rekomendowane kryteria:

- **Cel biznesowy** – opisuje, jakie doświadczenie użytkownika/usługę końcową zapewnia dana jednostka (np. „podgląd kamery dla operatora”, „śledzenie twarzy”, „rekonesans mapujący”). Usługa jest częścią jednego lub więcej scenariuszy z listy S0–S11.
- **Cel techniczny** – w sytuacjach pomocniczych (np. mostki, integracje) definiujemy, jakie zadanie techniczne realizuje moduł (np. „serial → bus”, „generowanie splash screen”). Jeśli usługa nie wnosi nowej funkcji biznesowej, musi być jasno oznaczona jako komponent infrastruktury i opisana w dokumentacji.
- **Jedna rola = jedna usługa** – każda jednostka odpowiada za pojedynczą funkcję. Tryby pracy (raw/edge/ssd) powinny być parametrami, a nie osobnymi unitami. Dzięki temu łatwiej przyporządkować usługę do scenariusza.
- **Mapa zależności** – przy każdej usłudze określamy, jakie zasoby fizyczne i warstwy przetwarzania wykorzystuje (kamera, LCD, mikrofon, ML). Informacja trafia do tabeli zależności i do dokumentacji systemd.

Jeśli usługa nie spełnia powyższych kryteriów (brak scenariusza lub celu technicznego), powinna trafić do katalogu „legacy/dev” albo być scalona z inną.

### Zakresy dla usług wideo (capture → processing → output)

Aby uniknąć dublowania pracy i kolizji o kamerę, dzielimy cały pipeline obrazu na logiczne warstwy:

1. **Capture (surowe dane)**  
   - Jedna usługa odpowiada za pobieranie klatek z kamery. Dostępne powinny być dwa tryby:  
     • klatki (snapshoty do `snapshots/` + feed po ZMQ/IPC)  
     • streaming (ciągły strumień do offload/web).  
   - Usługa capture *nie wykonuje* przetwarzania wysokiego poziomu – jedynie dostarcza dane.

2. **Przetwarzanie na Rider-Pi (frame-based)**  
   - Ze względu na wydajność przetwarzamy tylko klatki (bez własnego otwierania /dev/video). Każdy moduł otrzymuje klatki z capture i wykonuje własne algorytmy.  
   - Przykłady modułów:  
     • Follow-Me tracker (MediaPipe)  
     • Wykrywanie przeszkód / obiektów  
     • Mapper / SLAM  
   - Moduły mają jasno zdefiniowane wyjścia (topic, plik, mapa) i nie próbują ponownie generować snapshotów.

3. **Wyniki / prezentacja**  
   - Dane z modułów przetwarzania trafiają do UI/LCD/APIs. Może to być:  
     • status (np. obstacles → badge w panelu)  
     • mapy/koordinate → navigator  
     • streaming/outbound feed (np. offload do PC).  
   - Punkt ten nie wchodzi ponownie w capture – tylko udostępnia dane kolejnym warstwom.

Zależność między usługami: capture dostarcza dane; moduły przetwarzania korzystają z capture; funkcje (S3, S4, S8, S9) korzystają z wyników modułów. W ten sposób unikamy sytuacji, w której każda usługa otwiera kamerę i generuje własne kopie danych.

### Przepływ decyzji (dane → przetwarzanie → sterowanie)

W wielu scenariuszach (zwłaszcza Follow Me, Rekonesans, Nawigacja) potrzebne jest pokazanie, co z czego wynika i który komponent podejmuje decyzję. Przykładowy łańcuch:

0. **Wejścia fizyczne** – kamera dostarcza obraz, IMU i enkodery dają odczyty pozycji; wszystkie trafiają do warstwy capture/sensorów.
1. **Capture** generuje klatki, udostępniając je dalszym modułom.
2. **Moduł przetwarzający** (np. `rider-tracker`) wykrywa obiekt i publikuje dane `pose/target`.
3. **Moduł decyzji** (np. `rider-tracking-controller`) wykorzystuje dane z przetwarzania + odczyty IMU i decyduje o następnym ruchu.
4. **Mostek ruchu (`rider-motion-bridge`)** przyjmuje decyzję i wysyła ją do urządzenia.
5. **Monitoring**: wyniki (np. „aktywne śledzenie”, „wykryto przeszkodę”) trafiają do API/UI.

Ten wzór można przenieść na inne procesy:

- **Obstacle → Navigator**: `rider-obstacle` dostarcza mapę przeszkód, `rider-navigator` aktualizuje trasę i steruje ruchem.
- **SLAM → Navigator**: `rider-mapper` dostarcza mapę, `rider-navigator` definiuje punkty A/B.
- **Follow Me**: tracker dostarcza pozycję celu, controller przelicza na komendy, motion-bridge wykonuje.  

Każdy moduł w tym łańcuchu działa na dobrze zdefiniowanym interfejsie (np. ZMQ topics, pliki map). Dzięki temu inne funkcje mogą korzystać z tych samych danych bez powielania pracy.

| Krok | Opis | Przykładowe jednostki / moduły |
|------|------|--------------------------------|
| 0 | Wejścia fizyczne (kamera, IMU, enkodery) | Kamera hw, IMU w XGO, odczyty wheel |
| 1 | Capture generuje klatki / sygnały | rider-camera, moduły sensorowe |
| 2 | Przetwarzanie klatek (ML / wizja) | rider-tracker, rider-obstacle, rider-vision |
| 3 | Podejmowanie decyzji na podstawie wyników + stanu | rider-tracking-controller, rider-navigator |
| 4 | Sterowanie ruchem | rider-motion-bridge, warstwa XGO |
| 5 | Monitoring i prezentacja wyników | API/UI, badge w panelu, mapy |

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

## Zależność usług od zasobów fizycznych (AS-IS)

| Usługa / komponent | Kamera | LCD | Mikrofon | Głośnik | Odczyt stanu urządzenia (IMU / sensory) | Sterowanie ruchem | Warstwa przetwarzania |
|--------------------|:------:|:---:|:--------:|:-------:|:---------------------------------------:|:-----------------:|----------------------|
| rider-camera / rider-cam-preview / rider-edge-preview / rider-ssd-preview | ✔ | ✔ | – | – | – | – | surowe → opcjonalnie filtrowane (OpenCV) |
| rider-tracker | ✔ | – | – | – | – | – | MediaPipe / ML |
| rider-tracking-controller | – | – | – | – | ✔ (IMU/odometry) | ✔ | logika PID / bezpośrednie |
| rider-motion-bridge | – | – | – | – | ✔ (monitoring urządzenia) | ✔ | bezpośrednie / mapowanie JSON → XGO |
| rider-obstacle | ✔ | – | – | – | – | – | ML (detekcja przeszkód) |
| rider-vision (dispatcher) | ✔ | – | – | – | – | – | agregacja ML, filtry wizji |
| rider-vision-offload | ✔ | – | – | – | – | – | streaming/raw + offload |
| rider-odometry | – | – | – | – | ✔ | – | przetwarzanie odometryczne |
| rider-mapper | ✔ | – | – | – | ✔ | – | SLAM / mapowanie |
| rider-navigator | – | – | – | – | ✔ | ✔ | planowanie trasy |
| rider-voice | – | – | ✔ | ✔* | – | – | ASR/NLU/TTS (lokalnie/chmura) |
| rider-voice-web | – | – | ✔* | ✔* | – | – | warstwa HTTP/websocket |
| rider-google-bridge | – | – | – | – | – | – | integracja API |
| rider-boot-splash / rider-post-splash | – | ✔ | – | – | – | – | proste grafiki / status |
| rider-web-bridge / rider-api / rider-broker | – | – | – | – | – | – (pośrednio) | JSON/REST → ZMQ |

\* w zależności od konfiguracji providerów (np. lokalny TTS vs urządzenie zewnętrzne).


### Jak App Logic komunikuje się z resztą stosu (AS-IS)

| Warstwa / kanał | Cel | Przykłady |
|-----------------|-----|-----------|
| Systemd / targety | Uruchamianie i zatrzymywanie scenariuszy (S0–S11) | `systemctl start rider-followme.target`, `feature_manager.set_feature()` |
| Command bus (ZMQ) | Przekazywanie komend runtime, subskrypcja zdarzeń | publikacje do motion bridge, nasłuchiwanie telemetrycznych topiców |
| API / UI / CLI | Interfejs dla operatora i integracji | `/api/logic/feature`, panel `/web/control.html`, `robot_ctl` |
| Monitoring / stan | Udostępnianie obecnego scenariusza, statusu usług | `/svc`, `/run/rider/state`, tabelka usług, badge w UI |

Takie podejście sprawia, że App Logic jest „centralnym mózgiem” – spina interfejsy użytkownika, warstwę komunikacyjną i usługową, ale nie miesza się w szczegóły przetwarzania danych czy kontroli hardware.

## Zależność usług od zasobów fizycznych (TO-BE)

| Nazwa techniczna | Opis usługi | Kamera | LCD | Mikrofon | Głośnik | Odczyt stanu urządzenia | Sterowanie ruchem | Warstwa przetwarzania / rola |
|------------------|-------------|:------:|:---:|:--------:|:-------:|:------------------------:|:-----------------:|----------------------|
| `camera-capture` | Kontrola kamery, udostępnianie klatek | ✔ | – | – | – | – | – | sterownik hw, eksport klatek do busa |
| `lcd-renderer` | Renderowanie informacji na LCD | – | ✔ | – | – | – | – | render statusów/snapów na ekranie |
| `audio-input` | Obsługa mikrofonu (próbkowanie + publikacja) | – | – | ✔ | – | – | – | próbkowanie mikrofonu, publikacja audio |
| `audio-output` | Odtwarzanie audio / TTS | – | – | – | ✔ | – | – | przyjmowanie TTS i odtwarzanie |
| `sensor-reader` | Zbieranie danych IMU/odometrii | – | – | – | – | ✔ | – | agregacja IMU/odometrii |
| `motion-executor` | Wysyłanie komend ruchu do robota | – | – | – | – | – | ✔ | tłumaczenie komend na XGO |
| `frame-distributor` | Bufor i dystrybucja klatek do ML | – | – | – | – | – | – | bufor klatek, udostępnianie modułom ML |
| `stream-publisher` | Generowanie strumienia HTTP/offload | – | – | – | – | – | – | generowanie streamu HTTP/offload z feedu |
| `tracker-ml` | Moduł śledzenia obiektów (ML) | – | – | – | – | – | – | MediaPipe / ML na klatkach |
| `obstacle-detector` | Detekcja przeszkód / semantyka | – | – | – | – | – | – | detekcja kolizji / semantyka sceny |
| `slam-mapper` | Budowanie mapy (SLAM) | – | – | – | – | – | – | budowa mapy z klatek + IMU |
| `navigator` | Planowanie trasy na mapie | – | – | – | – | – | – | planowanie trasy na mapie |
| `voice-intelligence` | ASR/NLU/TTS korzystające z audio serwisów | – | – | – | – | – | – | przetwarzanie głosu |
| `app-logic-core`* | Zarządzanie scenariuszami i usługami | – | – | – | – | – | – | orkiestracja scenariuszy (steruje innymi usługami) |

#### Komponenty komunikacyjne (wspólne dla wszystkich scenariuszy)

| Nazwa techniczna | Opis usługi | Kamera | LCD | Mikrofon | Głośnik | Odczyt stanu | Sterowanie ruchem | Warstwa / rola |
|------------------|-------------|:------:|:---:|:--------:|:-------:|:------------:|:-----------------:|----------------|
| `api-gateway`** | Backend HTTP/REST, zarządzanie stanem (/svc, /api) | – | – | – | – | – | – | warstwa API |
| `bus-broker`** | Kolejka komunikatów (ZMQ pub/sub) | – | – | – | – | – | – | dystrybucja zdarzeń |
| `web-bridge`** | Mostek UI ↔ bus (HTTP→ZMQ) | – | – | – | – | – | – | obsługa panelu sterowania |
| `comm-broker`** | Broker usług komunikacyjnych | – | – | – | – | – | – | centralne przekazywanie komunikatów |

\* App Logic Core działa jako meta-usługa: nie posiada własnych zasobów fizycznych, ale zarządza start/stop innych komponentów według scenariuszy biznesowych (S0–S11). Może udostępniać API/CLI/daemon, które wysyła polecenia do systemd lub dedykowanego command busa.
\** Komponenty techniczne (API, kolejki, web bridge) odpowiadają za komunikację, stan i ekspozycję interfejsów – nie korzystają z zasobów fizycznych, ale są wymagane dla wszystkich scenariuszy.
