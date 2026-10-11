# Kontrakty API Rider-Pi i Rider-PC

Specyfikacja interfejsów, danych i reguł zgodności obu paneli. Normatywne wymagania dotyczą koperty oraz pełnych danych domenowych; odczyt API nie potwierdza fizycznego zakończenia ruchu. Inwentarz deklaracji obejmuje też opcjonalne aplikacje i osobny port bramy — ich aktywność sprawdza się osobno.

## Docelowy format odpowiedzi HTTP

### Negocjacja i zgodność w czasie aktualizacji

Kanoniczny JSON jest żądany na **obecnych URL** nagłówkiem:

~~~http
Accept: application/vnd.rider.api+json;version=1
~~~

Serwer zwraca odpowiadający Content-Type oraz Vary: Accept. Nieobsługiwana jawna wersja daje 406. Żądania JSON nadal mogą używać Content-Type: application/json, aby nie zmieniać koperty komendy napędów.

Brak żądania kanonicznej wersji wybiera udokumentowaną projekcję legacy. Nie zwracamy równocześnie pełnego starego body i drugiej kopii w data. Negocjacja dotyczy wszystkich JSON-owych sukcesów i błędów, w tym 400/404/405/413/500/503. OPTIONS pozostaje poprawnym preflight 204.

Pi ogłasza api_envelope_versions:[1] i obsługiwane contract_id/version w addytywnych metadanych katalogu. Pi UI w PR #262 żąda koperty 1. PC w PR #141 robi to samo. Starszy PC nadal otrzymuje znany format. Nowy klient sprawdza Content-Type i meta, ponieważ starszy serwer może zignorować Accept. Nieznany format pozwala wyłącznie na rozpoznane odczyty; nie daje domyślnej zgody na mutację.

### Wspólna koperta

~~~json
{
  "meta": {
    "envelope_version": 1,
    "contract_id": "rider.telemetry",
    "contract_version": 1,
    "host": "pi",
    "source": "motion-executor",
    "observed_at": null,
    "generated_at": 1791663266.25,
    "server_time": 1791663266.25,
    "stale": false,
    "offline": false,
    "partial": true
  },
  "ok": true,
  "data": {},
  "error": null,
  "operation": null
}
~~~

To przykład struktury, nie odczyt robota.

| Pole | Typ i znaczenie |
| --- | --- |
| meta.envelope_version | int, obecnie 1; wersja wspólnego formatu |
| meta.contract_id | string z rejestru rodzin kontraktów |
| meta.contract_version | int; wersja danych danej rodziny, osobna od koperty |
| meta.host | pi albo pc; właściciel danych/projekcji |
| meta.source | jednoznaczny producent/projektor; nie oznacza gotowości |
| meta.observed_at | number UNIX w sekundach lub null; obserwacja całego jednorodnego snapshotu, nie czas odpowiedzi; przy agregacji kanałów o różnych czasach null |
| meta.generated_at, server_time | number UNIX w sekundach; czas tworzenia odpowiedzi i zegar serwera, bez odnawiania obserwacji |
| meta.stale, offline, partial | bool; jakość snapshotu/transportu, niezależna od jakości pojedynczych kanałów |
| meta.transport | opcjonalny obiekt receiver_host/received_at/attempted_at/upstream_status; PC dopisuje wyłącznie stan transportu |
| ok | bool; poprawne wykonanie odczytu albo przyjęcie operacji według poniższych zasad |
| data | obiekt rodziny kontraktu; cały wymagany payload, bez utraty rozszerzeń odpowiedzi |
| error | null albo obiekt code/message/retryable/details; stabilny kod, tekst pomocniczy |
| operation | null przy odczycie; przy mutacji jawny wynik operacji |

ok:true przy GET potwierdza uzyskanie projekcji. Nie potwierdza sprawności wszystkich urządzeń; partial i kanałowe błędy pozostają widoczne. Błąd pobrania źródła daje ok:false i właściwy HTTP, opcjonalnie data z oznaczonym starym snapshotem. Pusty lub niewłaściwy JSON nie jest sukcesem.

Podwójne przechowywanie danych jest zabronione. Zachowujemy rozszerzenia domenowego payloadu; serializer nie może milcząco odfiltrować pól nieobecnych w bieżącym UI. Obowiązkowe pola określa schemat i manifest, a dane dodatkowe pozostają dostępne dla istniejących odbiorców.

### Wynik operacji

operation zawiera request_id, action, target, status, confirmed, ack_kind, ack oraz actuation. Dla napędów zachowuje physical_completion:"unverified".

| Wynik | HTTP | operation.status | Znaczenie |
| --- | --- | --- | --- |
| Oczekiwanie na dowód/ACK | 202 | pending | Przyjęte żądanie, brak potwierdzenia docelowego skutku |
| Zastosowana konfiguracja | 200 | executed | Potwierdzona zmiana w danej domenie; persisted musi opisać zapis |
| Potwierdzone przyjęcie SDK | 200 | executed | ack_kind=sdk_accepted; fizyczny ruch/zatrzymanie nadal unverified |
| Odmowa walidacji | 400 | rejected | Nie wykonano operacji; konkretny kod błędu |
| Konflikt/stara generacja/niedostępna zdolność | 409 | rejected | Odmowa przed journalem/BUS/systemd |
| Niepełne zastosowanie lub rollback | zgodny z domeną 409/500/503 | partial | affected i remaining oraz przyczyna; bez ogólnego OK |
| Brak źródła/providera | 503 | rejected lub unknown | rejected tylko jeśli wiadomo, że operacji nie wykonano |
| Timeout transportu | 504 | unknown | Brak potwierdzenia; nie wolno twierdzić, że nie wykonano |
| Błędny protokół upstream | 502 | unknown lub rejected według dowodu | Błąd protokołu, nie zamiennik sukcesu Pi |

ack_kind rozróżnia configuration_persisted, systemd_observed, task_accepted, task_ready, sdk_accepted i inne jawnie opisane dowody domenowe. executed nie zastępuje stanu gotowości zadania ani wykonania fizycznego. pending/unknown nie uruchamia automatycznego ponowienia mutacji. Oryginalny request_id polecenia ruchu nie jest zastępowany identyfikatorem proxy.

Stabilne kody błędów obejmują invalid_request, unsupported_contract, source_unavailable, stale_source, conflict, capability_unavailable, upstream_protocol_error, upstream_timeout, persistence_failed, partial_execution i dotychczasowe szczegółowe odmowy safety. Istniejące kody bezpieczeństwa nie są zamieniane na ogólne error.

### Transporty o innym MIME

JPEG/PNG/SVG/WAV i tekst Prometheus zachowują własny Content-Type. Nie zamieniamy obrazu ani audio na JSON/base64 dla ujednolicenia odpowiedzi. Metadane obrazu opisuje Frame; nagłówki czasu/tożsamości muszą zgadzać się z faktycznie serwowaną klatką. JSON błędu korzysta ze wspólnej koperty, jeżeli klient ją negocjuje.

