# Panel operatora

Panel korzysta z jednego katalogu `GET /api/logic/catalog` w wersji 2.
Zadania, opcje domen, członkowie usług i konsumenci zasobów pochodzą z API.
Brak katalogu albo jego starsza wersja oznacza odczyt i blokadę uruchamiania.

## Widoki

| Widok | Dane i działania |
| --- | --- |
| Przegląd `/view` | Pełny pulpit Rider-Pi: system, urządzenia, historia CPU/RAM, kondycja BUS, przeszkoda i histogram ROI, RAW/PROC/OBST/TRACKER, metryki API i wiek obrazów. Zadania i blokady uzupełniają pomiary. |
| Zadania i sterowanie `/control` | Katalog, jawna zgoda operatora, krótkie impulsy, możliwości napędów, żądania i ACK. |
| Urządzenia `/devices` | Właściciele procesów, konsumenci zadań, kamera, audio, LCD i UART. Podgląd obrazu na życzenie. |
| System `/system` | Odczyt usług i zależności. Administracja włączana jawnie w bieżącej karcie. Autostart zmieniany oddzielnie. |
| Nawigacja `/navigation` | Mapa, pozycja, wiek i jakość danych; jawne start/powrót i konfiguracja w DISARMED. |
| Chat `/chat` | Wybrana domena AI i opcjonalne TTS. Dopiero wysłanie wiadomości przygotowuje potrzebną domenę. |

Otwarcie widoku, karty, listy providerów lub odświeżenie danych nie uruchamia
usług ani napędów. Wybór opcji również nie uruchamia zadania. Jawny przycisk
zadania lub wysłanie wiadomości stanowi oddzielne żądanie.

## Pełny pulpit pomiarowy

Nagłówek zawiera nazwę urządzenia i „Przegląd”. Karty pomiarowe, oba wykresy
oraz cztery podglądy obrazów są widoczne bez otwierania szczegółów i bez
przechodzenia do Systemu. Układ ma cztery kolumny na szerokim ekranie,
dwie na węższym i jedną na telefonie. Rozbudowa bezpieczeństwa, katalogu
zadań lub kalibracji zachowuje te funkcje.

`/sysinfo` dostarcza płaskie pola CPU, obciążenia 1/5/15 min, RAM, dysku,
temperatury i historii. MB/GB w nazwach API oznaczają MiB/GiB. Historia
obejmuje najwyżej 60 próbek, a nie gwarantowane 60 sekund. Brak wartości
tworzy przerwę w wykresie; zero pozostaje pomiarem.

`/state.devices.xgo` dostarcza obserwację IMU i baterii; pole `on` nie jest
wymagane. Wiek oraz flagi źródła decydują o przydatności pomiaru. Kanały
`safety.sensor_quality.sensors` mają oddzielne czasy i jakość: bateria w tym
kontrakcie jest proporcją 0–1, natomiast `battery_pct` już procentem.
Orientacja IMU nie jest pozycją robota. Surowy yaw SDK ma osobny opis
niezweryfikowanej semantyki fizycznej. Samo `healthz: ok` potwierdza API,
nie sprawność wszystkich czujników.

Przegląd odczytuje telemetrię co sekundę, pozostałe pomiary i metadane obrazów co około 2 sekundy. Wariant
`/vision/snap-info?light=1` korzysta ze statystyki pliku bez czytania obrazu
do wyliczenia MD5. Podgląd pobiera wyłącznie świeżą klatkę aktywnej kamery.
Wyłączona kamera, brak obrazu i stary cache mają jawne etykiety; otwarcie
pulpitu nie uruchamia żadnego producenta ani zadania. System pokazuje
podstawowe pomiary przed listą usług; surowy JSON pozostaje w szczegółach.

## Ruch i potwierdzenia

`GET /api/control/state` dostarcza `safety.contract_version = 1`.
Brak świeżego stanu, `UNKNOWN`, niezgodny właściciel, wygasła zgoda lub
niepotwierdzone `available`/`stop_verified` blokują napędy. `DISARMED` i
`ESTOP` mają `read_only: true`; jawne ARM i kasowanie ESTOP korzystają
z osobnych reguł przygotowania. ARM wymaga też hardware_ready i ready. Kasowanie ESTOP wraca do DISARMED.

