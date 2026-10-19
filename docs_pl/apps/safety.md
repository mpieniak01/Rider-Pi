# Bezpieczeństwo fizycznego robota

Lekki robot ma bezwładność, równowagę i drogę hamowania. Zgoda programowa oraz
ACK SDK nie są dowodem fizycznego wykonania.

## Kategorie testów

- Pełne automatyczne testy i E2E działają w WSL/CI. Izolacja przed kolekcją
  odcina SDK, urządzenia, produkcyjny BUS, robot, mutacje usług i subprocessy.
  Mock sprzętu jest jawny; hardware/physical_motion nie uruchamia realnego testu.
- Na Pi sprawdzamy wybrane funkcje bez ruchu: kamerę, LCD, telemetrię.
  Diagnostyka nie uzbraja bramy, nie czyści E-Stop i nie uruchamia autonomii.
- Jazda, obrót, wysokość, balans, akcje i autonomia wymagają ręcznej zgody
  operatora na konkretną próbę. Nigdy nie uruchamiają ich pytest/E2E/CI,
  wdrożenie, harmonogram lub wejście na stronę.

Zgoda na kamerę, usługę, instalację WSL czy deploy nie jest zgodą na ruch.
Pakiety: [polityka środowisk](../POLITYKA_SRODOWISK.md).

## Operator i kabel

Robot w development może być na kablu. Traktuj go jako niegotowy do ruchu
do potwierdzenia przygotowania. Przed KAŻDĄ próbą opisz aktuator, kierunek,
prędkość znormalizowaną i czas. Operator potwierdza wolne miejsce, podłoże,
kabel i przygotowany STOP. Sprawdź wersję, ownera UART i świeży stan bramy.
Jedna krótka ręczna próba, potem STOP, ocena fizycznego stanu i notatka.
Kolejna próba wymaga nowej zgody. Nie podnoś limitów dla wygody diagnozy.

## Mechanizmy

Jedna brama DISARMED/ARMED/ESTOP obejmuje wszystkie aktuatory. Owner i lease
ograniczają zgodę; generation/seq/ts/TTL odrzucają stare i cudze komendy.
Task intent uniemożliwia staremu follow/nav przejęcie nowego ARM.
Lock i rzeczywisty owner UART wykluczają drugiego SDK. Guard SDK blokuje reset
konstruktora. MOTION_ENABLE=0 jest dodatkowym wetem. E-Stop flag/GPIO zatrzaskuje
blokadę; błąd zapisu nie przerywa STOP w pamięci i jest persistence_error.
Błąd UART/STOP obniża readiness i blokuje następny ARM.

Sam DRY_RUN/BRIDGE_READONLY/nazwa profilu/kod HTTP nie dowodzi globalnej blokady.
confirmed STOP wymaga terminalnego ACK; physical_completion jest unverified.
Height/balance/actions pozostają zablokowane do ręcznej charakterystyki przerwania.

## Polecenia

make safety-status i diag_motion-status.py tylko odczytują.
make safemode / sys_emergency-stop.py on wymagają ACK E-Stop.
make stop-all wymaga confirmed STOP przed zatrzymaniem usług aplikacji.
manual_motion-probe.py wymaga interaktywnego terminala, planu i wpisanego
jednorazowego tokena; jedna próba, STOP w finally. Odmawia w CI/pytest i dla
niezweryfikowanego capability. Dawne automatyczne burst/cascade/move smokes/demo
są wyłączone. Clear E-Stop ma osobną zgodę i pozostawia DISARMED, bez odtwarzania.
Diagnostyka i deploy nie usuwają flag.

## Granice

SIGTERM uruchamia cleanup. SIGKILL, utrata UART lub zasilania Pi nie mają dowodu
fizycznego zatrzymania. Firmware może zachować ostatni cel; lease procesu Pi nie
jest niezależnym zabezpieczeniem sprzętu. Ręczna charakterystyka jest konieczna.
Zobacz [architekturę](motion.md). Zachowuj LCD 270°, boot, Wi-Fi i SSH.


## Walidacja poleceń i dowodów wykonania

API i brama wykonawcy walidują polecenie etapami: tożsamość panelu,
generacja/sekwencja i świeżość, kontekst wykonania, zgoda oraz parametry
aktuatora. Niepoprawne typy JSON i liczby przekraczające zakres konwersji
są odmową walidacji, bez zużywania sekwencji lub zmiany zgody. Timestamp
polecenia na BUS jest liczbą JSON, a nie tekstem. STOP i E-Stop zachowują
swój priorytet; jawny `expected_generation` nadal ogranicza konkretny STOP.
Ponowne ARM w tej samej sesji nie przedłuża dzierżawy zgody.

Snapshot wymaga całkowitego `contract_version` i liczbowego, skończonego
`observed_at`; wartości logiczne nie zastępują liczb. Niepoprawny limit
wieku obserwacji zwraca UNKNOWN. Przeterminowany snapshot może nadal
pokazywać historyczną zgodę operatora, ale `can_move` i potwierdzenie
świeżej autoryzacji pozostają wyłączone.

Dopasowany ACK musi dotyczyć tego samego request/action/source, generacji
oraz sekwencji o właściwym typie. Jego czas obserwacji musi być skończony
i nie wcześniejszy niż wysłanie polecenia. Sprzeczne pary status/accepted
nie potwierdzają wykonania; uszkodzony wpis historii nie zasłania późniejszego
poprawnego ACK. Brak wiarygodnego dowodu pozostaje wynikiem oczekującym.
Warstwa HTTP zachowuje kolejność dowodów: częściowe wykonanie, ACK,
utrwalona konfiguracja/obliczenie, zadanie, obserwacja zasobu i wynik aplikacji.
HTTP 200 ani samo przyjęcie zadania nie tworzą potwierdzenia fizycznego.

Ochrona CORS przegląda kopię nazw nagłówków przed usuwaniem starych grantów,
aby mutowanie kolekcji nie pomijało sąsiednich wpisów. Kontrole Host/Origin,
obsługa jawnych uploadów i limity zgody pozostają aktywne.
