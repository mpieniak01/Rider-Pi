# Opcjonalny sniffer UART

Obserwator korzysta z istniejącego właściciela UART. Nie otwiera drugiego portu,
nie odpytuje rejestrów, nie wysyła poleceń i nie zmienia uzbrojenia.
Domyślnie cały sniffer jest wyłączony: `RIDER_UART_SNIFFER_ENABLED=0`.
Adapter korzysta wtedy bezpośrednio z serial, bez wrappera, kolejki, gniazda
i wątku obserwatora. Sterowanie wymaga tego samego użytkownika systemu.

## Przełącznik uruchomienia

`RIDER_UART_SNIFFER_ENABLED=1` w środowisku właściciela UART włącza możliwość
podłączania sniffera; tylko dokładna wartość `1` ją włącza.
Zmienna jest odczytywana przy tworzeniu adaptera. Zmiana wymaga ponownego
uruchomienia właściciela; nie restartuj go bez uwzględnienia stanu i decyzji
operatora o rozbrojeniu. Dla usługi ustaw ją w środowisku
`motion-executor.service`; eksport w terminalu klienta nie zmienia środowiska
już działającej usługi.

Przy `0` lub braku zmiennej nie ma gniazda sniffera i `list` nie pokaże tego
właściciela. Kod dekodera i analizatora pozostaje dostępny offline.
Po uruchomieniu z `1` zapis nadal jest wyłączony aż do jawnego `attach`.

## Podłączanie i odłączanie

Po uruchomieniu właściciela UART z `RIDER_UART_SNIFFER_ENABLED=1`:

~~~sh
python3 scripts/uart_sniffer.py list
python3 scripts/uart_sniffer.py attach --pid PID --seconds 60
python3 scripts/uart_sniffer.py status --pid PID
python3 scripts/uart_sniffer.py detach --pid PID
~~~

Attach rozpoczyna zapis; detach kończy sesję i zamyka plik.
Przy włączonym przełączniku obserwator pozostaje w procesie bez zapisu,
aby umożliwić ponowne podłączenie.
Komendy nie uruchamiają ani nie restartują wykonawcy. Po restarcie zapis jest wyłączony.
Nie uruchamiaj drugiego czytnika /dev/ttyAMA0.

Status zwraca dokładną ścieżkę pliku. Pliki mają uprawnienia 600 w prywatnym katalogu
/tmp/rider-uart-sniffer-UID/. Sesja trwa 1–300 sekund i ma limit 8 MiB.
Przekroczenie limitu automatycznie kończy zapis. Bufor mieści 1024 zdarzenia;
przepełnienie powoduje utratę wpisów, nie blokuje UART. Końcowy wpis podaje
liczbę pominiętych zdarzeń, również tych pozostałych w kolejce przy odłączeniu.
Pliki pozostają po sesji: skopiuj potrzebne na WSL i usuń zbędne ręcznie.
Wiele sesji nie ma wspólnego limitu dysku ani automatycznej rotacji.

## Dekodowanie na WSL

~~~sh
python3 scripts/uart_sniffer.py decode capture.jsonl > frames.jsonl
~~~

Dekoder łączy fragmenty ramek, sprawdza długość i checksum oraz pokazuje adres,
tryb i surowe dane. Nazwy rejestrów odpowiadają sprawdzonemu SDK 1.4.2.
Nieznane adresy pozostają unknown. Zapis nie potwierdza fizycznego wykonania ruchu.
Czas ramki to czas ostatniego fragmentu obserwowanego przez aplikację,
nie czas każdego bajtu na przewodzie. TX opisuje bajty przyjęte przez serial.write,
nie dowodzi ich odbioru przez firmware. Błędy read/write są rejestrowane i przekazywane
właścicielowi bez zmiany ich obsługi.

FlushInput / reset_input_buffer oznacza lukę: usuniętych bajtów nie odczytujemy.
Protokół nie ma identyfikatorów żądań; opóźnione odpowiedzi na identyczne odczyty
mogą być niejednoznaczne. Sniffer Rider-Pi obejmuje ruch i istniejące odczyty czujników;
nie przechwytuje HTTP i nie wiąże ramek z identyfikatorem żądania panelu.
Adapter instaluje obserwator po konstruktorze SDK, więc pierwsze odczyty konstruktora
nie są rejestrowane. Pełny zapis elektryczny wymaga zewnętrznego analizatora.

## Aplikacja dostawcy — sesja operatora

Najpierw zakończ bieżącego właściciela UART normalną procedurą.
Poniższa komenda wykonuje oryginalną aplikację: inicjalizacja może zmienić
pozycję lub wywołać ruch. Nie uruchamiać w CI ani w testach jednostkowych.

~~~sh
RIDER_UART_SNIFFER_ENABLED=1 python3 /home/pi/robot/scripts/uart_sniffer_vendor.py --operator-session /home/pi/RaspberryPi-CM4-main/app/app_TwoCar.py
~~~

