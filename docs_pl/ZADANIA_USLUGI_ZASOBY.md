# Zadania, usługi i zasoby operatora

## Jeden katalog i kontrakt 2

`common/service_catalog.py` jest źródłem zadań S0–S11, jednostek, aliasów,
zdolności, zasobów i allowlisty skryptów. Import i odczyty API nie uruchamiają
procesów ani nie otwierają BUS/UART. Nie instalujemy dodatkowego daemona ani pakietu.

| Odczyt | Zawartość |
| --- | --- |
| `/api/logic/catalog` | Katalog jednostek, zadania, zdolności i konsumenci zasobów |
| `/api/logic/features` | Obserwowane członki, requested/state/ready oraz opcje każdego zadania |
| `/api/logic/summary` | Ten sam stan i liczniki; zachowuje obwiednię `summary` |
| `/api/logic/state` | Snapshot diagnostyczny; nigdy źródło zgody na ruch |
| `/svc`, `/svc/<alias>` | Jednostki: installed/load/active/sub/enabled/PID |
| `/api/services/graph` | Ten sam katalog i wspólny snapshot systemd |
| `/api/resource/<camera\|mic\|speaker\|lcd\|uart>` | Dokładne ścieżki, PID, właściciel systemd i konsumenci |

Obwiednia ma `contract_version: 2`, `catalog_version: 2`, `host: "pi"`,
`source: "pi"` i `observed_at` w sekundach UNIX. Wiersz usługi podaje źródło
`systemd`, wiek ostatniego odczytu i `stale`. `can_move` opisuje potencjalny
skutek usługi/zadania, a nie zgodę na wykonanie. `motion_owner` to `manual`,
`follow_me`, `navigation` albo null. Klient nieznanej wersji pozostaje odczytowy.

`requested` jest intencją bieżącego managera. `state` rozróżnia `starting`,
`ready`, `stopping`, `failed`, `partial` i `stopped`. `running` opisuje członków
systemd. `ready` wymaga requested, zainstalowanych i aktywnych członków oraz,
dla napędów, aktualnej zgody właściwego właściciela w wspólnej bramie bezpieczeństwa.
Napędy dodatkowo wymagają `available: true` i `stop_verified: true` dla jazdy/obrotu;
nieznana lub niezweryfikowana zdolność nie jest gotowością.
Sam aktywny target nie oznacza gotowości. Restart API nie odtwarza zadań ruchowych.
S0 jest bazowym konsumentem; S1 wymaga odrębnego przygotowania operatora.

## Minimalny zestaw i opcje

`POST /api/logic/feature/<name>` przyjmuje `enabled` jako bool i `options` jako
obiekt. Nieznane klucze/wartości są odrzucane. Powtórzony start jest idempotentny;
zmiana opcji aktywnego zadania wymaga wcześniejszego stop. Aliasów legacy nie usuwamy.

`option_schema` katalogu podaje pole, domyślną wartość i dopuszczalne wybory.
Start zadania ruchowego wymaga także oryginalnej koperty operatora na najwyższym
poziomie żądania: `generation`, `seq`, `source: "manual"`, `ts`, `ttl_ms` (1–500 ms)
i `request_id`. Serwer odrzuca nieaktualne lub powtórzone intenty, bez zmieniania
czasu ani generacji. Przed startem producenta zapisuje atomowo przyjętą generację
i identyfikator żądania w `/run/rider-motion/feature_state.json`, pod
`service_intents[unit]`. Nieudany zapis oznacza odmowę startu. Producent pozostaje
przypisany do tej generacji przez cały czas działania. Nowy ARM tego samego właściciela
nie uprawnia starego zadania; trzeba zakończyć poprzednie, potwierdzić STOP,
a następnie przygotować i uruchomić nowy plan.

