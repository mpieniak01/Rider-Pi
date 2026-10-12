# Obliczenia i percepcja w Venomie

Pi pozostaje właścicielem kamery, audio, kalibracji i ruchu. Venom wykonuje
tekst, STT/TTS i **opis sceny**. Opis nie jest detektorem przeszkód ani zgodą
na przejazd. Wyniki obliczeń nie trafiają do poleceń ruchu; ARM i STOP pozostają
niezależne. Opcjonalne narzędzia czatu do sterowania robotem należą do R3.

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

Token wymaga HTTPS z weryfikowanym certyfikatem albo lokalnego endpointu
`http://localhost:<port>`, `http://127.0.0.1:<port>` lub `http://[::1]:<port>`
prowadzącego przez tunel SSH. HTTP po sieci lokalnej jest odrzucane także przez
klienta transportu. TLS/tunel na urządzeniu pozostaje do przygotowania przed
odbiorem sprzętowym; ta zmiana nie konfiguruje go automatycznie.

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
