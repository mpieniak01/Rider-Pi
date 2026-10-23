# Kontrakt nawigacji kierunkowej

Powiązany moduł Venom udostępnia edycję ROI obrazu i czułości oraz opcjonalne,
ograniczone korekty kierunku. Pi przechowuje wspólną rewizyjną politykę i pozostaje
jedynym wykonawcą silników. Zapis nie uruchamia ruchu ani ARM. Omijanie jest
domyślnie wyłączone, a dotychczasowa jazda prosto v1 pozostaje dostępna.

## Wersje akcji i przyjęcie ruchu

V2 zachowuje STOP i następnie turn_left/right wyłącznie yaw. Jawne v3 używa
steer_left/right: wspólne niskie vx i ograniczone yaw w jednym poleceniu.
Stare włączone polityki bez wersji manewru zostają v2. Polityki bez geometrii
migrują do image, bez cichego włączenia nowej projekcji. V3 image zachowuje
aproksymację masek; istniejąca instalacja wybiera ground jawnie.

Każda niezerowa odpowiedź musi pasować do run, frame, sequence, revision, modelu
i budżetu capture. Korekta wymaga trzech wolnych obserwacji strony, wolnego toru
i najbliższej strefy; Pi niezależnie sprawdza dowody. Klatka sprzed lub podczas
korekty nie autoryzuje następnego ruchu. Host trzyma stronę do potwierdzenia
wolnego toru prosto na nowych klatkach.

Pozostają pierwotne 10 s ARM/próby, watchdog i limity impulsu:
jazda <=0,1 SDK / 150 ms, yaw 0,01–0,1 SDK / 50–150 ms.
Nie ma automatycznego ARM ani przedłużania. Końcowy avoidance_no_progress
nie może wznowić się przez późniejsze GO.

## Polityka projekcji podłoża

avoidance.geometry zawiera mode (ground/image), znormalizowane fx/fy/cx/cy kamery,
radius_ratio, lookahead_ratio i max_heading_deg. Nowe ustawienia pozostawiają
omijanie wyłączone i fx/fy/radius_ratio puste. Walidacja sprawdza skończone zakresy;
jazda z włączonym ground v3 wymaga uzupełnienia kalibracji. Wykonawca odrzuca
niezerowe odpowiedzi bez konfiguracji projekcji, właściwego rodzaju geometrii,
poprawnej normalnej/wysokości odniesienia oraz dostatecznego wsparcia podłoża.

fx/fy to ogniskowe podzielone przez rozmiar dostarczonego obrazu; cx/cy to jego
znormalizowany punkt główny po faktycznym resize/crop/obrocie. Projekcja pinhole
wymaga scharakteryzowania/skorygowania dystorsji. radius_ratio to zachowawczy
promień opisany na robocie podzielony przez minimalną dopuszczoną fizyczną wysokość
kamery. Promień obejmuje wszystkie części względem rzutu kamery na podłoże
w dopuszczonych pozach i margines. lookahead_ratio używa jednostek bieżącej
wnioskowanej wysokości nad podłożem; nie deklaruje pomiaru centymetrów.

Host odpornie dopasowuje podłoże z pojedynczej inferencji głębi, rzutuje kapsuły
obrysu w 49 kierunkach i wyznacza ciągłe wolne prześwity. Oprócz próbek promieni
sprawdza obserwowane cienkie przeszkody i uskoki. Podgląd pokazuje rzut torów;
niepełna widoczność daje UNKNOWN. Ground korzysta z tych parametrów zamiast ROI.

Poza kamery wynika z bieżącego podłoża, nie z pomiaru IMU/wysokości. Duża zmiana
referencji kasuje stabilność, ale nigdy budżet korekt. Świeża porównywalna klatka
po korekcie mierzy przyrost względnego prześwitu. Stagnację regulują
max_stalled_corrections (1–5, domyślnie 2) i progress_min_delta (0–0,3, domyślnie
0,03); niezależny max_turn_pulses to 1–5, domyślnie 3. ZERO przy niepewnej
projekcji mieści się wyłącznie w pierwotnej ważnej sesji. Brak łączności i STOP
operatora/globalny kończą sesję.

Pełna siatka kierunków pozostaje w opcjonalnej diagnostyce hosta. Wybrane tory,
referencja i liczniki mieszczą się w istniejącym limicie odpowiedzi/nagłówka.
Kierunek wybiera stronę ograniczonej korekty, nie metryczny yaw ani certyfikowany
tor dynamiczny. Łączny vx/yaw, obrys i hamowanie wymagają odbioru fizycznego.

## Budżet HTTP i krótka przerwa analizy

Oczekiwanie HTTP wykorzystuje pozostały budżet klatki po odjęciu jej wieku
i przygotowania żądania. Połączenie, wysłanie żądania, nagłówki i treść odpowiedzi
mają jeden termin monotoniczny. Odbiór kolejnego fragmentu nie odnawia timeoutu.
Nie ponawiamy POST tej samej klatki.

W ciągłej podróży wyczerpaną klatkę można odrzucić po wygaśnięciu poprzedniego
zezwolenia na silniki, jeśli nadal trwa dotychczasowe okno oczekiwania na analizę.
Robot pozostaje w postoju; następna próba wymaga nowej klatki. Spóźnione GO nie
jest wykonywane i nie odnawia żadnego terminu. Brak nowej poprawnej decyzji przed
końcem pierwotnego okna nadal kończy podróż. STOP operatora, utrata uprawnień,
zmiana sesji/modelu i błędna tożsamość odpowiedzi zachowują działanie końcowe.
Ograniczone czasowo próby bez ciągłej podróży zachowują wcześniejsze zachowanie.

Pole statusu `request_attempt` zawiera identyfikator run/sequence, stan
pending/completed/failed oraz bieżące elapsed_ms i capture_age_ms.
request_roundtrip_ms i response_age_ms są zerowane przed nowym żądaniem,
a po błędzie opisują tę nieudaną próbę zamiast poprzedniego poprawnego GO.

## Testy i dalszy odbiór danych

Testy używają rzeczywistego kodu lease/runner z rejestrem wyjść zamiast sprzętu.
Sprawdzają błędne dowody geometrii, brak kalibracji, migrację, impulsy/TTL,
końcowy STOP i kontrakt między repozytoriami. Gałąź zawiera też poprawkę mobilnego
widoku sterowania i kamery.

Następny PR zbiera kalibrację kamery/obrysu i oznaczone sekwencje niezależnego
odbioru: podłoga, lewa/prawa/centralna/obie przeszkody, cienkie obiekty, uskoki,
słabe światło, różne wysokości/pitch/roll oraz nowe klatki po korekcie. Należy
zweryfikować znak yaw, obrys, faktyczny ruch i hamowanie oraz ocenić błędne
GO/STOP, migotanie, pomyłki stron i opóźnienia. Słabe historyczne pudełko pozostaje
próbką negatywną, bez wymuszania progów ani twierdzenia o fizycznie wolnym torze.
Ograniczeniami pozostają błędy głębi monokularnej i niewidoczne boki/tył.
