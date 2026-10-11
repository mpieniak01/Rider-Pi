# Opcjonalny sniffer UART

Obserwator korzysta z istniejącego właściciela UART. Nie otwiera drugiego portu,
nie odpytuje rejestrów, nie wysyła poleceń i nie zmienia uzbrojenia.
Domyślnie zapis jest wyłączony. Sterowanie wymaga tego samego użytkownika systemu.

## Podłączanie i odłączanie

Po załadowaniu nowego adaptera przez wykonawcę przy jego następnym uruchomieniu:

~~~sh
python3 scripts/uart_sniffer.py list
python3 scripts/uart_sniffer.py attach --pid PID --seconds 60
python3 scripts/uart_sniffer.py status --pid PID
python3 scripts/uart_sniffer.py detach --pid PID
~~~

Attach rozpoczyna zapis; detach kończy sesję i zamyka plik.
Lekki obserwator pozostaje w procesie bez zapisu, aby umożliwić ponowne podłączenie.
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
python3 /home/pi/robot/scripts/uart_sniffer_vendor.py --operator-session /home/pi/RaspberryPi-CM4-main/app/app_TwoCar.py
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
Sniffer można całkowicie usunąć z przyszłych uruchomień, usuwając instalację
obserwatora w adapterze; odłączenie sesji nie wymaga restartu.
Wdrożenie adaptera do już działającego wykonawcy wymaga jego kontrolowanego restartu.