SSE zachowuje text/event-stream, nazwę tematu i domenowy payload. Payload ma taki sam model danych jak HTTP data tej rodziny. Transport BUS/zdarzenia nie odnawia ts, observed_at ani generacji komendy. Ograniczone bufory i kursory nie zależą od długości deque ani od skoków zegara.

## Wspólny model obserwacji

Observation jest jedyną regułą interpretacji pomiaru w Pi i PC, używaną przez Przegląd, Urządzenia, System i Kalibrację. Snapshoty kanałów powstają u źródła i są projektowane przez API. UI nie składa konkurencyjnego pomiaru z kilku różnych fallbacków.

~~~json
{
  "value": 0.75,
  "unit": "ratio",
  "observed_at": 1791663265.8,
  "source": "motion-executor",
  "instance_id": "producer-instance",
  "generation": "opaque-generation",
  "max_age_s": 2.5,
  "ready": true,
  "stale": false,
  "simulated": false,
  "error": null,
  "physical_validity": "unverified"
}
~~~

assessed_at opisuje czas oceny age_s i nie jest nowym pomiarem; czas publikacji nie jest dodawany drugi raz do wieku przeliczonego przez API. source i observed_at są obowiązkowe; nieznany czas daje null i ready:false. instance_id/generation pozostają tam, gdzie producent je zapewnia; nie wymyślamy ich dla /proc czy pliku. ready opisuje świeży poprawny odczyt, physical_validity osobno opisuje potwierdzenie fizycznego znaczenia. Brak profilu kalibracji nie usuwa rzeczywistego odczytu.

- Bateria, roll, pitch i yaw mają osobne czasy i błędy. Błąd yaw nie ukrywa poprawnej baterii.
- Zero, false i puste listy pozostają wartościami, kiedy producent rzeczywiście je podał. Brak pola/null nie zamienia się w zero.
- Stary odczyt może pozostać w cache, ale ma stale:true i jawny wiek. Nie wchodzi jako świeży punkt wykresu.
- Błąd rodzica dotyczący transportu wygasza aktualność całego zachowanego snapshotu. Błąd jednego sensora nie jest takim błędem.
- Age rośnie mimo kolejnych odpowiedzi HTTP i heartbeatów. Zegary hostów mają osobny server_time/offset; nie zaciskamy przyszłego nieznanego czasu do wieku zero.
- Wewnętrzne budżety TTL, lease, rampy i UART pozostają monotoniczne. Czas UNIX służy wymianie i prezentacji, nie zastępuje ich.
- Próg max_age_s pochodzi z definicji źródła/kontraktu. Nie tworzymy różnych progów dla tej samej obserwacji w kilku ekranach.

### Jednostki i adaptery

| Dane | Kanoniczna jednostka/znaczenie | Zgodność ze starszym formatem |
| --- | --- | --- |
| battery | ratio, 0..1 | /state battery_pct 0..100 przelicza się dokładnie przez /100; BUS stare battery_pct było ratio i ma osobny nazwany adapter |
| roll/pitch | sdk_raw i physical_validity=unverified do potwierdzenia znaczenia | dotychczasowe wartości zachowane; brak domyślnego potwierdzenia osi/znaku |
| yaw_raw | sdk_raw i physical_validity=unverified do potwierdzenia znaczenia | raw SDK nie jest zastępowany zawiniętym yaw |
| yaw prezentacyjny | deg, derivation=legacy_wrap_180, display_only=true | pochodna tego samego odczytu i czasu; nie nowy pomiar ani korekta odometrii |
| CPU/RAM/dysk/GPU wykorzystanie | %, 0..100 | zachowane wartości procentowe, bez konwersji według heurystyki |
| Pamięć i dysk | MiB/GiB dla dotychczasowych pól; jednostki jawne | *_mb oraz *_gb w istniejącym API oznaczają bazę 1024; nie MB/GB dziesiętne |
| Load | load, wartości 1/5/15 minut | nie procent CPU |
| Temperatura | degC | null przy braku czujnika, nie 0 |
| Confidence/edge ratio/ROI bins | ratio, 0..1 | legacy edge_pct, edge_pct_raw oraz t_low/t_high są ułamkami, mimo nazwy pct |
| Odometria | m, rad, m/s, rad/s tylko z właściwym modelem/ramą | znormalizowane komendy/SDK step mają własne jednostki, nie są zgadywanym m/s |
| Czasy | s UNIX; TTL w polu ttl_ms jako ms | brak automatycznego mnożenia/dzielenia po wielkości liczby |

Przykład graniczny: REST battery_pct=1 oznacza 1%, czyli ratio=0.01. Safety value=1 z unit=ratio oznacza 100%. Nie wolno rozpoznawać formatu przez warunek value<=1.

## Rodziny danych i obowiązkowe pola

