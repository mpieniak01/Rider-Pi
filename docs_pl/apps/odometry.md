# Odometria i jakość danych nawigacji

Odometria jest modelem na podstawie potwierdzonych wyjść SDK i obserwacji IMU.
Nie jest czujnikiem lokalizacji. W tym wydaniu nie ma zmierzonej dokładności,
prędkości ani drogi zatrzymania. Charakterystyka sprzętu pozostaje otwarta w #256.

## Źródła i ważność

- `motion.output`: rzeczywiście zaakceptowane przez SDK, podpisane znakiem
  `linear_step` / `turn_step`, source=`motion-executor`, instance_id, generation, oryginalne
  observed_at, stopped i accepted. Żądane motion.command ani legacy motion
  nie aktualizują modelu położenia.
- `imu.data`: skończony yaw i oryginalny czas obserwacji. IMU jest wymagane;
  brak IMU nie przełącza automatycznie na zgadywaną prędkość kątową.
- `robot.pose`: x/y/theta, observed_at najstarszego źródła, ts publikacji,
  calibration_id, reference_id, data_ready, navigation_ready i error.
  home jest jawnym zgłoszeniem operatora w tym samym odniesieniu/kalibracji.
  Sama ważność modelu pozycji nie udostępnia autonomicznego ruchu.
  Confidence=null oraz confidence_kind=unquantified_model oznaczają brak
  wyznaczonej pewności modelu. physical_completion=unverified.

Całkowanie używa czasu monotonicznego. Ważność wyjścia wynosi 0,25 s, IMU 2,5 s,
maksymalny dt całkowania 0,2 s. To budżety wejść programu, nie granice fizyczne.
Stare, przyszłe, brakujące i nieuporządkowane dane nie odmładzają pozycji. Luka
po ruchu oznacza nieznaną ciągłość aż do nowego ręcznego punktu odniesienia.
Zaakceptowane niezerowe wyjście już oznacza możliwy ruch, przed pierwszym krokiem
całkowania. Nieobserwowana zmiana generacji i nowy proces wykonawcy unieważniają
odniesienie. ts publikacji nigdy nie zastępuje brakującego observed_at.

Podczas bezczynności odebrane niezależnie świeże, zaakceptowane zero SDK może
pozostać ostatnim poleceniem modelu, gdy zgodny heartbeat motion.state potwierdza
ten sam proces wykonawcy/generację, zerowe wyjście/cel oraz zdrowy stan bez ruchu.
Heartbeat ma budżet 3 s dla czasu źródłowego i monotonicznego czasu odbioru;
IMU nadal musi być świeże. Heartbeat nie dostarcza brakującego zapisu SDK ani nie
naprawia luki historii. Pierwotny czas zapisu pozostaje w last_sdk_output_observed_at;
observed_at pozycji podczas postoju pochodzi z najstarszej obserwacji heartbeat/IMU
potwierdzającej bieżący model. Stary STOP bez takiej ciągłości nie potwierdza nowego
ręcznego odniesienia. To wejścia modelu, bez dowodu mechanicznego zatrzymania;
physical_completion pozostaje unverified.
Przyjęcie MOVE może dotrzeć przed niezależnym wyjściem SDK. Zdrowy, zgodny wykonawca
może odroczyć model najwyżej o 0,25 s ze stanem sdk_output_pending; nie pozwala to
całkować ruchu, odmładzać STOP ani wydłużać oczekiwania kolejnymi heartbeat.
Brak wyjścia, luka żywotności, nieprawidłowy dt lub stare IMU nadal łamią ciągłość.
Oczekiwanie kończy dopiero niezależnie odebrany, zaakceptowany zapis SDK.

## Zapisany model

ODOMETRY_CALIBRATION_PATH opcjonalnie wskazuje ograniczony plik JSON. Wzór:
[`config/odometry-calibration.example.json`](../../config/odometry-calibration.example.json).
Wzór celowo jest niezweryfikowany i nie zawiera fizycznych wartości.

Użyteczny jest dopiero ręcznie zweryfikowany zapis z identyfikatorem pomiaru,
warunkami firmware/podłoża/obciążenia/baterii, sprawdzonym znakiem IMU oraz
tablicami dokładnych kroków SDK ze znakiem. linear_m_s mapuje całkowity krok SDK
na zmierzone m/s; turn_rad_s na zmierzone rad/s, dodatnie przeciwnie do wskazówek
zegara. Zero jest poleceniem zerowym. Brakujący krok jest odrzucany, bez
interpolacji. Dawne skale prędkości znormalizowanej nie są kalibracją fizyczną.

