# Obliczenia i percepcja w Venomie

Pi pozostaje właścicielem kamery, audio, kalibracji i ruchu. W S12/S13 Venom
wykonuje tekst, STT/TTS i **opis sceny**. Opis nie jest detektorem przeszkód ani
zgodą na przejazd. Wyniki tych zadań nie trafiają do poleceń ruchu; ARM i STOP
pozostają niezależne. S14/S15 korzystają z osobnej ograniczonej pętli nawigacyjnej
opisanej poniżej. Opcjonalne narzędzia czatu do sterowania robotem należą do R3.

[English guide](../docs/COMPUTE_VENOM.md).

## Jedno miejsce konfiguracji

`data/compute_config.json` (600) przechowuje wybranego wykonawcę, adres, listę
zadań i rewizję. `config/compute.example.json` jest wzorem, z wykonawcą OFF.
Token znajduje się w prywatnym `/etc/default/rider-compute`:

```sh
RIDER_COMPUTE_TOKEN=<ustawiony_lokalnie_token_urządzenia>
```

API, usługa głosu i offload obrazu czytają ten sam plik env. Ten sam token i ID
muszą być skonfigurowane w module Venoma. Nie publikuj pliku z tokenem ani
adresami urządzeń. API nie przyjmuje dowolnego URL od przeglądarki.

Konfiguracja i awaryjny CLI korzystają z tej samej domeny:

```sh
python3 -m services.compute_config --url https://venom-host:8443 --device-id robot
```

Domyślny `transport_profile: "secure"` wymaga HTTPS z weryfikowanym
certyfikatem albo lokalnego endpointu `http://localhost:<port>`,
`http://127.0.0.1:<port>` lub `http://[::1]:<port>` za tunelem SSH. Brak pola
w istniejącym pliku zachowuje ten profil, bez automatycznej migracji.

Jawny `trusted_lan` dopuszcza HTTP wyłącznie dla skonfigurowanego URL i wymaga
`expected_peer_id` Venoma (32 małe znaki szesnastkowe). Najpierw operator
odczytuje i potwierdza `GET /api/v1/transport/identity` z instalacji Venoma;
tożsamość nie jest sekretem ani kryptograficznym uwierzytelnieniem. Token nadal
pochodzi z prywatnego środowiska usługi. Przykład, po zatrzymaniu celów:

```sh
python3 -m services.compute_config --url http://venom-host:3300 --device-id robot \
  --transport-profile trusted_lan --expected-peer-id <potwierdzony_peer_id_Venoma>
```

Polecenie zapisuje profil, lecz nie wybiera wykonawcy ani nie uruchamia sprzętu.
Zapisz nazwę działającą w DNS LAN ze wszystkich klientów; sufiks `.local` nie
jest wymagany ani zakładany. URL z nazwą i portem pozostaje kanoniczny po zmianie
DHCP. Nie wpisuj adresu wewnętrznego WSL. Otwarta karta pod starym IP wymaga
ponownego otwarcia panelu przez nazwę.

Przed poświadczeniami klient sprawdza wersję 1, `service_role: "venom"` i
oczekiwany peer_id na tym samym TCP. Błąd nazwy/portu, timeout, obca tożsamość,
redirect lub niepoprawne API blokują wysłanie tokenu. Serwer/proxy Venoma musi
utrzymać połączenie po identity; `Connection: close` daje jawny błąd
`transport_identity_connection_closed`, bez wysyłania tokenu na nowy socket.
Dotyczy to compute, nawigacji i pasywnego preflight strumienia.

Po błędzie kolejna aktywna próba odtwarza połączenie z nazwy. W procesie jeden
wspólny gate danego peera ogranicza reconnect: 1/2/4/8/16/30 s z małym jitterem,
bez timera, skanowania sieci ani nowej usługi. Systemowy resolver zarządza TTL;
klient nie przechowuje IP, a połączenie odnawia po 2 s bezczynności lub 30 s
aktywności. Częstotliwość istniejących pętli pozostaje bez zmian. Nowa generacja
unieważnia starą sesję i oczekujące wyniki; klient nie ponawia POST. Aktywny cel
może zakończyć się błędem i wymagać jawnego ponownego uruchomienia. Nie wznawia
mikrofonu, kamery, odtwarzania ani uprawnień ruchu z utraconego lease.

