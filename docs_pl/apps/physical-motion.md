# Ruch fizyczny: kontrakt programu i ręczna charakterystyka

Ten przyrost zawiera zabezpieczenia programu i weryfikację na mockach.
**Robot nie został poruszony w ramach tej pracy. Pomiary fizyczne nie są zakończone.**
Issue #256 pozostaje otwarte. ACK SDK potwierdza zapis, nie ruch, stabilność,
odległość, czas zatrzymania ani fizyczne dotarcie do celu.

## Działanie programu

| Obszar | Kontrakt |
| --- | --- |
| Czas | Rzeczywisty monotoniczny dt; nieważny/nieskończony/nie dodatni/za duży dt zatrzymuje i rozbraja |
| Rampa | Ograniczona zmiana znormalizowanego polecenia na sekundę; nawrót przechodzi przez zero |
| SDK | rider_move_x(runtime=0) jest podtrzymany do zastąpienia; ponawiane wyjście jest ograniczone istniejącą bramą celu/zgody |
| Znak skrętu | Canonical yaw ujemny=w lewo, dodatni=w prawo; kąt pozycji dodatni przeciwnie do wskazówek zegara |
| Polecenie zerowe | Świeże uprawnione MOVE=0 natychmiast zapisuje zera, zachowuje ważną zgodę i otrzymuje ACK SDK |
| Błąd/timeout | Utrata czujnika/intencji/źródła i timeout celu zatrzymują przez tę samą bramę oraz rozbrajają; dane nie przywracają zgody |
| Czujniki | Jeden właściciel UART, jeden odczyt na przebieg; skończone oryginalne czasy osobnych osi i baterii, budżet wieku 2,5 s |
| Bateria | Procent SDK 0..100 przechodzi na 0..1; 1%=0,01; brak/nieważny odczyt=null, nigdy zdrowe zero |
| Polityka baterii/przechylenia | Progi i reakcja fizyczna pozostają manual_characterization_required |
| Cięższe akcje | Wysokość, balans i akcje gotowe są za tą samą bramą; brak charakterystyki przerwania blokuje zdolność |

Rampa ma jednostki polecenia, nie m/s ani m/s². Nawet bardzo mała niezerowa
wartość może stać się minimalnym krokiem SDK i jest raportowana jako ruch.
Domyślne granice są odziedziczonymi ograniczeniami programu, nie pomiarem.
Mała rampa nie obiecuje małego przyspieszenia fizycznego. STOP omija rampę,
ale mechaniczne skutki pozostają niezweryfikowane.

Przedni ROI jest heurystyką. Klatka z cache zachowuje wiek oryginalnego obrazu.
Brak/błąd/niepotwierdzona informacja o wolnym miejscu nie może uruchomić ruchu.
Eksploracja i ReturnHome pozostają bierne z navigation_traversal_unverified:
ROI i punktowy A* nie dowodzą przejazdu całej bryły oraz horyzontu hamowania.
Ręcznie potwierdzony model/bieżące HOME i zapisy odległości/obrysu/przejezdności
służą wyłącznie biernemu planowi, nie udostępniają MOVE. Stare zadanie nie wznawia
się po restarcie, zmianie źródła, utracie zgody lub danych. Ruch ręczny ma osobną zgodę.

Mapa i pozycja muszą mieć dokładnie to samo bieżące calibration_id i reference_id.
Zmiana odniesienia operatora czyści komórki i odległości poprzedniej mapy oraz
anuluje rozpoczętą trasę powrotu. Stare komórki przechodzą na UNKNOWN także
w statystykach panelu; samo zgodne request_id nie potwierdza ramy mapy.
Jawny błąd/offline/stale kamery pozostaje błędem przez ROI i historię.
Nieważna klatka strumienia nie tworzy świeżego pliku przetworzonego do fallbacku.

Panel odczytuje istniejący wewnętrzny plan punktowy i potwierdzony HOME.
`plan_observed_at` zachowuje starszy źródłowy czas mapy/pozycji; heartbeat procesu
nie odmładza punktów. Zmiana referencji/HOME, błąd pozycji lub jawny STOP usuwa
plan. Nakładki mapy, pozycji i planu wymagają tej samej ramy oraz HOME. Katalog
wymaga dokładnego `data_ready: true` i `navigation_ready: true` od bieżącego,
dopasowanego producenta nawigacji; sam działający proces nie oznacza gotowości.

**Nie ma jeszcze osobnego żądania planowania w DISARMED.** Zachowane legacy
start/ReturnHome wymagają oryginalnej koperty zgody na ruch, a kontroler pozostaje
pasywny. Panel blokuje oba żądania i pokazuje `passive_plan_request_unavailable`
oraz `navigation_traversal_unverified`. Nie uzbrajaj robota, aby otrzymać plan.
Oddzielne API planowania bez aktuacji wymaga przyszłej zmiany; odczyt wcześniej
opublikowanego planu jest już dostępny.

## Przygotowanie przyszłej ręcznej próby

### Ograniczenia wdrożenia

Zwykłe `pi-preview` oraz `pi-release` chronią zmiany w `drivers/` i `systemd/`.
Ta migracja wymaga więc osobno zrecenzowanego, jednorazowego i kontrolowanego
przełączenia Git oraz unitów. `systemd_reconcile.py` tylko podmienia linki i
przeładowuje systemd; nie przekazuje własności UART ani nie przełącza atomowo
kodu i definicji usług. Przed planowaniem przełączenia potrzebny jest świeży
inwentarz rzeczywistych ścieżek unitów, interpreterów i drop-inów. Wdrożenie
pozostaje oczekujące; ta weryfikacja programowa nie wdrożyła zmian na urządzenie.