| Zadanie | Opcje / skutek |
| --- | --- |
| S0 | API, BUS, executor i telemetria; brak uzbrojenia |
| S1 | Ta sama baza, osobne uprawnienie manualne; nie uzbraja napędów |
| S2 | Kamera RAW + feed |
| S3 | RAW/feed/tracker/kontroler; twarz albo dłoń, jeden właściciel |
| S4 | RAW/feed/wizja/przeszkody/odometria/mapa/nawigator; zgoda navigation |
| S5 | `domain: voice\|asr\|tts`, domyślnie voice; bez Google |
| S6 | RAW/feed/tracker; pasywny, bez kontrolera i bez aktuacji tracking.pose |
| S7 | `provider: local\|pc`; wizja/przeszkody lokalnie albo wyłącznie offload |
| S8 | Pasywne mapowanie; bez nawigatora |
| S9 | Zestaw mapy + nawigator; zgoda navigation |
| S10 | `domain: text\|voice\|asr\|tts\|vision\|google`; domyślnie text z workerem HTTP tylko dla chat |
| S11 | `tool: edge\|ssd\|raw`, domyślnie edge; dokładnie jedno narzędzie, bez GUI/Jupyter |

Opcjonalne targety są znacznikami zadań. Ich start przez `systemctl` nie wykonuje
scenariusza; manager uruchamia jawnych członków katalogu. Kamera i feed mogą być
współdzielone. Offload korzysta z istniejącego feedu/pliku, bez awaryjnego otwierania
drugiej kamery. Jupyter pozostaje wyłącznie narzędziem ręcznym.

## Własność i zakończenie

Działania zadania, administracji i recovery korzystają z jednej blokady.
Manager uruchamia tylko różnicę wymaganych usług. Stop zwalnia wyłącznie jednostki
uruchomione przez managera, których nie potrzebuje baza ani inny konsument.
Jednostki zastane po uruchomieniu mają konsumenta `external`; nie są automatycznie
zatrzymywane. Katalog i wykryty proces są widoczne, więc operator może jawnie je
zakończyć po sprawdzeniu skutków.

Każdy zestaw dziedziczy odczytową bazę; start executora tworzy DISARMED i nie uzbraja napędów.
Start zatrzymuje się przy pierwszym błędzie i wycofuje własne nowe jednostki.
Niepełny rollback jest `partial`; ponowny stop może dokończyć zwalnianie.
Konflikt RAW/EDGE/SSD albo dwóch właścicieli sterowania daje odmowę, bez zatrzymania
innego zadania. Administracja nie może zatrzymać/restartować używanego zasobu.
Enable opcjonalnych/dev/manual usług jest zabronione; autostart pozostaje osobną decyzją.

Zakończenie autonomii najpierw odwołuje zgodę i czeka na potwierdzony STOP wspólnej
bramy. Brak ACK/timeout pozostawia zasoby i jawny błąd `stop_unconfirmed`.
Start/restart nie uzbraja napędów. Patrz [bezpieczeństwo](apps/safety.md).
Automatyczne testy korzystają z atrap; fizyczna próba napędów jest wyłącznie ręczna,
po wyraźnej zgodzie operatora dla konkretnego planu.

## Diagnostyka i recovery

Diagnostyka nie inicjalizuje SDK. UART jest odrębnym zasobem jednego executora;
sensor-reader korzysta z BUS. Kamera obejmuje tylko `/dev/video*`; SPI/framebuffer
należy do LCD. Brak urządzenia to `unavailable`, błąd odczytu to `unknown`, a `free`
w obu przypadkach jest null. Nie zakładamy wolnego urządzenia przy braku danych.

Najpierw zakończ właściciela zadania. `release` nie zabija procesów domyślnie.
Ręczne recovery wymaga `force: true`, `operator_consent: true` i dokładnych obecnie
obserwowanych PID. Odpowiedź pokazuje właścicieli, konsumentów i skutki. SIGTERM
dotyczy wyłącznie tych PID; nie ma automatycznego SIGKILL/restartu. UART, LCD i baza
są chronione. Samo oglądanie urządzenia nie daje zgody na recovery ani na ruch.