| contract_id | Wersja domeny | Zawartość i zasady |
| --- | --- | --- |
| rider.safety | istniejąca 1 | DISARMED/ARMED/ESTOP, owner/lease, command_generation, instance, target/output, capabilities/actuators, dynamics, sensor_quality; kolejka i ACK wskazują ten sam wykonawca |
| rider.telemetry | 1 | devices, niezależne Observation dla kanałów XGO, stan kamery/LCD, firmware i źródła; nie utożsamia IMU z pozycją |
| rider.system | 1 | host/OS, cpu_pct/load1/5/15, mem_total_mb/used_mb/pct, disk_total_gb/used_gb/pct, temp_c, uptime, historie i jawne jednostki |
| rider.health | 1 | api.live, wymagane komponenty bazowe, bus.connected/last_msg_age/last_heartbeat_age, readiness per component; API HTTP200 nie potwierdza urządzeń |
| rider.catalog | istniejąca 2 | jednostki, zadania, aliasy, zasoby, option_schema, can_move/motion_owner, start_available/reason i permissions per action; wersje koperty i domen |
| rider.tasks | istniejąca 2 | requested/state/running/ready, opcje, członkowie, intencja/request/generation, dowody producer/PID, partial/error; ready nie jest active targetu |
| rider.services | 2 | identity=host:unit, host/unit, installed/load_state/active_state/sub_state/unit_file_state/pid/process_running, consumers/dependencies/resource claims i permissions |
| rider.resources | 1 | name, physical/logical, diagnostic_available, state, free:true/false/null, właściciele/PID/unit, konsumenci, dozwolone recovery i dowód zwolnienia |
| rider.service_graph | 2 | te same identity co rider.services, host-qualified edges, powody działania, źródło i czas każdego węzła; agregacja nie odświeża hostów |
| rider.frames | 1 | raw/proc/ssd/obst/tracker osobno, Frame i URL/metadane każdego strumienia; bez zamiany producentów |
| rider.obstacle | 1 | present/confidence/edge_ratio, ROI i diag.bins/t_low/t_high/edge_ratio_raw, źródło/frame/time/error; brak detekcji nie potwierdza wolnego korytarza |
| rider.navigation | istniejąca 1 | status/config/map/pose/path/HOME, jakość i czasy każdej składowej, rama, data_ready/navigation_ready/start availability; bierny plan nie uprawnia MOVE |
| rider.odometry | istniejąca 1 | odom.pose/status, physical model, profile_digest, reference/HOME/frame_hash, wiarygodność i reset/invalidation |
| rider.calibration | istniejąca 1 | profiles/digest/history, confirmation/model_ready, active/pending/applied, transaction i matching motion+odom ACK; save nie oznacza activate |
| rider.providers | 1 | domain, requested/effective routing/backend/host, configured/initialized/model_loaded/ready/error, persisted; peer health oddzielnie |
| rider.voice | 1 | provider list i wynik ASR/TTS/capture/say, model/backend/source, ready/error, audio MIME; probe/test ma jawny zakres |
| rider.chat | 1 | items/history albo reply z backend/source/error; history-only nie udaje odpowiedzi AI; brak echo/mock fallbacku w realnym trybie |
| rider.face | 1 | state/sink/backend/out, play/stop/render result; DISPLAY to odrębny zasób; orientacja LCD zachowana |
| rider.models | 1 | models[] name/path/category/type/format/size i total, aktywne przypisania gdzie istnieją; installed nie oznacza loaded/ready |
| rider.google_feed | 1 | stan/feed timestamp/metrics i ostatni cache; missing cache ma reason, bez sztucznego bieżącego czasu |
| rider.home | 1 | configured/authenticated/devices i jawny wynik command/auth; brak poświadczeń/łącza nie zamienia się w demo |
| rider.api_metrics | 1 | metrics.control/navigator/voice/google_home/chat/face.{ok,error}, total_errors, okres/scope/źródło |
| rider.version | 1 | project/branch/hash/dirty/cache/source; wersja kodu nie zastępuje instancji producenta |
| rider.network | 1 PC | konfiguracja i obserwacja połączenia, host/source/time; probe na żądanie, bez zmiany Wi-Fi |
| rider.mcp | 1 PC | tools/resources/stats/history i permissions, rozdzielone rejestr lokalny i historia TextProvider |
| rider.project | 1 PC | issues/meta oraz wyniki jawnych operacji GH/Git; zachowanie istniejących pól |
| rider.knowledge | 1 PC | documents/search/status/reindex; zachowanie wyników, źródeł i metadanych |
| rider.assistant | 1 PC | konfiguracja/urządzenia/historia/status oraz jawne operacje; enabled/configured/ready osobno |

Nowa koperta nie podnosi automatycznie wersji safety, katalogu ani profilu. Zmiana semantyki wymagająca nowej wersji domeny musi mieć nazwaną migrację i fixture. W payloadach domenowych zachowujemy wszystkie obecne pola wykorzystywane przez API, CLI, procesy i ekrany; tabela zmian nazw poniżej definiuje tylko jawne zamiany.

### Jawne zmiany nazw

| Stare pole | Model kanoniczny | Zasada |
| --- | --- | --- |
| service.active string | active_state | bez reinterpretacji jako bool |
| feature.services[].active bool | process_running | nie zastępuje active_state; dostępność oryginalnego stanu zachowana |
| battery_pct REST | Observation battery value/unit=ratio | /100 i ten sam czas |
| battery_pct BUS ratio | Observation battery value/unit=ratio | brak /100; adapter konkretnego tematu i wersji |
| yaw i yaw_raw | odrębne raw/derived Observation | źródłowy czas i derivation; null raw nie uruchamia cichego fallbacku |
| edge_pct / edge_pct_raw | edge_ratio / edge_ratio_raw | jednostka ratio; legacy alias zachowany w projekcji |
| received_at / timestamp odbioru | meta.transport.received_at | nie observed_at |
| PC collect_system_metrics.timestamp | observed_at lokalnego snapshotu | tylko ponieważ timestamp powstaje podczas faktycznej kolekcji |
| frame mtime | file_observed_at, provenance=file_mtime | nie capture timestamp, dopóki nie ma dowodu producenta |
| provider pc_health | peer_health | oddzielone od domains[].ready |
| sam SIGTERM ok | operation pending + signal_sent | released dopiero po obserwacji zasobu |
| feature ok:true/start | task_accepted, state=starting | task_ready dopiero po matching dowodach producentów |

## Uprawnienia i skutki operacji

can_move opisuje potencjalny skutek procesu/zadania. process_running opisuje proces. ready wymaga dowodów właściwych dla zadania. start_available opisuje zdolność implementacji, a permissions[action] bieżącą dopuszczalność operacji.

Uruchomienie bazowego motion-executor w DISARMED nie może być traktowane jak uprawnienie do jazdy. Start S3/S4/S9 i polecenia aktuatorów mają inne wymagania niż start odczytowej bazy czy pasywnego S6. Politykę wylicza i egzekwuje backend; UI prezentuje ją bez własnej konkurencyjnej listy warunków.

Przy start_available:false backend odmawia operacji przed journalem/systemd/BUS. Sprawdzenie dotyczy zarówno feature_handler→set_feature→_start, jak i bezpośredniej administracji jednostką. S4/S9 pozostają niedostępne do uruchomienia. Navigator blokuje MOVE przez navigation_traversal_unverified i _motion_data_permitted. Ta polityka nie stanowi potwierdzenia gotowości fizycznej.

Pasywne planowanie/mapowanie pozostaje dostępne w przewidzianych zadaniach. Zmiana profilu/referencji/HOME lub ramy unieważnia niezgodną geometrię. PC stosuje identyczne warunki widoczności i dostępności akcji.

STOP przez POST jest mutacją. GET/HEAD pozostają odczytowe. Historyczne GET /api/stop wymaga jawnego zakończenia obsługi mutacji: zwraca 405/Allow: POST albo udokumentowany opis metody, bez wysyłania STOP i zmiany generacji. Wszystkie znane wywołania migrują w PR #262.

Aliasy face_tracking/hand_tracking/follow_me/recon zachowują mapowanie do ruchowych S3/S4. Nie przepisujemy ich na S6. /vision/tracking/mode jest aliasem pasywnego S6 mode=face|hand|none; konflikt S3/S6 daje 409 bez niejawnego zatrzymania drugiego zadania.

## Obrazy i historia

Frame zawiera stream, url, frame_id, observed_at/capture_at lub null, file_observed_at, source/provenance, exists, stale, error, placeholder oraz max_age_s. RAW, PROC, SSD, OBST i TRACKER mają odrębne rekordy. /api/last_frame jest obrazem, nie JSON metadanych.

Jeden resolver wybiera plik i tworzy jego metadane; osobny moduł nie może opisać RAW_PATH, a serwować innego SNAP_DIR/cam. Odbiór JPEG ani ponowny odczyt mtime nie dowodzi pracy producenta. Domyślny podgląd bieżący pokazuje tylko aktualną klatkę; archiwum można odczytać jawnie, z oznaczeniem. Brak aktywnej kamery nie uruchamia capture.