Lokalne snapshoty mogą zawierać `transport.state`, `error`, `generation` i
`retry_after_s`. Przy diagnozie sprawdzaj kolejno nazwę z Pi, port LAN, identity,
zgodność profilu/peer_id, obecność tokenu i API capabilities. Nie podmieniaj
tokenu przy `transport_identity_mismatch` ani `transport_resolve_failed`.
Rollback wymaga zatrzymania celów i jawnego zapisania poprzedniego profilu/URL;
nowe zadania korzystają z nowych sesji.

URL może wskazywać bazę hosta albo dokładny `/api/v1/rider/compute`. Dla
dwukierunkowego tunelu uruchamianego z Venoma przykładowy URL na Pi to
`http://127.0.0.1:18800/api/v1/rider/compute`; port prowadzi przez SSH do
`127.0.0.1:8800` Venoma. Host korzysta z Pi przez własny `127.0.0.1:18080`.

Polecenie zapisuje adres, ale nie aktywuje celu. Wybór wykonawcy:
`GET /api/compute/config`, `POST /api/compute/config` z
`{"executor_id":"venom","revision":<odczytana rewizja>}`. `null` wyłącza
nowe obliczenia zdalne. Przed zmianą zatrzymaj cele obliczeniowe; 409 oznacza
konflikt rewizji albo aktywny cel. CLI i API używają wspólnej blokady orkiestracji.
Starsza konfiguracja lokalna/PC pozostaje do jawnego powrotu wersji. Heartbeat PC
nie zmienia adresu ani wyboru Venoma. Awaria Venoma nie uruchamia lokalnych modeli.

## Opcjonalny keepalive odczytów API Pi

Serwer API Pi zachowuje domyślnie dotychczasowe zamykanie połączeń.
`RIDER_API_HTTP_KEEPALIVE=1` w istniejącym prywatnym środowisku usługi API
włącza ograniczone HTTP/1.1 wyłącznie dla zakwalifikowanego runtime:
Python 3.9 z Werkzeug 1.0.1. Brak flagi, `0`, `false` lub `off` pozostawia
stare zachowanie. Jawne włączenie na innej wersji zatrzymuje start serwera
z `http_keepalive_runtime_unsupported`; niepoprawna wartość daje
`http_keepalive_flag_invalid`. Opcja nie wymaga nowych zależności.

Połączenie może zostać ponownie użyte tylko po GET/HEAD bez body,
bez Transfer-Encoding i Expect, z jednoznacznym brakiem Content-Length
albo pojedynczym `Content-Length: 0`. POST, PUT, DELETE i pozostałe metody,
body, niejednoznaczne nagłówki, HTTP/1.0 oraz żądanie `Connection: close`
zawsze zamykają połączenie. Nieodczytane body odrzuconego żądania nie jest
przetwarzane jako następne żądanie. `Expect: 100-continue` zachowuje jedną
odpowiedź tymczasową, a odpowiedź końcowa zamyka połączenie.

Odpowiedzi o znanej długości, np. JSON i pojedynczy JPEG, mogą korzystać
z tego samego TCP. MJPEG/SSE bez znanej długości nadal kończą się zamknięciem
połączenia według reguł Werkzeug. Decyzja klienta lub serwera o zamknięciu
jest zawsze zachowana. Timeout socketu 10 s ogranicza bezczynny odczyt
oraz zablokowane I/O; nie zmienia TTL poleceń ani terminów sterowania.
Opcja działa niezależnie od profilu secure/trusted_lan. Włączenie i wyłączenie
wymaga zwykłego wdrożenia/restartu API oraz osobnego odbioru odczytów na Pi.
Nie uruchamia celów, sprzętu ani ruchu.

