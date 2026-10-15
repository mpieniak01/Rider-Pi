# Opcjonalne skręty w pętli wizji Venom

Pi pozostaje jedynym właścicielem polityki i wykonania ruchu. Ta funkcja dodaje
opcjonalny kontrakt wizji v2; domyślnie omijanie jest wyłączone. Stare pliki
konfiguracji są odczytywane z nowymi polami wyłączonymi. Jazda prosto v1 pozostaje
dostępna; stare odpowiedzi nie mogą uruchomić nowych akcji skrętu.

## Polityka i zgodność

Istniejący plik navigation_config.json zawiera pole avoidance:
enabled, sweep_verified, mirrored (bool), turn_speed (SDK 0,01–0,1; domyślnie
0,05), turn_ms (50–150; domyślnie 100), max_turn_pulses (1–5; domyślnie 3).
Nie ma drugiego pliku ustawień ruchu po stronie Venom. Zmiana parametrów
unieważnia poprzedni odbiór kalibracji. Włączenie wymaga depth_plane oraz
dotychczasowych niskich limitów próby. Tryb drive wymaga sweep_verified:
potwierdzenia stron kamery, obrysu skrętu i hamowania na danym montażu.

Venom musi reklamować supported_protocol_versions zawierające 2. Pi wysyła
protocol_version=2 wyłącznie dla włączonego omijania, wraz z avoidance oraz
motion_phase=ready/turn_settling. Odpowiedź zachowuje run/frame/sequence/revision,
model i TTL. Akcje to go, stop, turn_left, turn_right. Nieznana wersja, błędna
tożsamość lub niepełne dowody wolnej strony kończą próbę postojem.

## Sekwencja

Po wykryciu przeszkody Pi najpierw wysyła ZERO. Venom wymaga trzech kolejnych
potwierdzeń wolnej strony. Pi sprawdza odbiór strefy, model, tryb, kompletność
sektora, brak uskoku i pozostały limit skrętów. Dopiero wtedy wywołuje istniejący
wykonawca z vx=0 i yaw dodatnim dla left, ujemnym dla right. Rzeczywiste znaki
kierunku wymagają sprawdzenia na robocie; czas SDK nie wyznacza kąta obrotu.

Po skręcie Pi wymaga klatki przechwyconej po końcu lokalnego pozwolenia
i 100 ms stabilizacji. Samo późne otrzymanie odpowiedzi nie wystarcza. W tym czasie
wolno podtrzymywać jedynie ZERO. Nowa ocena trzech klatek przednich może wznowić
krótkie impulsy do przodu w nowym kierunku.

Wszystkie postoje i skręty mieszczą się w oryginalnej próbie do 10 s.
Nie przedłużają ARM, watchdogów ani limitów jazdy 0,1 SDK / 150 ms.
Globalny STOP, utrata decyzji, błąd wykonawcy i przejęcie ręczne są końcowe.
Nie ma automatycznego wznowienia ani powrotu do pierwotnego kursu.

## Odbiór

Funkcja eksperymentalna: testy programowe nie potwierdzają wolnego obrysu,
kierunku ani zaobserwowanego ruchu fizycznego. Kamera przednia nie pokazuje
całego boku i tyłu. Przed przyjęciem omijania wymagane są oznaczone sekwencje
lewa/prawa/obie strony, cienkie przeszkody, uskoki i klatki po skręcie oraz
ręczny odbiór obu kierunków. Automatyczne testy nie kontaktują silników.

Powiązana implementacja panelu i analizy znajduje się w venom-module-rider.
Wersje obu repozytoriów trzeba wdrażać zgodnie z kontraktem v2.