Karta PC img_obst dziś czyta /vision/ssd. Spec wymaga jawnego rozróżnienia: obraz OBST pochodzi z obst_annot, SSD z /vision/ssd. Nie wolno nazwać SSD obrazem OBST. Obydwa strumienie pozostają dostępne; karta zachowuje funkcję podglądu, a Urządzenia umożliwiają właściwy wybór strumienia.

Wykresy zachowują do 60 próbek wraz z czasem. Oś/history label pokazuje rzeczywisty zakres czasu albo ostatnie 60 próbek; nie zakłada 60 sekund przy odświeżaniu co 2 s. Null/stale daje przerwę. Istniejące hist_cpu/hist_mem pozostają w projekcji legacy. ROI bins i progi zachowują ratio oraz jawne skalowanie osi.


## Sterowanie i modele fizyczne

### Komenda i potwierdzenie

Komenda pozostaje płaska na HTTP i BUS. Wspólny walidator zachowuje action/source/generation/seq/request_id/ts/ttl_ms oraz dane aktuatora. Nie opakowujemy jej w odpowiedź HTTP meta i nie nadajemy nowego czasu w proxy.

| Pole | Docelowa reguła |
| --- | --- |
| action | jawna nazwa z rejestru operacji i możliwości |
| source | manual/follow_me/navigation według rzeczywistego właściciela intencji |
| generation | niepusty opaque identyfikator oryginalnej generacji |
| seq | int, nie bool, 0..2^63-1; rosnąca sekwencja w generacji |
| request_id | niepusty string do 128 znaków; ten sam w całym przepływie |
| ts | skończony UNIX seconds, oryginalny czas polecenia |
| ttl_ms | int, 1..500; nie odnawiany przy retransmisji |
| vx/yaw | znormalizowane -1..1; przód vx>0, lewo yaw<0, prawo yaw>0 |
| duration | sekundy, maksymalnie 0.25 dla pojedynczego impulsu |
| height | logiczny indeks 0..12; nie metry |
| enabled | bool, bez wartości truthy z dowolnego stringa |
| action ID | wyłącznie jawny katalog dostępnych akcji i możliwości przerwania |

STOP/ESTOP pozostają dostępne bez wymagania zgody na ruch. ARM/clearESTOP wymagają jawnego planu i zgody; clear kończy w DISARMED. MOVE/turn/height/balance/action wymagają właściwego owner, aktualnej zgody, capability i ważnej komendy. Aktywacja profilu wymaga świeżego DISARMED i idle/zero, ale nie jest ARM ani próbą napędów.

ACK koreluje request_id/action/source/seq/command_generation i czas. generation po STOP/aktywacji może być nowa; command_generation nadal wskazuje żądanie. accepted oznacza przyjęcie celu; executed ruchu oznacza SDK accepted. HTTP202 oznacza brak terminalnego dowodu. target, przyjęty SDK output i stan fizyczny mają odrębne znaczenie.

### Inwentarz tematów ruchu i telemetrii Pi

| Temat lub ścieżka | Producent | Payload i znaczenie | Odbiorcy |
| --- | --- | --- | --- |
| motion.command | Operator/API, autoryzowany tracking/navigator | oryginalna komenda i intencja; żadnej rekonstrukcji aktualnego ARM | jedna brama/executor |
| motion.ack | executor | request/action/source/seq/command_generation, result/reason, czas, physical_completion | HTTP waiter, UI, PC |
| motion.state oraz plik statusu | executor | safety1, owner/lease/generation/instance, target/output, capabilities, dynamics, sensor_quality, calibration | API, readiness zadań, odometria, UI/PC |
| motion.output | executor | faktycznie przyjęte signed SDK steps, czas SDK write, instance/generation | odometria |
| motion.sensor.raw | executor | niezależne odczyty/czasy/błędy baterii i osi IMU | sensor-reader |
| imu.data | sensor-reader | surowe osie, jakość każdego kanału; czas agregatu może być null | API/cache, odometria |
| devices.xgo | sensor-reader | firmware i IMU; stare battery_pct jest ratio, legacy pose jest IMU | API/cache, legacy |
| robot.pose | odometria | x/y m, theta rad, theta_deg pochodna, jakość/frame/HOME/source time | mapper/navigator/API/PC |
| odometry.reference | API operatora | reference x/y/theta, ewentualnie HOME, dokładny aktywny digest i manual envelope | odometria |
| odometry.reference.ack | odometria | wynik reference, operator-reported, actuation:false | API/UI |
| calibration.activate | API operatora | digest i oryginalny manual envelope/zgoda/plan | executor i odometria |
| calibration.ack | executor | executed/rejected konfiguracji, transaction, actuation:false | API/UI i matching consumer state |
| /api/calibration/state | projektor API | oba świeże stany motion/odom, matching digest/transaction/instance i applied ACK | Calibration |
| /api/odometry/state | projektor API | żywy proces, pose/reference/calibration/ACK | Calibration |

Właściwy temat to motion.sensor.raw, singular. Dawna nazwa motion.sensors.raw nie jest alternatywnym aktywnym kontraktem.

motion.output jest ostatnim faktycznym SDK write. Heartbeat motion.state nie może odnowić jego czasu, tożsamości ani generacji. Odometrii nie zasila sam target ani żądanie operatora.

### Migracja starszych producentów

| Wejście | Decyzja w PR Pi |
| --- | --- |
| common.bus.TOPIC_MOTION_COMMAND, dawniej motion | centralny rejestr wskazuje motion.command; producenci korzystają ze wspólnego buildera |
| cmd.move/stop/balance/height, cmd.motion.*, motion.cmd, motion | jawne adaptery znanych kształtów; brak envelope nie daje prawa do aktuatora |
| cmd/type, dir/direction, lx/az, dur/t/ms, forward/back/left/right | jedna udokumentowana konwersja nazw, znaku i jednostek; bez czasu/generacji/zgody z bieżącego stanu |
| apps/nlu/main.py | autoryzowana oryginalna intencja albo propozycja do operatora; nie dopisywać aktualnego ARM do starej frazy |
| services/motion_cmd_shim.py | wycofany producent; nie publikuje, nie restampuje i nie tworzy autoryzacji polecenia |
| scripts/dev_send-cmd.py | wycofać bare speed/runtime ze ścieżki użytkowej; wskazać jawne narzędzie manualne |
| apps/choreographer, konfigurowalny topic=motion | brak automatycznych świeżych komend z emocji/scenariusza; ruch wyłącznie z osobną oryginalną autoryzacją |
| apps/menu BACK | canonical STOP; zachować funkcję przycisku, LCD i boot |
| services/motion_bridge.py | pozostaje wycofany, nie tworzyć drugiego UART/SDK owner |
| services/web_motion_bridge.py GET /api/stop | POST jedyną mutacją; GET/HEAD bez skutków, 405 |
| control_proxy.proxy_stop_get | nie podłączać ponownie mutacji GET |
| apps/ui LCD manager/overlay | odczyt safety1 zamiast stopped/enabled/last_cmd_age_ms domyślnych starego formatu |
| API devices.py obserwujące cmd balance/height | historia żądań jest odrębna od rzeczywistego stanu actuators wykonawcy |