## Cele i przepływy

- **S12 — Opis sceny w Venomie**: istniejący capture RAW, feed i lekki klient.
  JPEG/PNG jest wysyłany bez dekodowania i ponownego kodowania na Pi. Kolejka
  odbiornika mieści dwie ramki; wybiera najnowszą. Czas RAW pochodzi z końca
  odczytu kamery, przed obróbką; nie jest timestampem ekspozycji sensora.
  Sidecar wiąże czas z tożsamością pliku. Brak zgodnych metadanych daje jawne
  `file_mtime`, nie sfabrykowany pomiar czasu capture.
- **S13 — Rozmowa przez Venom**: tylko mikrofon/lekki listener i odtwarzanie.
  Uporządkowana wypowiedź → Whisper → odpowiedź obecnego runtime → Piper WAV
  → istniejący player Pi. Bez NLU/narzędzi ruchu i bez lokalnego voice-web/modelu.
  Mikrofon jest zamykany przed inferencją; cisza nie oznacza awarii wykonawcy.

Zakończenie celu zamyka subskrypcję, HTTP, microphone/player i własną sesję.
Inny aktywny cel zachowuje swoją sesję. Współdzielone usługi kamery zatrzymuje
istniejący manager dopiero po zwolnieniu ostatniego konsumenta. Przeglądarka
nie jest potrzebna do działania uruchomionego celu.

Pojedyncze zadania bez uruchamiania sprzętu: `POST /api/compute/tasks/<task>`,
binarny body i `X-Rider-Params: {"language":"pl"}`; synteza zwraca WAV, pozostałe
zadania JSON. Awaryjnie ten sam klient:

```sh
python3 -m apps.compute capabilities
python3 -m apps.compute text --text 'Odpowiedz krótko po polsku'
python3 -m apps.compute tts --text 'Witaj' --output /tmp/rider-voice.wav
```

TTS CLI zapisuje plik, nie odtwarza go. Fizyczne nagrywanie/odtwarzanie włączają
wyłącznie jawne cele albo polecenia operatora. Automatyczne testy używają atrap.

## Odczyt i awarie

`GET /api/compute/status` jest odczytem lokalnych, ograniczonych snapshotów.
Panel modułu pokazuje wykonawcę, model, stan instalacji/konfiguracji/gotowości,
kolejkę, wiek wejścia i czas inferencji. Pierwszy job może załadować zimny model;
czas inferencji obejmuje ładowanie. Nie wyświetlamy fikcyjnego osobnego pomiaru
czasu ładowania. Język TTS musi odpowiadać wybranemu głosowi Pipera.

Gotowość pochodzi z `capabilities.tasks`, a nie z samej dostępności wykonawcy.
Snapshot głosu zapisuje faktycznie wybrane `response_task`: `text.respond`
dla R2 albo opcjonalne `conversation.respond` dla R3. Zakończony cel ma stan OFF.

Compute v1 ma tożsamość urządzenia/bootu, osobne sesje głosu/wizji, korelację
wejścia/wyniku, TTL do 60 s i ograniczoną kolejkę. Stare wyniki, restart,
zmiana modelu i OFF nie odtwarzają zadań. Saturacja/niegotowy model/transport
dają jawny błąd. Szczegółowy protokół znajduje się w module:
`docs/COMPUTE_V1.md`.

Wdrożenie zestawu Pi/moduł/core i odbiór rzeczywistej kamery/mikrofonu/głośnika
wykonuj razem po dostępności urządzenia. Sprawdzenie modeli w WSL na sztucznym
obrazie/WAV potwierdza transport i inferencję, nie jakość percepcji robota ani
reakcję napędów. Dane i logi odbioru przechowuj wyłącznie w lokalnym backlogu.


## Pętla wizja → decyzja → ruch (S14 / S15)

Konfiguracja na Pi: data/navigation_config.json, API GET/POST /api/navigation/config.
POST zawiera revision i values; zapis nie uruchamia usług. Panel /navigation i moduł
Rider w Venomie korzystają z tej samej konfiguracji.