Użyj dotychczasowego katalogu roboczego oraz interpretera aplikacji dostawcy.
W drugim terminalu uruchom list / attach / status / detach z repo Rider-Pi.
Launcher obserwuje /dev/ttyAMA0; nie zmienia plików SDK ani globalnych pakietów.
Ruch aplikacji dostawcy nie jest chroniony bramą Rider-Pi.
Polecenia wykonane przed ręcznym attach nie trafią do zapisu.

## Narzut i zakres wdrożenia

Jeden wątek tła obsługuje lokalne gniazdo i plik. W ścieżce UART pozostaje
sprawdzenie aktywności i nieblokująca próba dodania wpisu do kolejki.
To obserwacja programowa, nie gwarancja zerowego narzutu czasowego.
Błędy rejestratora nie mogą zmienić wyniku odczytu / zapisu UART.
Całkowite wyłączenie w przyszłych uruchomieniach wymaga tylko
`RIDER_UART_SNIFFER_ENABLED=0`, bez usuwania kodu. `detach` wyłącza zapis
bieżącej sesji bez restartu; nie usuwa wrappera ani wątku z już działającego procesu.
Wdrożenie adaptera do już działającego wykonawcy wymaga jego kontrolowanego restartu.


## Rozszerzony raport — bez dodatkowych odczytów sprzętu

~~~sh
python3 scripts/uart_sniffer.py decode capture.jsonl --firmware R-1.1.6 > frames.jsonl
python3 scripts/uart_sniffer.py analyze capture.jsonl --firmware R-1.1.6 \
  --output report.json --markdown report.md
~~~

Raport pokazuje:
- ACTION: numer i nazwa według dokumentacji, wykonanie w firmware;
- PERFORM i BALANCE: wysłany przełącznik, nie odczyt stanu;
- HEIGHT / ROLL_SETPOINT: bajt i odwzorowanie SDK, nie pozycja zmierzona;
- PERIODIC_ROLL / PERIODIC_HEIGHT: włączenie i okres według SDK;
- VX / VY / VYAW: bajt neutralny 128 i odchylenie; bez pozornej prędkości fizycznej;
- pakiet IMU 0x65: XYZ z grawitacją oraz osobne kąty dla potwierdzonego R-1.1.6;
- odpowiedzi baterii, stanu pracy i firmware;
- pełną oś czasu, zmiany nastaw, rozkład odstępów zapisu i zakresy czujników;
- odczyt → odpowiedź, długość i adres oraz opóźnienie obserwowane w serial;
- braki odpowiedzi, ramki błędne, odpowiedzi bez pary i przerwy obserwacji.

Domyślne okno parowania to 100 ms, edytowane przez --response-timeout-ms.
To okno analizy, nie timeout sterowania. Parowanie po adresie i długości jest
wnioskowaniem. Nakładające się identyczne żądania oznaczamy jako ambiguous.
Opóźniona odpowiedź starego, identycznego odczytu może wyglądać jak nowa:
nie ma identyfikatora, więc raport nie twierdzi, że to ścisłe potwierdzenie.

Format firmware jest rozpoznawany z obserwowanej odpowiedzi 0x07 lub jawnego
--firmware. Wcześniejsze pakiety bez potwierdzonego formatu pozostają surowe.
Nazwy akcji pochodzą z dokumentacji; nie dowodzą zgodności każdej płytki.
Zapis polecenia ani upływ ActionTime nie potwierdza fizycznego zakończenia.

## Głębiej niż UART Pi → kontroler

Warstwa 1: istniejący SerialTap — wywołania aplikacji, bez pełnego śladu przewodu.
Warstwa 2: zewnętrzny analizator na UART Pi/kontroler — także bajty odrzucone
przez flush, rzeczywiste czasy oraz ruch poza aplikacją.
Warstwa 3: osobna magistrala kontroler/napędy — dopiero tu można zobaczyć
polecenia wewnętrzne, o ile interfejs da się pasywnie przechwycić.
Warstwa 4: kod/debug firmware — wewnętrzny regulator, wybór figury i trajektorie.

Warstwy 2/3 wymagają ustalenia pinów, napięć, rodzaju interfejsu oraz kierunków
z właściwego schematu i płytki. Nie zakładaj UART/RS485/CAN ani poziomów
elektrycznych na podstawie nazwy złącza. Sniffer programowy nie otwiera
drugiego portu i nie zapisuje konfiguracji kontrolera.

Analizator offline można zasilić eksportem z zewnętrznego przechwytywania:
JSONL z direction tx/rx, hex (bajty), time_ns (monotoniczne czasy), opcjonalnie
event start/end oraz direction gap. Kierunki odnoszą się do badanego hosta.
Dekoder XGO ma zastosowanie tylko wtedy, gdy na tym interfejsie rzeczywiście
obserwujemy ramki XGO; wewnętrzna magistrala może mieć inny protokół.
W raporcie zachowaj pochodzenie pomiaru i nie traktuj eksportu elektrycznego
jak obserwacji SerialTap.

External XGO export example / Przykład zewnętrznego eksportu XGO:

~~~sh
python3 scripts/uart_sniffer.py analyze wire.jsonl --source wire_export --firmware R-1.1.6 --output wire-report.json
~~~