ARM wymaga konkretnego planu, potwierdzenia przygotowania robota, wybranego
właściciela i zgody najwyżej na 30 sekund. Nie ma automatycznego uzbrajania
po wejściu do widoku ani po ponownym połączeniu. Dla robota zasilanego
przewodem operator musi zapewnić przestrzeń i zabezpieczyć kabel. Karty
bezpieczeństwa w Nawigacji i Systemie mają ten sam jawny formularz; opuszczenie
widoku unieważnia zgodę, więc przygotuj ją na stronie wykonania.

Każde kliknięcie napędu, ARM lub kasowania ESTOP tworzy jedną kopertę:
`request_id`, `generation`, rosnące `seq`, `source`, `ts`, `ttl_ms <= 500`.
Panel nie ponawia automatycznie mutacji i nie odnawia metadanych starego
żądania. Ręczny impuls ma czas najwyżej 0.25 sekundy.

Odpowiedź `server_time` jest czasem serwera API, oddzielnym od czasu pomiaru
`observed_at`. Panel uzgadnia zegar przy odczycie safety; czas polecenia
wykorzystuje dolną granicę, a wiek pomiaru górną granicę opóźnienia sieci.
Niepotwierdzony zegar lub RTT ponad 500 ms blokuje nowe polecenia ruchu.
STOP nie zależy od tego uzgodnienia.

Historia żądań pozostaje oddzielna od stanu wykonawcy. `pending` oznacza
oczekiwanie. Tylko dopasowany terminalny ACK zmienia żądanie na `executed`
lub `rejected`. `executed` oznacza przyjęcie przez SDK; fizyczne zakończenie
pozostaje `unverified`. Brak ACK przechodzi w `unknown`, bez domyślnego sukcesu.

Nawigacja dopasowuje osobno stan zadania do oryginalnych `request_id`
i `generation`. Potwierdzenie pracy zadania nie jest ACK wykonania napędów.
Odpowiedź uruchomienia domeny Chat z `starting` lub `partial` nie zezwala
jeszcze na wysłanie treści: potrzebne jest świeże `ready` odpowiedniej domeny.
Błąd producenta jest widoczny w karcie i szczegółach, a echo ani zastępczy
dźwięk nie potwierdzają działania AI/TTS.

Wysokość, balans i gotowe akcje pozostają widoczne. Stan
`manual_characterization_required` jawnie blokuje ich wywołanie, dopóki
procedura ręczna nie potwierdzi sposobu przerwania ruchu. Pola parametrów
oznaczają proponowane żądanie, nie pomiar postawy robota.

STOP jest stale dostępny i nie wymaga metadanych bezpieczeństwa. Skróty
W/S/A/D i strzałki działają tylko w Sterowaniu, poza polami edycji, bez
powtarzania klawisza i przy aktualnej zgodzie właściciela `manual`.
Spacja wysyła STOP poza polami. Utrata połączenia, fokusu lub ukrycie karty
wyłącza lokalną możliwość ruchu i próbuje wysłać STOP. Jeśli połączenie
zniknęło, zatrzymanie fizyczne nie jest deklarowane jako potwierdzone.
Unieważniona lokalnie generacja nie odzyskuje zgody po ponownym odczycie
tego samego ARMED; potrzebne są STOP i jawne nowe uzbrojenie.

## Urządzenia i obciążenie

RAW/PROC/SSD/TRACKER oznaczają rodzaj klatki. `capture` oznacza proces
trzymający kamerę, a URL źródło istniejącego obrazu. Wyłączenie odświeżania
obrazu nie zatrzymuje kamery ani zadania. Zmiana URL nie przejmuje kamery.
Dozwolone są lokalne adresy HTTP tego samego hosta pod `/camera/`, `/vision/`
i `/snapshots/`. Klient pokazuje wiek na podstawie czasu klatki. Wiek metadanych
i klatki faktycznie wczytanej jest oddzielony; stary obraz zostaje przygaszony.