S15 uruchamia jedynie kamerę, transport i segmentację podłogi na Venomie.
Nie wymaga ARM, nie publikuje ruchu ani STOP i nie ładuje lokalnych detektorów.
S14 wymaga mode=drive, odebranej strefy zatrzymania, identyfikatora kalibracji
oraz hash modelu. Osobny operator ARM owner=navigation z krótką timed lease
i Start celu tworzą jedną intencję. Brak automatycznego uzbrojenia/wznowienia.

Venom ma osobny model ONNX SegFormer, niezależny od LLM. To nie jest pomiar
odległości ani gwarancja wykrycia przezroczystych przeszkód lub krawędzi stopni.
Przed jazdą trzeba fizycznie odebrać strefę zatrzymania dla montażu kamery,
podłoża, oświetlenia, szybkości i modelu. Zmiana parametrów unieważnia dotychczasowy
odbiór, chyba że operator zapisze nowy identyfikator odbioru.

Pi podtrzymuje tylko krótkie impulsy. Lokalny monotoniczny watchdog i deadline
wykonawcy zatrzymują ruch bez odpowiedzi Venoma. Spóźnione/stare wyniki,
zmiana konfiguracji/uzbrojenia, ciemny obraz, awaria modelu lub brak klatek
kończą próbę. Heartbeat nie daje pozwolenia na jazdę.
Obserwuj /run/rider-motion/navigation_loop.json oraz stan celu; stare wyniki
nie są bieżącym pomiarem. Jednostki Restart=no; nie dodawać ich do boot/minimal.

Automatyczne testy używają wyłącznie atrap. Wdrożenie i próby ruchu są osobnym
odbiorem operatora; ten kod nie potwierdza fizycznego hamowania.


### Obserwacja i opóźnienia transportu

Obserwacja bez ruchu ma ograniczony do 1 s timeout odczytu HTTP, aby zwykły
jitter Wi-Fi nie kończył usługi. Nagłówek klatki nadal zawiera skonfigurowany
budżet decyzji; czas transportu nie daje żadnej zgody na ruch. Nieaktualne
klatki są pomijane tylko w obserwacji, a brak użytecznej klatki przez 5 s
kończy próbę. Jazda zachowuje swój krótki timeout, odrzucenie pierwszej
nieaktualnej klatki i termin pozwolenia egzekwowany przez Pi.


### Pierwsza klatka przy starcie próby

Po przełączeniu z podglądu na jazdę kamera może zwrócić zapis z poprzedniego uruchomienia. Runner czeka maksymalnie 5 s na pierwszą świeżą klatkę, bez wysyłania ruchu i bez resetowania tej karencji przez stare klatki. Po przyjęciu pierwszej świeżej klatki tryb jazdy zachowuje ścisły budżet decyzji; utrata świeżości lub odpowiedzi zatrzymuje i zatrzaskuje próbę. Karencja startu nie wydłuża impulsu ani terminu zgody na ruch.


### Koszt przygotowania próby jazdy
Podczas jednej transakcji przygotowania Pi odczytuje stan członków nawigacji,
alternatywnych kamer i istniejących konsumentów w ograniczonym zapytaniu systemd.
Po każdej zmianie usługi odczyt jest unieważniany. Safety i generacja sterowania
są nadal sprawdzane na świeżo, osobno od obserwacji usług.

Przed startem producenta zapisywany jest aktualny journal uprawnień i konsumentów.
Zapis nie odświeża całego katalogu nieaktywnych celów. Istniejące cele głosowe
zachowują aktualne domeny, a obserwacje niezwiązanych celów swój pierwotny czas.
Zwykły odczyt katalogu poza przygotowaniem nadal odświeża wszystkie cele.