Strażnik bezczynności LCD w API obserwuje właścicieli i pokazuje wskazówkę dla
operatora. Nigdy nie zwalnia zasobów LCD automatycznie. Błąd inventory pozostawia
zasilanie i prezentowanie nieznane (`on: null`); wolny deskryptor SPI nie dowodzi,
że ekran jest ciemny. Rozruch, polityka renderowania i orientacja fizyczna pozostają
bez zmian.

## Odczyty i migracja instalacji

Wspólny snapshot używa jednego `systemctl show` dla katalogu, TTL 0,75 s i blokady
odświeżania. Mutacja unieważnia cache. Awaria zachowuje wiek danych, oznacza stale
i odbiera gotowość. Jest to ograniczenie liczby odczytów, nie pomiar oszczędności baterii.

`scripts/systemd-sync.sh` domyślnie wyświetla **plan bez zmian**. Plan wykazuje też
brakujące S6/S7/S10; plik w repo nie znaczy, że unit jest zainstalowany na urządzeniu.
Po odczytaniu stanu instalacji i sprawdzeniu planu operator może wykonać:

```bash
./scripts/systemd-sync.sh
sudo ./scripts/systemd-sync.sh --apply
# osobna decyzja o jednym źródle autostartu, bez start/stop procesów:
sudo ./scripts/systemd-sync.sh --apply --consolidate-boot
# ścieżka kopii wypisana przez apply:
sudo ./scripts/systemd-sync.sh --rollback /etc/systemd/system/_rider_catalog_<znacznik>
```

Apply linkuje wyłącznie katalog, zapisuje backup/manifest i robi daemon-reload.
Nie usuwa cudzych unitów/drop-inów, nie ustawia default target, nie zmienia sieci,
SSH ani parametrów LCD/boot i nie używa start/stop/restart/`--now`/reboot.
`--with-dev` jest akceptowany dla kompatybilności, ale nie instaluje legacy.
Oddzielne consolidate-boot ustawia minimal/splash/LCD/Wi-Fi jako źródła autostartu
i wyłącza redundantne enabled oraz opcjonalne zadania. Samych procesów nie zatrzymuje.
Rollback odmawia nadpisania unitów zmienionych po migracji. Migrację unitów wykonuje
się osobno od zwykłego podglądu aplikacji opisanym w [wdrożeniu](WDROZENIE.md).


## Potwierdzenie producenta i wymagania profilu

Follow i nawigacja zapisują heartbeat pojedynczego procesu obok dziennika intencji:
`rider-tracking-controller.service.json` lub `rider-navigator.service.json`.
Gotowość wymaga świeżego `observed_at` (maksymalnie 3 s), `accepted: true`,
`active: true` oraz dokładnej przyjętej pary `generation/request_id`.
Oczekiwanie na cel trackera może być gotowym zadaniem, bez fizycznego ruchu.
Odpowiedź startu może mieć sukces i `state: starting`; start procesu nie jest ACK
producenta. Brak potwierdzenia pozostaje niedostępnością, a po oknie startowym
stanem `partial`. Nowa generacja tego samego właściciela nie akceptuje starego
żądania. Navigator przyjmuje dziennik jednokrotnie; manager nie wysyła sztucznego
HTTP start ani nie odświeża czasu koperty operatora.

ASR i TTS współdzielą istniejący proces `rider-voice-web.service` i port 8092.
ASR importuje wyłącznie Vosk; TTS wyłącznie Piper. Domeny są sumą bieżących
konsumentów zadania/administracji; ostatni stop domeny czyści cache jej modelu,
a ostatni konsument zwalnia worker. Heartbeat domen pokazuje faktyczną dostępność
importu/modelu i PID. Zadanie jest gotowe wyłącznie dla żądanych domen.
Pełne `voice` jawnie dodaje CLI słuchacza oraz chat; worker startuje pierwszy.
Źródłowe `VOICE_WEB_LLM_PROVIDER=stub` oznacza niedostępny pełny dialog, ale nie
blokuje samodzielnego ASR/TTS. Start nie instaluje pakietów ani nie pobiera modeli.
Worker używa wskazanej konfiguracji lokalnego głosu, odmawia override chmurowego
TTS i nie uruchamia login shell w celu pobierania niepowiązanych poświadczeń.