Odczyty mają jeden aktywny request na adres, timeout, ograniczony backoff
i pauzę w ukrytej karcie. Safety odczytywane jest raz na sekundę, katalog
i System co 5 sekund, telemetria urządzeń co sekundę, właściciele urządzeń
co 10 sekund. Obraz urządzeń pobierany jest pojedynczo na żądanie lub z włączonym
podglądem co 2 sekundy; Przegląd odświeża świeże obrazy aktywnych producentów.
SSE aktualizuje rzeczywiste zdarzenia i zachowuje czas producenta;
brak strumienia pozostawia okresowy odczyt. Zero jest prawidłowym pomiarem,
`null` pozostaje nieznane. Stary pomiar nie staje się świeży przez polling.

Jeden wykonawca posiada UART i publikuje telemetrię przez BUS. Ekran LCD
jest zamontowany bokiem; zachowujemy kompensację 270°, rozruch, SSH i Wi-Fi.

## Administracja i odzyskanie zasobu

System domyślnie służy do odczytu. Jawne włączenie administracji odsłania
działania `start`/`stop`/`restart`. `enable`/`disable` zmienia autostart
osobno; API nie pozwala włączyć autostartu usług na żądanie. Zależności,
konsumenci i przyczyna odmowy są widoczne.

Ostatnie logi są odczytywane dopiero po kliknięciu przy danej usłudze.
Endpoint dziennika przyjmuje tylko unity ze wspólnego katalogu, bez shell
ani sudo; limit wynosi 50 linii, 64 KiB i dwie sekundy. Brak uprawnień
pozostaje nieznany. CPU, RAM, dysk, temperatura, Git i graf są w szczegółach.

Najpierw STOP, zakończenie zadania i zwykłe zatrzymanie właściciela.
Wymuszone zwolnienie jest oddzielną ręczną procedurą: świeży odczyt
właścicieli, wybór konkretnych PID, wpisanie nazwy zasobu i osobna zgoda.
Backend chroni usługi bazowe, UART i LCD. Nie ma automatycznego odzyskiwania.


### Tracker pasywny

S6 wybiera `face`, `hand` albo `none` z `option_schema` katalogu. Sam wybór
nie wykonuje żądania; osobny przycisk uruchamia lub kończy obserwację. S6
nie uruchamia kontrolera ruchu i nie zapisuje zgody na napędy. Inny tryb
aktywnego Follow Me powoduje `409` i `blocked_by`; operator kończy poprzednie
zadanie przed zmianą trybu. Zakończenie S6 zachowuje tracker i tryb potrzebny
pozostałym konsumentom. Dawny `/vision/tracking/mode` oraz jego alias `/api`
korzystają z tej samej orkiestracji; GET służy wyłącznie do odczytu.

### Jakość prezentacji

`observed_at`, jawne `stale`/`offline`, błędy i gotowość danych przechodzą
przez API do panelu. Błąd z nowym czasem publikacji nie oznacza dobrego
pomiaru; `null` lub niepoprawny pakiet unieważnia poprzednią geometrię.
Zmiana jakości przy tym samym czasie odświeża rysunek. Poprawny starszy
pomiar nie nadpisuje nowszego, lecz jawna informacja o awarii wygasza zdrowy
wygląd. Świeży status zadania FAILED/IDLE pozostaje widoczny niezależnie
od gotowości mapy. Zero jest zachowane także dla baterii. Nawigacja odczytuje
ograniczony cache mapy, pozycji i ścieżki z `/state` oraz `/api/navigator/status`;
odczyt nie odświeża czasu źródła ani nie uruchamia producentów.

## Weryfikacja bez robota

```bash
node --experimental-vm-modules --test tests/operator_panel.test.mjs tests/operator_panel_shared_review.test.mjs tests/legacy_catalog.test.mjs
RIDER_TEST_ISOLATED=1 .venv/bin/python -m pytest --noconftest -q tests/test_operator_event_cursor.py tests/test_operator_navigation_state.py tests/test_operator_service_logs.py
.venv/bin/python tests/operator_fixture_server.py
```

Serwer fixture działa wyłącznie na loopback, używa stdlib i danych w pamięci.
Nie importuje API robota, SDK, BUS ani systemd. Wypisuje lokalny URL.
Automatyczne testy nie są upoważnieniem do ruchu fizycznego. Test sprzętowy
napędów wymaga osobnej świadomej zgody przygotowanego operatora.