Przy zaplanowanym rollbacku odtwórz manifest unitów **nowym** helperem
`scripts/systemd_reconcile.py --rollback <katalog-kopii-manifestu>` przed
przywróceniem starej rewizji Git; po przywróceniu Git przeładuj systemd.
Nie restartuj automatycznie starszych klientów SDK: ich konstruktor może
poruszyć urządzeniem. Zachowaj Wi-Fi/SSH, kompensację bocznego LCD 270, boot
i ręczny Jupyter; pozostaw `--consolidate-boot` wyłączone. Ograniczenia wymagają
jawnego planu wdrożenia z operatorem, a nie automatycznego wdrożenia lub próby ruchu.

1. Operator wybiera jeden konkretny manewr i zapisuje plan: podłoże, przestrzeń,
   zmierzone granice, obciążenie, bateria, kabel, obserwator oraz dostępny STOP/E-Stop.
   Robot deweloperski jest zasilany kablem: potrzebny luz i wolna przestrzeń.
   Zgoda na kamerę/deploy/usługi nie jest zgodą na ruch.
2. Potwierdzić firmware, jednego właściciela UART, świeżą telemetrię, DISARMED,
   zdolności i awaryjne zatrzymanie. Nieznany/błędny stan oznacza brak próby.
   Nie kasować E-Stop automatycznie ani nie udostępniać niezweryfikowanego aktuatora.
3. Uzgodnić dokładne polecenie i maksymalny czas tej jednej próby. Każda kolejna
   wymaga osobnej zgody operatora. Bez pętli, automatycznej kalibracji, CI/E2E/pytest
   i diagnostyki wysyłającej manewry.
4. Dopiero po zgodzie użyć istniejącego scripts/manual_motion-probe.py do jednej
   ograniczonej próby. Wymaga TTY, planu i potwierdzenia tokenu, ogranicza impuls
   do 0,01..0,25 s i wysyła STOP w cleanup. Odmawia nieopisanym zdolnościom.
   Dłuższa obserwacja wymaga osobno przejrzanego planu operatora; nie omijać bramy.
5. Obserwować rzeczywistą reakcję i STOP niezależnym pomiarem/czasem. Przerwać przy
   niepewnej przestrzeni, napięciu kabla, opóźnieniu STOP lub niestabilności.
   Zapisać odmowę, timeout, wyjście firmware i wynik, także nieudanej próby.

To instrukcja dla przygotowanego operatora, nie zgoda na jej wykonanie.

## Zapis pomiaru i otwarta akceptacja

Wzór config/odometry-calibration.example.json nie zawiera wymyślonych wartości.
Zapisać surowe obserwacje i powtarzalność z firmware, podłożem, obciążeniem,
baterią, kablem, operatorem, datą i commitem. Dokładne kroki ze znakiem są
używane bez interpolacji; warunki określają zakres stosowania zapisu.

- [ ] Potwierdzić znak i jednostki SDK/IMU yaw niezależnym pomiarem orientacji.
- [ ] Zmierzyć najmniejsze skuteczne kroki przód/tył/lewo/prawo.
- [ ] Zmierzyć rozpędzanie i hamowanie dla zaakceptowanej rampy.
- [ ] Obserwować nawrót przez zero i ustalanie mechaniczne; bez nieuzgodnionej serii.
- [ ] Zmierzyć opóźnienie i drogę zatrzymania na zapisanym podłożu.
- [ ] Opisać wysokość/balans/akcje i ich przerwanie przed włączeniem zdolności.
- [ ] Opisać ważność baterii, zachowanie przy rozładowaniu i bezpieczną reakcję.
- [ ] Opisać przechylenie IMU, offset/szum i uzgodnioną reakcję na niebezpieczną postawę.
- [ ] Zmierzyć błąd pozycji/kierunku, prześwit obrysu i pokrycie odległości/przejezdności.
- [ ] Potwierdzić marginesy korytarza bryły i horyzont hamowania; przejrzeć planner/bramę przed aktuacją autonomiczną.
- [ ] Wybrać uzgodnione fizyczne progi/reakcję i zapisać zakres ich obowiązywania.
- [ ] Ręcznie potwierdzić parametry w tych warunkach i przejrzeć rollback.

Mocki i odczyt protokołu producenta nie zaznaczają żadnego punktu tej listy.
Sam plik nie ustanawia bieżącego odniesienia: osobne
[API odniesienia operatora](odometry.md) nie wykonuje aktuacji i wymaga DISARMED.

## Dostępna lekka weryfikacja

Testy korzystają z fake SDK/czasu/BUS/plików: rampa/dt/nawrót, zero a błąd,
brak/wiek/przyszły czas/kolejność czujników, wiek faktycznych wyjść, metadane cache,
nieskalibrowany model, replay/restart/API odniesienia, stara mapa/pozycja/odległość,
granice alokacji, trasy UNKNOWN i znak skrętu. Uruchamiać je w istniejącym venv
Rider w WSL z izolacją. Bez nowych pakietów/daemona/drugiej bramy.
Ograniczone zapisy statusu są w /run/rider-motion.

LCD pozostaje zamontowany bokiem z kompensacją 270; boot, splash, Wi-Fi/SSH
i ręczny Jupyter pozostają konfiguracją odniesienia.