Profil `text` uruchamia tylko istniejący worker HTTP z domeną chat. Wymaga skonfigurowanego wykonywalnego lokalnego backendu i jego modelu; źródłowy `stub` jest jawnie niedostępny. Nie importuje ASR/TTS ani nie zajmuje mikrofonu/głośnika. `/api/chat/send` wybiera ten worker według świeżego heartbeat i pasującego PID, gdy nie ustawiono jawnego `CHAT_REMOTE_URL`. Legacy echo nigdy nie stanowi potwierdzenia gotowości AI.

Endpoint wybranego workera jest trasą HTTP na tym samym hoście. Producent i konsument wymagają dosłownego adresu pętli lokalnej, jawnego poprawnego portu oraz stałej ścieżki `/api/chat`; adres nasłuchu wildcard jest mapowany na loopback. Błędny bind publikuje niedostępną domenę chat z kodem `chat_worker_endpoint_requires_loopback_bind`, bez endpointu. Klient wewnętrzny pomija proxy ze środowiska i odrzuca przekierowania. Jawny `CHAT_REMOTE_URL` zachowuje osobny transport skonfigurowanego backendu.

Gotowość ASR/TTS wymaga rzeczywistego skonstruowania i zbuforowania wyłącznie wybranego modelu (`model_loaded: true`), a nie samego importu i obecności plików. Uszkodzony model daje `*_model_load_failed`; ta walidacja nie otwiera urządzenia audio.

`runtime_modules` opisuje wymagane importy jednostek katalogu. Preflight bada
tylko wybrany profil i zwraca `runtime_dependencies_missing` przed startem.
Worker głosu dodatkowo sprawdza własne backendy/modele w środowisku systemd;
wykrycie pakietu w interpreterze API nie dowodzi zgodności modelu lub ABI.
Narzędzia WSL i opcjonalne ML pozostają poza bazą; patrz
[polityka środowisk](POLITYKA_SRODOWISK.md).

Blokada wątku API oraz ograniczona czasowo blokada pliku (`feature_state.lock`)
serializują mutacje i recovery także między procesami utrzymania.
Osobny CLI recovery czyta zapisanych konsumentów i aktualnych właścicieli.
Brak dostępu do blokady/dziennika jest błędem, nigdy zgodą na zwolnienie zasobu.
Mutacje unieważniają snapshot systemd przed i po wykonaniu.
PATCH rejestru providerów nie jest startem/stopem zadania; minimalny zestaw domen
wybieraj przez opcje zadania z katalogu. Dawny provider state/health pozostaje
diagnostyką do czasu usunięcia globalnych skutków zmiany trybu.

## Stare wywołania podczas migracji panelu

Stary panel zachowuje odczyt i STOP. Przyciski startu zadań, powrotu do bazy i odzyskiwania zasobów są wyłączone do czasu panelu v2 z potwierdzeniem operatora i aktualnym odczytem PID. Stan unknown/unavailable jest widoczny wprost. Start zadania ruchowego przez CLI wymaga interaktywnego TTY operatora, wcześniejszego jawnego ARM z konkretnym planem i `--control-file`: ograniczonego pliku JSON z dokładną świeżą kopertą bieżącej akcji (generation, request_id, source, seq, ts, ttl_ms). Manager sprawdza ją bez zmian; CLI nie uzbraja, nie odnawia czasu i nie tworzy zgody. Plik przygotowuje się bezpośrednio przed wysłaniem; przeterminowane polecenie jest odrzucane. STOP nie wymaga pliku.