Macierz obejmuje również demo i scalar topics xgo/motion.bridge.telemetry/roll/pitch/yaw/battery_pct/fw. Jawny legacy adapter zachowuje źródło, symulację i brak czasu. Odczyt historycznej konfiguracji nie może automatycznie uruchomić urządzenia.

### Odometria i kalibracja

Signed SDK step jest mapowany na m/s lub rad/s wyłącznie przez zmierzoną tabelę danego profilu. Brak wpisu daje sdk_step_unmeasured; nie dodajemy interpolacji ani zgadywanej prędkości. confidence pozostaje null z confidence_kind=unquantified_model, dopóki nie ma modelu dokładności.

reference/HOME i frame_hash zawierają tożsamość profilu/aktywnej transakcji; nie przeżywają restartu ani utraty ciągłości. Zero we współrzędnych przy data_ready:false nie dowodzi położenia. Idle opiera się na bezpośrednim zaakceptowanym SDK zero i wymaganych aktualnych dowodach; czas ostatniego STOP pozostaje oryginalny.

Profile pozostają immutable schema1 i dokładny SHA256. Metadata HTTP/BUS nie wchodzą do haszowanego profilu. Zapis nie oznacza aktywacji, imported nie oznacza verified, a applied nie oznacza model_ready lub fizycznego potwierdzenia.

Aktywacja utrzymuje pending→preflight→zastosowanie/nowa generacja→durable applied marker. Pending/corrupt blokuje użycie profilu po starcie oraz ARM. last_ack ostatniej próby i applied_ack bieżącej konfiguracji są odrębne.

Matching porównuje digest, executor instance, request_id, command_generation, seq i stable applied generation. Ponowna aktywacja tego samego hash to nowa transakcja. saved_profile po restarcie nie fabrykuje nowego ACK i nie zachowuje starej referencji. Wartości ramp/ceiling i watchdog pozostają w istniejących ograniczeniach.


## Kompletność panelu Pi

### Manifest kart Przeglądu Pi

15 oryginalnych kart oraz safety, bieżące zadania i historia ACK.

| Karta | Identyfikatory elementów | Źródła | Zachowana funkcja |
| --- | --- | --- | --- |
| 1. System | ci_host, ci_cpu, ci_load, ci_mem, ci_disk, ci_os, ci_fw, system-age | /sysinfo; /state; /healthz | host/cpu/load/RAM/dysk/OS/firmware; czas źródła |
| 2. Urządzenia | d_cam, d_lcd, d_xgo_imu, d_xgo_pose, d_xgo_batt, xgo-age, d_temp | /state; /api/control/state; /healthz | kamera/LCD/IMU/bateria/temperatura; Observation per channel |
| 3. Historia CPU / RAM — ostatnie 60 próbek | chart | /sysinfo | hist_cpu/hist_mem + czas próbek |
| 4. Kamera  … | camBadge, img_cam, leg_cam_txt | /vision/snap-info; /vision/cam | Frame raw i obraz tego samego frame_id |
| 5. Health | h_status, h_uptime, h_msg, h_hb | /healthz; /api/bus/health | API/BUS/uptime i wiek wiadomości/heartbeat osobno |
| 6. Obstacle | obs_present, obs_conf, obs_edge, obstacle-age | /vision/obstacle | present/confidence/edge ratio/source/time/error |
| 7. ROI histogram — edges | binsCanvas, binsLegendTxt | /vision/obstacle | diag.bins/t_low/t_high/edge_ratio_raw |
| 8. Kamera — PROC | img_proc, leg_proc_txt | /vision/snap-info; /vision/edge | Frame proc |
| 9. API Metrics | metric_control, metric_navigator, metric_voice, metric_google_home, metric_chat, metric_face, metric_total_errors | /api/app-metrics | sześć domen ok/error i total_errors |
| 10. Snap freshness | age_raw, age_proc, age_obst, age_tracker | /vision/snap-info | niezależna świeżość raw/proc/obst/tracker, ssd dostępny w Devices |
| 11. Repozytorium | stałe odnośniki | stałe UI + /api/status/version | repo i odnośniki GH; bez zmiany konfiguracji |
| 12. Camera — OBST (annot) | img_obst, leg_obst_txt | /vision/snap-info; /snapshots/obst_annot.jpg | Frame obst i właściwy annot |
| 13. Info | imu-yaw-raw | /api/control/state; /state | yaw raw, unit sdk_raw/physical validity; IMU nie jest odometrią |
| 14. Linki | stałe odnośniki | /events; /metrics; /system/; /control; /home | zachowane linki i funkcje |
| 15. Camera — TRACKER (Follow Me) | img_tracker, leg_tracker_txt | /vision/snap-info; /vision/tracker | Frame tracker, bez automatycznego S3/S6 start |
| 16. Bezpieczeństwo ruchu | safety-heading, safety-state, safety-ready, safety-age, safety-owner, safety-lease, safety-reason | /api/control/state; POST /api/safety tylko po akcji | safety/STOP/owner/lease/reason/actual age |
| 17. Bieżące zadania | overview-task-status, overview-tasks | /api/logic/catalog | requested tasks i dokładny task state |
| 18. Żądania i potwierdzenia | request-history, last-event | /events; wyniki jawnych żądań | request history i dopasowane ACK; fizyczne completion unverified |




## Inwentarz zarejestrowanych endpointów

Inwentarz wygenerowany z aplikacji Flask bez uruchamiania sprzętu i procesów. Osobny most 8081 i opcjonalne usługi głosowe są niezależnymi interfejsami. Obrazy, SSE i metryki Prometheus zachowują swój typ MIME. Zarejestrowana trasa nie potwierdza gotowości opcjonalnego providera.