Status przygotowania zawiera `phase_timings_ms` oraz identyfikator żądania.
Pozwala odróżnić przekroczenie budżetu przygotowania usług (15 s) lub końcowego startu po ARM (5 s) od późniejszego
zatrzymania już uruchomionej próby. Zapis ostatniej próby może dotyczyć innego
żądania i nie potwierdza uruchomienia bieżącego testu.


### Jeden start i dwa terminy wykonawcy
Polecenie próby jest sprawdzane pod kątem świeżości przy przyjęciu przez Pi.
Czas spędzony później na serializacji i odtworzeniu journalu należy już do
ograniczonego przygotowania usług (15 s; po żądaniu ARM maksymalnie 5 s do startu producenta). Po uzyskaniu blokady Pi porównuje generację,
właściciela, stan i numer ostatniego polecenia z odczytem przy przyjęciu;
nowa interakcja operatora anuluje wcześniejsze przygotowanie.

Przy nawigacji panelowej producent przekazuje dwa terminy na zegarze Pi:
- `decision_deadline_monotonic`: po nim stary obraz nigdy nie podtrzymuje ruchu;
- `decision_feedback_deadline_monotonic`: ogranicza oczekiwanie przy zerowych
  silnikach na kolejną decyzję. Jest to oryginalny termin producenta, nie nowy
  budżet liczony od odbioru przez BUS; maksymalnie 500 ms.

Koniec impulsu lub ważności obrazu zeruje silniki. Nowa świeża decyzja przed
terminem informacji zwrotnej może rozpocząć kolejny ograniczony impuls w tej
samej sesji. Brak decyzji rozbraja wykonawcę niezależnie od procesu producenta.
Żaden z tych terminów nie odnawia pierwotnego ARM (maksymalnie 10 s próby).
Bez nowego pola obowiązuje dotychczasowe rozbrojenie po ważności obrazu.
Nowy kontrakt wymaga `remote_decision_feedback_supported`; podgląd wdrożenia
musi zaktualizować także proces wykonawcy, przy rozbrojonym robocie.


### Świeża decyzja ze zbyt krótkim czasem na impuls

Jeżeli poprawnie skorelowana decyzja nadal mieści się w budżecie obrazu,
ale pozostaje mniej niż 50 ms na impuls, pętla z kontraktem feedback wysyła
wyłącznie ZERO i oczekuje na następną świeżą decyzję. Nie wydłuża starego GO.
Panel zachowuje wynik oceny obrazu, ale raportuje rzeczywiste wykonanie STOP
z powodem awaiting_fresh_decision.

Zerowy cel korzysta z dotychczasowego budżetu feedback i tej samej generacji
oraz pierwotnego terminu ARM. Nie wykonuje ponownego uzbrojenia. Brak dalszego
feedback nadal kończy próbę przez STOP; przeterminowany obraz, obca tożsamość,
niepoprawny model i nieudane wysłanie ZERO pozostają błędami terminalnymi.
Legacy bez kontraktu feedback zachowuje poprzednie zatrzaśnięcie STOP.

Regresja używa liczbowego zapisu próby zakończonej o 15:16:11: obraz miał
296 ms przy budżecie 300 ms. Poprzedni kod kończył próbę pomimo GO; nowy
nie nadaje tej klatce żadnego niezerowego wyjścia. Scenariusz kolejnego
świeżego GO w teście sprawdza możliwość kontynuacji, a nie odtwarza
niezarejestrowanego fizycznego przejazdu.


### Odbiór operatora — 2026-10-15

Operator potwierdził stabilność procesu w bieżącej skalibrowanej scenie
na rzeczywistym Rider-Pi po poprawce krótkiego permitu. Zakres można wydać
dla tej sceny i obecnych ograniczonych parametrów. Historyczna awaria
z 15:16:11 pozostaje fixture regresji, a nie opisem aktualnego odbioru.
Zmiana sceny, oświetlenia lub montażu kamery wymaga ponownej oceny warunków.
Nie potwierdzamy metrycznej drogi hamowania ani uniwersalnej jakości percepcji.


[Directional vision / Nawigacja kierunkowa](DIRECTIONAL_NAVIGATION.md)
