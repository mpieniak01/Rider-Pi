# Dostawca i model percepcji

Panel nawigacji Rider-Pi rozdziela wybór dostawcy analizy obrazu od wyboru
modelu. Odczyt i wybór nie uruchamiają ruchu. Kamera wyłączona przed wyborem
pozostaje wyłączona.

## Właściciele konfiguracji

| Informacja | Źródło prawdy |
| --- | --- |
| Dostawca `local` / `venom`, lokalny silnik, transport obrazu | Istniejący `data/camera_pipeline.json`, `profile.analysis_location/local_engine/remote_transport` i jego `revision` |
| Wagi Venom, instalacja, dostępność, załadowany model | Katalog i runtime modułu Rider na hoście Venom |
| Wybrany model hostowy oraz odcisk artefaktu | `data/navigation_config.json`, `perception.model_id/artifact_sha256` i rewizja konfiguracji |
| Możliwość ruchu | Istniejący wykonawca ruchu Pi, aktualny ARM i osobny odbiór |

Pi nie przechowuje kopii katalogu ani wag Venom. Wybór dostawcy nie zmienia
wyboru silnika głosu lub tekstu. Oba panele odczytują tę samą konfigurację Pi;
panel Rider-Pi odświeża wybór automatycznie. Stan „wybrany” i stan „aktywny”
pozostają odrębne, również przy wyłączonej kamerze lub niedostępnym hoście.

Lokalne opcje pochodzą z istniejącego toru kamery:
`local-canny` (OpenCV, bez wag), `local-ssd` (MobileNet SSD) oraz
`local-tflite` (EfficientDet Lite0). Endpoint odczytuje rzeczywiste pliki
wskazane przez `SSD_MODEL_DIR` i `TFLITE_MODEL` oraz istniejące capabilities.
Nie pobiera pakietów i nie ładuje modeli. Canny wyznacza krawędzie, a SSD/TFLite
wykrywają obiekty; nie deklarujemy dla nich segmentacji podłogi ani zgodności
z kontraktem hostowej pętli nawigacji. Dotychczasowe lokalne scenariusze pozostają
w istniejących aplikacjach i zachowują własny kontrakt bezpieczeństwa.

## API

Odpowiedzi obsługują istniejącą kopertę `rider.navigation_loop`, wersja 1.

- `GET /api/navigation/models`: świeży katalog Venom przez wybrany compute
  endpoint. Brak hosta daje błąd; Pi nie pokazuje starej listy jako gotowej.
- `GET /api/navigation/local-models`: lokalne silniki, dostępność, pliki
  bazowe i odciski bez prywatnych ścieżek; wybrany i aktywny model lokalny,
  dostawca oraz rewizja pipeline. Nie wywołuje Venom.
- `POST /api/navigation/model`: `{"revision": 7, "model_id": "segformer-b0-ade20k"}`.
  Przekazuje intencję do hosta. Host kwalifikuje artefakt; klient nie podaje URL,
  ścieżki ani własnego odcisku.
- `POST /api/navigation/model-selection`: wewnętrzne zatwierdzenie przez hosta:
  `{"revision": 7, "model_id": "segformer-b0-ade20k", "artifact_sha256": "<64 hex>", "engine": "segformer"}`.
  Atomowy zapis CAS zwraca `{ok,persisted,config}`.
- Dostawca i lokalny silnik nadal korzystają z
  `POST /api/resource/camera/pipeline`, `action=configure`, aktualnego
  `expected_revision`, świeżego `request_id` i pełnego istniejącego profilu.

Proxy używa wyłącznie skonfigurowanego adresu i poświadczeń compute:
`GET /api/v1/rider/compute/vision/models` oraz
`POST /api/v1/rider/compute/vision/model`. Poświadczenia pozostają na serwerze.
Żaden endpoint katalogu nie utrwala listy ani nie uruchamia instalacji.

## Zmiana i bezpieczeństwo

