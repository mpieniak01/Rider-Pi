# Automat2 — kontrakt podróży v1

Tryb podróży jest osobnym opt-in dla integracji Venom. `POST /api/navigation/trial`
zachowuje dziesięciosekundową zgodę i dotychczasową obsługę operatora. Nowa podróż
nie jest automatycznym odnawianiem trial ani okresowym ARM.

## Start i wymagania

`POST /api/navigation/journey` przyjmuje pola trial: `request_id`, `generation`,
`ts`, `ttl_ms` (do 500 ms), `config_revision`, `settings_revision`,
`operator_consent:true`, `operator_plan`, `source:manual`, `execution_context:panel`.
Dodatkowo wymagane są `journey_version:1`, `operator_control_version:1` oraz
niepusty `panel_id`. Identyfikator żądania nie zawiera białych znaków.

Start wymaga `navigation_journey_version:1` w świeżym stanie wykonawcy i obsługi
kontraktu przez Venom. Polityka musi pozwalać na jazdę oraz mieć
`avoidance.enabled:true`, `protocol_version:3`, `sweep_verified:true` i aktualny
odbiór modelu/strefy. Zachowane są geometrie `image` i `ground`; wybrany `ground`
wymaga rzeczywistych `fx`, `fy`, `radius_ratio` oraz bieżącego potwierdzenia.
Brak kalibracji nie jest uzupełniany automatycznie. Limity omijania zachowują
maksymalnie 0,1 SDK i impuls do 150 ms.

Przygotowanie korzysta z tej samej transakcji co trial: kamera, zwolnienie starego
producenta, konfiguracja, pojedyncza zgoda wykonawcy, start i potwierdzenie nowego
workera. STOP lub nowsza generacja przerywają przygotowanie. Odtworzenie request_id
nie uruchamia ponownie misji. Postęp przygotowania dodaje `journey_version:1`.

## Zgoda wykonawcy i świeżość

Wewnętrzne ARM używa `arming_mode:journey`, `owner:navigation`,
`journey_version:1`, `journey_id` równego identyfikatorowi żądania podróży,
`operator_control_version:1` i `panel_id`, bez `lease_s`. Tylko jawny panel może
je przyznać. Bootstrap ma watchdog 5 s. Potem każdy zaakceptowany cel NAV, również
ZERO, odnawia wyłącznie krótki watchdog niezależnej pętli sprzężenia zwrotnego.

Każdy cel ma identyfikator misji, poprawne generation/operation/sequence, krótki
TTL i oba Pi-local deadlines decyzji oraz feedback (do 500 ms). Ich walidacja nie
przedłuża zgody; następuje to dopiero po przyjęciu celu przez controller.
Impuls kończy się we własnym terminie. Oczekiwanie na następną świeżą decyzję
utrzymuje ZERO; utrata feedback kończy zgodę. GET, Refresh, podgląd, ponowne
połączenie i odtworzone ARM nie odnawiają podróży.

## Klatki, omijanie i postęp

Metadata klatki i odpowiedź Venom zawierają dokładnie:
`journey:{version:1,id:<id misji>,maneuver_epoch:<liczba całkowita>}`.
Początkowy epoch wynosi 0. Host dodaje `host_session`, nonce procesu; zmiana nonce
w trwającej misji kończy jazdę. Ramki trial i obserwacji nie zawierają journey.

Omijanie używa istniejących dowodów v3: wolny sektor i chroniony tor skrętu,
aktualny model/strefa, seria potwierdzeń i ograniczona liczba korekt. Po korekcie
nie używa się zdjęcia sprzed ruchu lub okresu ustalania obrazu. Pi zwiększa epoch
o 1 i zeruje lokalny budżet korekt dopiero po trzech zaakceptowanych świeżych GO
z klatek przechwyconych po zakończeniu korekty i okresie ustalania. GO bez
wcześniejszej korekty nie zeruje budżetu. Przeszkoda/niepewność przerywa serię.
Krótkie oczekiwanie na świeży feedback zachowuje serię, ale nigdy stary ruch.

Venom przyjmuje krok epoch +1 tylko po swoim potwierdzeniu przejazdu po korekcie.
Skok, cofnięcie, obcy identyfikator albo brak dokładnego echo kończą misję.
Nieskuteczne korekty kończą się STOP; nie odnawiają budżetu przez upływ czasu.

## STOP i stan

STOP, ESTOP, utrata decyzji, zmiana konfiguracji i ręczne przejęcie kończą podróż.
`navigation_resume` nie wznawia jej. Ręczna korekta wymaga nowej jawnej ręcznej
zgody; prawo podróży nie zmienia się w nieograniczone ARM manual. Kamera może
pozostać jako pasywny podgląd, bez prawa ruchu. Restart nie odtwarza misji.

`GET /api/navigation/status` publikuje `journey`:
`{version:1,id,active,state,reason,elapsed_s,maneuver_epoch}`.
Stany to `qualifying`, `forward`, `steer_left`, `steer_right`, `waiting`, `blocked`,
`stopped`, `failed`. Zakończony wynik pozostaje w statusie i archiwum ostatniego
przebiegu. Safety publikuje oddzielny stan zgody `journey` z tym samym id i flagą
active oraz krótki `lease_remaining_s`; źródłem stanu manewru jest runner.

To reaktywna jazda z obrazu, bez SLAM, odometrii, gwarancji dotarcia do celu i
pomiaru centymetrów z pojedynczej kamery. Testy programowe używają wyłącznie
atrap. Fizyczny odbiór kilku przeszkód, pochylenia, łączności i STOP należy do
operatora po przygotowaniu przestrzeni i kabla; ACK nie dowodzi przebytej drogi.