Pomiar obowiązuje wyłącznie w zapisanych warunkach. Rampa nadal dotyczy
znormalizowanych poleceń. Minimalny niezerowy krok adaptera nie pozwala obiecać
dowolnie wolnego fizycznego ruchu przy małej wartości w panelu.

## Aktualny punkt odniesienia

Kalibracja z pliku nie przywraca bieżącego położenia robota. Każdy proces
odometrii zaczyna z nieznanym odniesieniem. Przy potwierdzonym świeżym stanie
wykonawcy, bez ruchu i w DISARMED operator może sprawdzić położenie/kierunek
i świadomie zgłosić pojedyncze odniesienie:

```text
GET  /api/odometry/state
POST /api/odometry/reference
```

POST wymaga generation, source=manual, rosnącego seq dla generacji, request_id,
oryginalnego ts, ttl_ms<=500, operator_consent=true, konkretnego operator_plan
oraz skończonych x/y/theta (metry/radiany, dodatni kąt w lewo). API zwraca 202
pending. Dopiero dopasowany ACK bieżącego procesu potwierdza zmianę odniesienia;
nie potwierdza ruchu ani kalibracji. GET nie uruchamia procesu ani napędu.
Tematy BUS: odometry.reference i odometry.reference.ack.

Bieżąca pozycja nie jest automatycznie HOME. Niezależnie sprawdzone HOME zgłasza
się w tym samym żądaniu: home_operator_confirmed=true oraz skończone home_x/home_y
w tej samej ramie. Bez tego HOME pozostaje nieznane, bez domyślnego (0,0).
Nowe odniesienie bez HOME usuwa poprzednie HOME; restart/zmiana wykonawcy go
nie odtwarza. GET/ACK pokazują zgłoszone HOME z dokładnym reference_id/calibration_id.
CLI udostępnia jawne --home-x i --home-y: obie wartości razem albo żadna.

Interaktywny pomocnik bez aktuacji: scripts/manual_odometry-reference.py.
Operator podaje zmierzone współrzędne i plan, potem potwierdza REFERENCE.
CI/brak TTY/izolacja testowa są odrzucane. Żądanie sprzed startu procesu oraz
trwale zużyta para generation/seq są odrzucane. Restart nie odtwarza odniesienia.
Stan i zużycie sekwencji są w /run/rider-motion; ODOMETRY_STATE_DIR to override
izolowanego testu.

## Mapper i powrót do domu

Mapper przyjmuje wyłącznie świeże skalibrowane pozycje oraz zweryfikowaną
geometrię odległości, obrys oraz zapisy przejezdności/horyzontu hamowania. Ogranicza mapę do 65 536
komórek, zachowuje ich oryginalne czasy i zamienia stare na UNKNOWN. Żądanie mapy
odsyła request_id i nie odmładza danych. UNKNOWN oraz skróty po przekątnej między
zablokowanymi komórkami nie są przejezdne w planie punktowym. Mapa i pozycja
muszą mieć dokładnie zgodne reference_id/calibration_id oraz HOME; zmiana ramy
czyści wcześniejsze komórki/odległości. Brak odległości/pozycji/HOME blokuje plan.
planning_ready opisuje użyteczne wejścia, navigation_ready mappera pozostaje false.

**Eksploracja i ReturnHome pozostają bierne w tym wydaniu.** Nie publikują MOVE,
także zerowego. ReturnHome zwalnia zgodę ruchu canonical STOP i może pokazać
dopasowany punktowy plan A* (planning_only, planned_path, maksymalnie 128 punktów
w prezentacji). Wolne komórki i dodatni stopping_horizon_m z flagami weryfikacji
nie dowodzą przejazdu całej bryły ani wyhamowania. Sterownik raportuje
navigation_traversal_unverified, nigdy fizyczne dotarcie lub gotowość ruchu.
Żadna flaga metadanych nie uruchamia autonomicznego aktuatora. Charakterystyka
korytarza/hamowania i osobno przejrzany planner/brama są nadal do wykonania.
Ręczne sterowanie zachowuje osobną zgodę operatora.

Detektor przedniego ROI kamery jest heurystyką przeszkody; **nie jest skalibrowaną
odległością ani dowodem przejezdności korytarza dla całego obrysu robota**.
Brak klatki, pusta lista przeszkód i confidence=0 nie tworzą wolnej mapy.
Potwierdzenie zapisu SDK nie dowodzi fizycznego dotarcia do celu.

Zobacz [ręczny protokół i otwartą listę akceptacji](physical-motion.md).