| Methods | Path | Handler | Domain | Version |
| --- | --- | --- | --- | --- |
| GET, HEAD, OPTIONS | `/` | `dashboard` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/api/app-metrics` | `app_metrics` | `rider.api_metrics` | 1 |
| GET, HEAD, OPTIONS | `/api/bus/health` | `_bus_health` | `rider.health` | 1 |
| OPTIONS, POST | `/api/calibration/activate` | `activate` | `rider.calibration` | 1 |
| GET, HEAD, OPTIONS, POST | `/api/calibration/profiles` | `catalog` | `rider.calibration` | 1 |
| GET, HEAD, OPTIONS | `/api/calibration/profiles/<digest>` | `profile` | `rider.calibration` | 1 |
| GET, HEAD, OPTIONS | `/api/calibration/state` | `state` | `rider.calibration` | 1 |
| OPTIONS, POST | `/api/chat` | `chat_send` | `rider.chat` | 1 |
| GET, HEAD, OPTIONS | `/api/chat/history` | `chat_history` | `rider.chat` | 1 |
| GET, HEAD, OPTIONS | `/api/chat/ping` | `_chat_ping` | `rider.chat` | 1 |
| OPTIONS, POST | `/api/chat/send` | `chat_send` | `rider.chat` | 1 |
| OPTIONS, POST | `/api/cmd` | `control_proxy_handler` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/control` | `control_proxy_handler` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/control/balance` | `api_balance` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/control/height` | `api_height` | `rider.safety` | 1 |
| GET, HEAD, OPTIONS | `/api/control/state` | `api_control_state` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/control_legacy` | `api_control_legacy` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/draw/face` | `draw_face_route` | `rider.face` | 1 |
| OPTIONS, POST | `/api/draw/face` | `api_draw_face_legacy` | `rider.face` | 1 |
| GET, HEAD, OPTIONS | `/api/flags` | `api_flags_get` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/flags/<name>/<state>` | `api_flags_set` | `rider.safety` | 1 |
| GET, HEAD, OPTIONS | `/api/google/raw/last.json` | `google_proxy.get_last_snapshot` | `rider.google_feed` | 1 |
| GET, HEAD, OPTIONS | `/api/google/status` | `google_proxy.get_status` | `rider.google_feed` | 1 |
| OPTIONS, POST | `/api/home/auth` | `home_auth` | `rider.home` | 1 |
| GET, HEAD, OPTIONS | `/api/home/auth/url` | `home_auth_url` | `rider.home` | 1 |
| OPTIONS, POST | `/api/home/command` | `home_command` | `rider.home` | 1 |
| GET, HEAD, OPTIONS | `/api/home/devices` | `home_devices` | `rider.home` | 1 |
| GET, HEAD, OPTIONS | `/api/home/status` | `home_status` | `rider.home` | 1 |
| GET, HEAD, OPTIONS | `/api/last_frame` | `_api_last_frame` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/logic/catalog` | `feature_catalog_handler` | `rider.catalog` | 2 |
| OPTIONS, POST | `/api/logic/feature/<name>` | `feature_handler` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/logic/features` | `feature_registry_handler` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/logic/state` | `feature_state_handler` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/logic/summary` | `feature_summary_handler` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/models/installed` | `installed_models_handler` | `rider.models` | 1 |
| GET, HEAD, OPTIONS | `/api/motion/queue` | `api_motion_queue` | `rider.safety` | 1 |
| OPTIONS, POST | `/api/navigator/config` | `api_navigator_config` | `rider.navigation` | 1 |
| OPTIONS, POST | `/api/navigator/return_home` | `api_navigator_return_home` | `rider.navigation` | 1 |
| OPTIONS, POST | `/api/navigator/start` | `api_navigator_start` | `rider.navigation` | 1 |
| GET, HEAD, OPTIONS | `/api/navigator/status` | `api_navigator_status` | `rider.navigation` | 1 |
| OPTIONS, POST | `/api/navigator/stop` | `api_navigator_stop` | `rider.navigation` | 1 |
| OPTIONS, POST | `/api/odometry/reference` | `operator_reference` | `rider.odometry` | 1 |
| GET, HEAD, OPTIONS | `/api/odometry/state` | `reference_state` | `rider.odometry` | 1 |
| GET, HEAD, OPTIONS, PATCH | `/api/providers/<domain>` | `provider_domain_handler` | `rider.providers` | 1 |
| GET, HEAD, OPTIONS | `/api/providers/health` | `providers_health_handler` | `rider.providers` | 1 |
| OPTIONS, POST | `/api/providers/pc-heartbeat` | `providers_pc_heartbeat_handler` | `rider.providers` | 1 |
| GET, HEAD, OPTIONS | `/api/providers/state` | `providers_state_handler` | `rider.providers` | 1 |
| GET, HEAD, OPTIONS, POST | `/api/resource/<name>` | `api_resource` | `rider.resources` | 1 |
| GET, HEAD, OPTIONS, POST | `/api/safety` | `api_safety` | `rider.safety` | 1 |
| GET, HEAD, OPTIONS | `/api/services/<unit>/logs` | `service_logs` | `rider.services` | 2 |
| GET, HEAD, OPTIONS | `/api/services/graph` | `services_dashboard.services_graph` | `rider.service_graph` | 2 |
| GET, HEAD, OPTIONS | `/api/status/version` | `version.version_info` | `rider.version` | 1 |
| GET, HEAD, OPTIONS, POST, PUT | `/api/system/ai-mode` | `ai_mode_handler` | `rider.providers` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/cam` | `vision_api_alias.vision_cam` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/edge` | `vision_api_alias.vision_edge` | `rider.frames` | 1 |
| OPTIONS, POST | `/api/vision/follow/face` | `vision_api_alias.legacy_follow_face` | `rider.tasks` | 2 |
| OPTIONS, POST | `/api/vision/follow/hand` | `vision_api_alias.legacy_follow_hand` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/api/vision/obst` | `vision_api_alias.vision_obst` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/obstacle` | `vision_api_alias.vision_obstacle` | `rider.obstacle` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/snap-info` | `vision_api_alias.snap_info` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/ssd` | `vision_api_alias.vision_ssd` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/api/vision/tracker` | `vision_api_alias.vision_tracker` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS, POST | `/api/vision/tracking/mode` | `vision_api_alias.set_tracking_mode` | `rider.tasks` | 2 |
| OPTIONS, POST | `/api/voice/asr` | `asr_local_handler` | `rider.voice` | 1 |
| OPTIONS, POST | `/api/voice/capture` | `capture_handler` | `rider.voice` | 1 |
| GET, HEAD, OPTIONS | `/api/voice/providers` | `providers_list_handler` | `rider.voice` | 1 |
| OPTIONS, POST | `/api/voice/providers/test` | `providers_test_handler` | `rider.voice` | 1 |
| OPTIONS, POST | `/api/voice/say` | `say_handler` | `rider.voice` | 1 |
| OPTIONS, POST | `/api/voice/tts` | `tts_local_handler` | `rider.voice` | 1 |
| GET, HEAD, OPTIONS | `/calibration` | `page` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/camera/last` | `camera_last` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/camera/placeholder` | `camera_placeholder` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/camera/proc` | `camera_proc` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/camera/raw` | `camera_raw` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/chat` | `serve_chat` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/control` | `control_page` | `rider.safety` | 1 |
| GET, HEAD, OPTIONS | `/devices` | `devices_page` | `rider.http` | 1 |
| OPTIONS, POST | `/draw/face` | `draw_face_route` | `rider.face` | 1 |
| GET, HEAD, OPTIONS | `/events` | `events` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/face/ping` | `face_ping` | `rider.face` | 1 |
| OPTIONS, POST | `/face/play` | `face_play` | `rider.face` | 1 |
| OPTIONS, POST | `/face/render` | `face_render` | `rider.face` | 1 |
| GET, HEAD, OPTIONS | `/face/state` | `face_state` | `rider.face` | 1 |
| OPTIONS, POST | `/face/stop` | `face_stop` | `rider.face` | 1 |
| GET, HEAD, OPTIONS | `/google_home` | `serve_google_home` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/health` | `health_alias` | `rider.health` | 1 |
| GET, HEAD, OPTIONS | `/healthz` | `healthz` | `rider.health` | 1 |
| GET, HEAD, OPTIONS | `/home` | `serve_home` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/livez` | `livez` | `rider.health` | 1 |
| GET, HEAD, OPTIONS | `/metrics` | `metrics` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/navigation` | `serve_navigation` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/readyz` | `readyz` | `rider.health` | 1 |
| GET, HEAD, OPTIONS | `/snapshots/<path:fname>` | `snapshots_static` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/state` | `state_route` | `rider.telemetry` | 1 |
| GET, HEAD, OPTIONS | `/static/<path:filename>` | `static` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/svc` | `svc_list_route` | `rider.services` | 2 |
| GET, HEAD, OPTIONS, POST | `/svc/<name>` | `svc_name_route` | `rider.services` | 2 |
| GET, HEAD, OPTIONS | `/svc/<name>/status` | `svc_status` | `rider.services` | 2 |
| GET, HEAD, OPTIONS | `/sysinfo` | `sysinfo` | `rider.system` | 1 |
| GET, HEAD, OPTIONS | `/system/` | `system_dashboard_html` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/view` | `dashboard` | `rider.http` | 1 |
| GET, HEAD, OPTIONS | `/vision/cam` | `vision_api.vision_cam` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/vision/edge` | `vision_api.vision_edge` | `rider.frames` | 1 |
| OPTIONS, POST | `/vision/follow/face` | `vision_api.legacy_follow_face` | `rider.tasks` | 2 |
| OPTIONS, POST | `/vision/follow/hand` | `vision_api.legacy_follow_hand` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/vision/obst` | `vision_api.vision_obst` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/vision/obstacle` | `vision_api.vision_obstacle` | `rider.obstacle` | 1 |
| GET, HEAD, OPTIONS | `/vision/snap-info` | `vision_api.snap_info` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/vision/ssd` | `vision_api.vision_ssd` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS | `/vision/tracker` | `vision_api.vision_tracker` | `rider.frames` | 1 |
| GET, HEAD, OPTIONS, POST | `/vision/tracking/mode` | `vision_api.set_tracking_mode` | `rider.tasks` | 2 |
| GET, HEAD, OPTIONS | `/web/<path:fname>` | `serve_web` | `rider.http` | 1 |

Wdrożenie LCD obejmuje chronione pliki startowe i jednostki systemd; wymaga osobno zapisanej procedury z kopią plików i stanu usług. Nie omijaj blokad pi-preview ani nie odtwarzaj vendor cleanup podczas testów. KEEP_BL_ON domyślnie wynosi 0. Odczyt baterii pochodzi wyłącznie od jedynego wykonawcy UART. Wczesny splash przed brokerem nie ma jeszcze pomiaru; po uruchomieniu wykonawcy LCD pokazuje ten sam gotowy ekran Device Info z IP i baterią, zachowuje orientację 270° i gaśnie po 45 s. Nie wprowadza nowego panelu zadań. Odbiór ekranu jest możliwy bez restartu robota i bez ruchu.

Pole `configured_rot` pochodzi z `PREVIEW_ROT` procesu API (domyślnie 0); opisuje konfigurację podglądu, nie montaż ani orientację ekranu startowego. Rzeczywisty renderer startowy zgłasza `rot=270`. Konfiguracja kamery bez LCD nie może nadpisywać tej obserwacji ani potwierdzać stanu podświetlenia.

LCD `preview_config` ma osobny czas źródłowy. Rzeczywiste `source`/`observed_at` opisują raport cyklu renderera; `power_source`/`power_observed_at` wymagają jawnego `power_known=true` i `control_write_accepted`. `frame_source`/`frame_observed_at` zachowują czas pierwotnego raportu przyjęcia pikseli; raport wygaszenia nie nadaje im ani pomiarowi baterii nowego czasu. Przyjęcie przez oprogramowanie pozostawia fizyczną widoczność niezweryfikowaną; potwierdzenie operatora jest osobnym zapisem odbioru.


## Zakres panelu ruchu
- Przegląd, Urządzenia i Chat: odczyty oraz operacje bez napędów; bez formularza zgody, przycisków ruchu i skrótu STOP. Obserwator stanu może dostarczać pomiary, ale nie wysyła poleceń po utracie fokusu.
- Nawigacja pozostaje pasywnym wizualizatorem. Bez formularza ARM; katalog tego widoku pokazuje tylko zadania bez ruchu. Autonomia nadal wymaga ręcznej charakterystyki i pozostaje niedostępna.
- Sterowanie i Kalibracja: lokalna zgoda, krótkie uzbrojenie, STOP, właściwy właściciel i świeży stan wymagane dla napędów.
- System: diagnostyka domyślnie; kontrolki zgody i STOP widoczne dopiero po włączeniu administracji, ponieważ start/restart określonych usług może uruchomić napędy.
- Zwolnienie ESTOP jest jawną operacją operatora z planem i potwierdzeniem. Kończy się stanem DISARMED; nie uzbraja automatycznie. ARM wymaga ponownego potwierdzenia.
- Sprawdzenie kontraktu i odświeżenie stanu odbywają się przed utworzeniem polecenia z TTL 500 ms. Nie odmładza się gotowych poleceń ani nie powtarza żądań automatycznie.
- Czas poleceń pochodzi z osobnego oszacowania zegara odpowiedzi bezpieczeństwa Pi. Odczyty innych hostów nie zmieniają tego oszacowania.


## Sterowanie ręczne i prosta kalibracja reakcji

Widok podstawowy zawiera kamerę, strzałki i STOP oraz suwaki jazdy, skrętu i reakcji.
Czas kliknięcia znajduje się w ustawieniach zaawansowanych. Suwaki prędkości ustawiają
następną pojedynczą próbę; rampa zaczyna obowiązywać po zapisaniu i zastosowaniu.
Ręczne sterowanie wymaga uzbrojenia jednym globalnym przyciskiem po prawej. Nie ma dodatkowej zgody przy każdej strzałce.
Zmiana suwaka, odczyt, zapis, zastosowanie lub powrót wersji nie uruchamiają ruchu.
Nie ma automatycznego powtarzania ani sekwencji kalibracyjnej.

Opcjonalny obiekt profilu interaction zapisuje linear_speed i turn_speed (0–1)
oraz pulse_duration (0.01–0.25 s). Wykonawca udostępnia go w
motion.calibration.interaction; Pi i PC odczytują te same ustawienia z Pi.
Parametry nie stanowią zgody na ruch. Stare profile bez tego obiektu pozostają czytelne.
Rampa i pułap polecenia zachowują dotychczasowy format motion i ograniczenia wykonawcy.
Przyjęcie ustawień nadal wymaga potwierdzenia obu modułów, niezależnie od gotowości
metrycznej odometrii. Zwykłe strojenie nie wymaga dystansu, kątów, HOME ani tabel m/s.

### Mapowanie do SDK Rider 1.4.2

Identyfikator: rider-1.4.2-levels-v2.
- linear_step: podpisany poziom polecenia −127..127, nie licznik obrotów.
- Parametr przekazany do rider_move_x: linear_step * 1.5 / 127, zakres ±1.5.
- turn_step: podpisany poziom −70..70; parametr skrętu SDK ma tę samą wartość.
- motion.output.units = command_levels; mapping_id, linear_sdk_value i
  turn_sdk_value opisują mapowanie, nie zmierzoną prędkość ani ukończenie ruchu.
- Neutralny bajt rejestrów prędkości to 128. Adapter koryguje zaokrąglanie SDK
  w swoim kontrolowanym hooku; nie modyfikuje zainstalowanej biblioteki.
- Czas ogranicza długość polecenia. Prędkość ogranicza jego wartość.
- Pomiary odometrii wymagają conditions.command_mapping zgodnego z tym identyfikatorem.
  Dawne zapisy pozostają do wglądu, lecz bez zgodności skali model jest niegotowy.
  Zmiana mapowania wymaga nowych pomiarów; nie migrujemy współczynników automatycznie.

Formularze pomiarów, odometrii, HOME i diagnostyka pozostają w zwiniętej części
zaawansowanej. Ocena operatora „za szybko / za wolno” służy dopasowaniu sterowania;
nie potwierdza metrycznej odometrii ani autonomii.

## Globalne uzbrojenie panelu i oddzielna zgoda testowa

Jeden przycisk po prawej pokazuje potwierdzony stan wykonawcy: czerwony
„Robot rozbrojony”, zielony „Robot uzbrojony”. Kliknięcie czerwonego jest
zgodą operatora na ręczne sterowanie z panelu; kliknięcie zielonego wysyła STOP.
Kasowanie programowego ESTOP i ARM odbywa się po jednym świadomym kliknięciu,
sekwencyjnie, dopiero po świeżym potwierdzeniu DISARMED. Zewnętrzny ESTOP,
brak sprzętu, brak świeżego zegara lub brak potwierdzenia nadal blokują ARM.
Uzbrojenie nie wywołuje ruchu. Panel używa arming_mode=operator: uzbrojenie trwa do STOP lub rozbrojenia
przez operatora, bez limitu czasu i bez automatycznego odnawiania. Przejście do innego widoku nie wysyła STOP.

Kontrakt bezpieczeństwa dodaje execution_context (panel/test),
panel_motion_enabled i test_motion_enabled. Panel wysyła execution_context=panel.
Zgoda panelu nie uprawnia poleceń testowych, nawet z test_operator_consent=true.
Ręczna fizyczna próba ma osobną sesję execution_context=test i jawne
test_operator_consent=true przy ARM i każdym poleceniu ruchu. Sesja testowa
nie uprawnia panelu. Jedna sesja wykonawcy zapobiega równoległemu sterowaniu.
STOP zawsze unieważnia obie flagi.

Automatyczne pytest/CI pozostaje izolowane: prawdziwy SDK, porty sprzętowe,
SSH i sieć robota są zablokowane niezależnie od obu flag. Flaga zgody testowej
nie wyłącza tej izolacji. Skrypt manual_motion-probe.py wymaga obecnego
operatora, terminala i wpisania jednorazowego potwierdzenia; po próbie wysyła STOP.

Panel: arming_mode=operator, lease_remaining_s=null. Zmiana widoku i fokusu nie rozbraja robota. Próby testowe pozostają w trybie timed, z osobną zgodą. Błędy sprzętu i zewnętrzny ESTOP nadal wymuszają zatrzymanie; stare dane blokują nowe polecenia.

Ograniczony czasowo impuls z panelu zatrzymuje napęd po zakończeniu; uzbrojenie operatora pozostaje aktywne dla następnego kliknięcia. STOP/disarm unieważnia sesję; sesje testowe zachowują swój limit czasu.


## Wspólne ustawienia sterowania ręcznego
GET/POST /api/calibration/controls udostępnia obiekt rider.manual_settings v1 zarządzany przez Pi: revision, values, limits, observed_at, actuation=false. values zawiera linear_speed, turn_speed, pulse_duration, speed_limit, linear_rate i turn_rate. POST przyjmuje revision i częściową zmianę values, zapisuje atomowo, wymaga bezczynnego wykonawcy i nie wysyła polecenia napędu. Nieaktualne zapisy zwracają 409.
Widoki sterowania i kalibracji Pi oraz PC odczytują ten sam obiekt i blokują ruch podczas zapisu zmian oraz przy braku lub nieaktualności danych. Każde polecenie ruchu operatora zawiera direction i settings_revision oraz dokładne wspólne vx/yaw/duration. Wykonawca odrzuca stare rewizje i niespójne wartości. Otwarcie widoku, import szkicu i odczyt historycznego profilu nie zastępują bieżących ustawień. Jawna aktywacja zapisanego profilu aktualizuje wspólne ustawienia.
Domyślny impuls trwa 0.25 s; rampy programowe wynoszą 3 dla jazdy i 4 dla skrętu w jednostkach znormalizowanych na sekundę. Zachowane ograniczenia prędkości i impulsu to 0.6 i 0.25 s. Mapowanie skrętu v3 używa 180 natywnych jednostek SDK przy wartości znormalizowanej 1; dawnych pomiarów fizycznych v2 nie można uznawać za zweryfikowane dane v3. Zmiana kierunku wysyła neutralne polecenie napędu przed rampą w nowym kierunku, bez rozbrajania panelu. To wartości programowe, a nie fizycznie zmierzona kalibracja.

## Parametry i ciągłe sterowanie ręczne

[Kontrakt parametrów, jednostek i trybów sterowania](manual-motion.md).


## Grafika twarzy — rider.face v1

[Studio buźki: schemat, jednostki, ograniczone podglądy i zdarzenia runtime](../FACE_STUDIO.md).
API intencji graficznych i obwiedni audio mają `actuation=false`; nigdy nie autoryzują poleceń napędów.

Nastawy buźki rozszerza opcjonalne `skin` (`none`, `human`, `cat`, `robot`),
domyślnie `none` dla istniejących plików. Endpoint klatki przyjmuje to samo
pole; nastawy i deskryptory zwracają wspólny wybór oraz metadane `skins`.
To addytywne ustawienie wyglądu w rider.face v1, niezależne od definicji gestu
i ruchu fizycznego.