Przed zmianą modelu, dostawcy lub lokalnego silnika operator rozbraja robota
i zatrzymuje pętle S14/S15 oraz zadania ruchowe. Sama kamera może pozostać
włączona. Brak świeżego stanu wykonawcy albo wiarygodnego dziennika celów nie
jest dowodem bezczynności. Odmowa nie zatrzymuje automatycznie usług.

Zapis modelu i zmiana dostawcy korzystają z istniejącej transakcji celów
i mutexu ustawień współdzielonego z jedynym wykonawcą ruchu. Równoległy ARM
nie może wejść w transakcję zapisu; STOP/EStop nie czekają na ten mutex.
Każda rzeczywista zmiana czyści `verified`, `calibration_id`,
zatwierdzone `model_sha256` i `sweep_verified`, ustawia `mode=observe`.
Zmiana samego modelu Venom nie restartuje kamery. Zmiana dostawcy lub lokalnego
silnika może przebudować istniejący tor kamery i zachować wyłącznie wcześniejsze
żądanie podglądu, bez odtwarzania analizy lub sterowania.

Zwykły zapis `/api/navigation/config` nie może podmienić ani usunąć jawnej
tożsamości modelu z pominięciem selekcji. Nowe jawne wybory segmenterów
(SegFormer, Fast-SCNN, YOLO semantic) są obserwacyjne także w końcowej bramie Pi.
Depth Anything V2 może uzyskać zgodę dopiero po odrębnym odbiorze dokładnie
wybranego artefaktu. Stare konfiguracje bez nowej tożsamości zachowują zgodność.

Każde żądanie z jawnym modelem przenosi jego ID i SHA w `perception`.
Odpowiedź musi potwierdzać tę samą tożsamość, rewizję, run, klatkę i sekwencję;
niezgodna odpowiedź nie trafia do aktualnego wyniku ani aktuatorów.
Powtórzenie zatwierdzenia po utracie ACK jest bezskutkowe i zwraca ten sam stan,
jeżeli tożsamość i wyzerowany odbiór nadal są identyczne. Inna stara rewizja
zwraca konflikt; klient odczytuje świeży stan i nie ponawia zapisu automatycznie.

## Powrót i odbiór

Na aktualnym kodzie wybierz poprzedni gotowy model oraz, w razie potrzeby,
poprzedni profil kamery z aktualnymi rewizjami. Powrót zachowuje obserwację
i nie przywraca zgody na ruch. Przed powrotem do starszego kodu Pi, który nie
zna nowych pól, trzeba w kontrolowanej transakcji usunąć opcjonalną tożsamość
z konfiguracji po zatrzymaniu pętli i potwierdzeniu DISARMED. Nie przywracaj
starej kopii konfiguracji zawierającej odbiór jazdy.

Automatyczne testy używają plików tymczasowych, atrapy transportu i silników
w pamięci. Odbiór operatorski sprawdza zgodność obu paneli, kamerę OFF/ON,
blokadę zmiany przy sterowaniu oraz brak starego wyniku po przełączeniu.
Ruch wymaga oddzielnej zgody operatora na konkretną próbę.

## Tożsamość obrazu lokalnego

W zarządzanym torze kamery `/camera/proc` czyta wyłącznie wynik z RAM;
nie wraca do starych plików JPEG. Producent przetworzonego obrazu dołącza
`local_engine`, `model_id=local-<engine>` i `analysis_location=local`
do tych samych metadanych co klatka (sesja, epoch, rewizja i czas przechwycenia).
API odrzuca wynik starszej konfiguracji lub innego silnika.
`X-Rider-Source-Json` zachowuje te pola, a nagłówki
`X-Rider-Local-Engine` i `X-Rider-Local-Model-Id` są ich projekcją.
RAW nie otrzymuje tożsamości modelu. Po zamknięciu producenta bufor jest pusty.
Panel nadal odrzuca odpowiedzi z poprzedniej sesji/epoch, także po restarcie
tego samego profilu; czas odczytu HTTP nie zastępuje czasu przechwycenia.


Powiązane: [profile nawigacji i SLOW](navigation-profiles.md).
