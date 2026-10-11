# Kalibracja: profile, pomiary i odniesienie

Panel /calibration korzysta z istniejących modułów JavaScript i Flask.
Nie instaluje pakietów ani modeli. Otwarcie strony wykonuje odczyty;
nie uruchamia usług, nie wysyła ARM, STOP ani prób ruchu.

## Rzeczywiste odczyty wykonawcy

Panel pokazuje signed linear_step/turn_step wyłącznie z motion.sdk_output:
accepted, źródło motion-executor, oryginalny observed_at, dokładne instance_id
i generation muszą pasować do świeżego statusu wykonawcy. Budżet zapisu SDK
wynosi 0.25 s. Starsze pasujące kroki są oznaczone jako historia/stale,
bez twierdzenia o aktualnym ruchu; dane odrzucone lub niezgodne są unknown.
Cel panelu i wartości formularza nigdy nie służą do wyliczenia kroków SDK.

Roll, pitch i yaw są surowymi wartościami SDK bez przypisywania niepotwierdzonych
jednostek. Bateria jest przeliczana z finite fraction 0–1 na %, z zachowaniem
prawdziwego zera. Każdy kanał ma własne observed_at, ready, error i wiek
z budżetem 2.5 s. Świeża publikacja statusu nie odmładza pomiaru; uwzględniony
jest także większy wiek zgłoszony przez producenta. Błąd jednego kanału
nie potwierdza ani nie psuje innych, ale brak świeżego rodzica lub błąd
UART/sprzętu wygasza całość. Bieżące trzy parametry motion.dynamics są
pokazywane oddzielnie od pułapów ENV, także przy błędzie sprzętu, gdy konfiguracja jest poprawna i świeża. Błąd sprzętu jest pokazany osobno. Physical_completion pozostaje unverified.

## Profil i jednostki

| Pole | Znaczenie |
| --- | --- |
| motion.speed_limit | Limit 0–1 w jednostkach znormalizowanych wykonawcy, nie m/s. |
| motion.linear_rate / turn_rate | Tempo rampy w jednostkach znormalizowanych/s, nie fizyczne przyspieszenie. |
| odometry.linear_m_s / turn_rad_s | Własne zmierzone prędkości dla signed SDK step: jazda ±1…12, skręt ±20…70. |
| odometry.conditions | Firmware, podłoże, obciążenie, bateria, kabel, operator, data i commit. Dodatkowe pola pozostają zachowane. |
| odometry.observations | Notatki/dowody: minimum step, przyspieszanie, hamowanie, zmiana kierunku, droga/opóźnienie STOP, błędy pozycji/kierunku, bateria i przechył. |
| measurements | Surowe obserwacje udanych i nieudanych prób, czas, dystans/kąt, faza, step i dowody. |

Runtime stosuje trzy parametry motion, tabele odometrii i znak IMU.
Observations, w tym battery_policy i tilt_policy, zapisują notatki operatora;
nie są działającymi progami lub blokadami i nie odblokowują autonomii.
Nie zmieniamy skali SDK ani migracji istniejących jednostek ENV.

Formularz zaczyna od niezweryfikowanego szkicu. Wartości 0.6/1/2 to ustawienia
programowe, nie pomiary; bieżąca raportowana dynamika może je zastąpić.
Aktywacja respektuje pułapy ENV z chwili startu wykonawcy. Watchdog nie jest
edytowany. Puste obserwacje pozostają nieznane, bez domyślnych wartości fizycznych.

## Przepływ operatora

1. Wpisz profil, warunki i dowody. Zapis tworzy niezmienną rewizję SHA-256;
   nie aktywuje konfiguracji ani ruchu.
2. Fizyczną próbę przygotuj z przestrzenią i kablem zasilania. W zwijanym
   formularzu jawnie udziel ARM z planem i krótką zgodą.
3. Każdy pojedynczy impuls wymaga osobnego planu i checkboxa. Zgoda jest
   zerowana przed wysłaniem, także przy błędzie. Czas wynosi 0.01–0.25 s;
   nie ma serii, ponowień ani automatycznego ARM. Obserwuj robota i użyj
   stale dostępnego STOP. ACK SDK nie dowodzi fizycznego zatrzymania ani pomiaru.
4. Dodaj własne obserwacje, także nieudane. Średnia dystans/czas całej próby
   obejmuje rampę i nigdy automatycznie nie uzupełnia tabeli ruchu ustalonego.
   Signed SDK step pochodzi ze stanu wykonawcy, nie z wartości suwaka.
5. Po rzeczywistych pomiarach wybierz manual i jawnie potwierdź własne dane.
   Wymagane są obie tabele, znak IMU, identyfikator, operator/data, opis dowodów
   i rekord z tym samym measurement_id oraz notatką. Edycja zeruje checkbox.
6. Aktywuj zapisaną rewizję w świeżym DISARMED, z osobną zgodą konfiguracji
   i planem. Nie jest to zgoda na ruch. Niegotowy model odometrii nie blokuje
   konfiguracji, gdy oba procesy są dostępne i motion potwierdza zerowy cel/wyjście.
7. Aktywacja zmienia generację i kasuje stare odniesienie/HOME, bez SDK STOP.
   Operator osobno używa STOP i fizycznie sprawdza zatrzymanie oraz pozycję,
   następnie wpisuje zmierzone x/y/theta oraz opcjonalne HOME w tej samej ramie.
   Formularz odniesienia nie wysyła ARM ani STOP; HOME nie jest domyślnym (0,0).

Testy automatyczne nie wykonują fizycznych prób. LCD, jego zamontowana orientacja
i sekwencja startowa pozostają bez zmian.

## Potwierdzenia i historia

HTTP 202 / pending oznacza wysłanie żądania. Aktywację potwierdza dopiero GET:
ten sam hash w obu świeżych procesach, zgodna instancja motion, applied_ack,
request/seq oraz command_generation i applied_generation. Ostatnia niezwiązana
odmowa last_ack nie zastępuje dowodu przyjętej konfiguracji applied_ack.
Po restarcie świeże matching hash ze źródła saved_profile dają
confirmation=loaded_from_saved, bez udawania nowego ACK.

Aktywacja zapisuje najpierw lokalny wskaźnik z activation_state=pending.
Wykonawca ponownie sprawdza DISARMED, brak celu/ruchu, generację i TTL;
dopiero po logicznym przyjęciu konfiguracji i zmianie generacji zapisuje
activation_state=applied. Wpis pending nie jest aktywnym profilem: API pokazuje
partial/active_profile_pending, a restart blokuje ARM i model odometrii.
E-Stop przed logicznym przyjęciem lub błąd końcowego zapisu pozostawiają ten
wpis do naprawy przez nowe jawne żądanie. Nie ma automatycznego rollbacku ani
przyjęcia przy restarcie. Starszy wskaźnik bez znacznika również jest odrzucany.
E-Stop po logicznym przyjęciu jest osobnym zatrzaśniętym stanem bezpieczeństwa;
udany końcowy zapis potwierdza wyłącznie konfigurację i nie kasuje E-Stop.

Applied dotyczy konfiguracji. Zweryfikowany zapis pomiarów record_verified,
bieżący model_ready i physical_completion=unverified są oddzielne.
Brak, stare dane, odmowa i tylko jeden zgodny proces pozostają unknown/partial.
Mutacje nie są automatycznie ponawiane ani odmładzane. Odniesienie wymaga
pasującego terminalnego ACK i odczytanego reference_id/HOME, nie samego HTTP.
Odmowa lub brak zgodnego potwierdzenia przez 8 s odblokowuje formularz dla
nowego jawnego żądania; nigdy nie powoduje ponowienia. Odniesienie dla aktywnego
profilu wymaga dokładnego profile_digest i zgodnej transakcji obu modułów.

Historia jest czytana początkowo, po zapisie lub na „Odśwież historię”;
polling co 2 s czyta wyłącznie runtime. Eksport dotyczy zapisanej rewizji.
Import UTF-8 JSON ma limit 65536 bajtów i zawsze jest historyczny,
manual_verified=false, nawet jeśli plik twierdzi inaczej. Powrót wersji to
jawna aktywacja wcześniejszego hasha z takimi samymi blokadami.
Katalog zachowuje do 64 rewizji; profil do 128 rekordów prób.

## API i pliki lokalne

| Endpoint | Działanie |
| --- | --- |
| GET /api/calibration/state | Oba procesy, active/requested hash, confirmation, model/error; tylko odczyt. |
| GET /api/calibration/profiles | Metadane rewizji. |
| POST /api/calibration/profiles | {profile, imported?:bool}; zwraca digest, profile, created, actuation:false. |
| GET /api/calibration/profiles/<digest> | Wybrana rewizja do formularza/eksportu. |
| POST /api/calibration/activate | Jawna konfiguracja; HTTP 202 pozostaje pending. |
| GET /api/odometry/state | Odniesienie, model i ostatni ACK. |
| POST /api/odometry/reference | Jawne odniesienie i opcjonalne HOME, bez aktuacji. |

Koperta aktywacji/odniesienia: generation, rosnące seq, source=manual,
request_id, ts, ttl_ms<=500, operator_consent=true, niepusty operator_plan.
Aktywacja zawsze podaje profile_digest; odniesienie podaje go, gdy istnieje
aktywny profil. Dotychczasowa konfiguracja bez profilu zachowuje swój kontrakt.
SafetyPanel uzgadnia zegar; RTT ponad 500 ms lub brak świeżego stanu blokują
mutacje. Konfiguracja, odniesienie, ARM i próba mają odrębne zgody.

Domyślny katalog config/local/motion-calibration/ jest ignorowany przez Git.
RIDER_CALIBRATION_DIR może wskazać inny absolutny katalog lokalny.
Nie publikuj fizycznych wyników, profili, eksportów ani pomiarów w PR/GitHub.
Narzędzia i kontrakt domykają zakres kalibracyjny #256; własne fizyczne
parametry operator zbiera lokalnie, bez dodatkowego PR.

Zobacz [odometrię](odometry.md), [ruch fizyczny](physical-motion.md)
i [pracę z robotem](safety.md).


## Sterowanie ręczne i prosta kalibracja reakcji

Widok podstawowy zawiera kamerę, strzałki i STOP oraz suwaki jazdy, skrętu i reakcji.
Czas kliknięcia znajduje się w ustawieniach zaawansowanych. Suwaki prędkości ustawiają
następną pojedynczą próbę; rampa zaczyna obowiązywać po zapisaniu i zastosowaniu.
Ręczne sterowanie wymaga uzbrojenia jednym globalnym przyciskiem po prawej. Nie ma dodatkowej zgody przy każdej strzałce.
Zmiana suwaka, odczyt, zapis, zastosowanie lub powrót wersji nie uruchamiają ruchu.
Nie ma automatycznego powtarzania ani sekwencji kalibracyjnej.

Opcjonalny obiekt profilu interaction zapisuje linear_speed i turn_speed (0–1)
oraz pulse_duration (0.01–0.25 s). Wykonawca udostępnia go w
motion.calibration.interaction; Pi i PC odczytują te same ustawienia z Pi.
Parametry nie stanowią zgody na ruch. Stare profile bez tego obiektu pozostają czytelne.
Rampa i pułap polecenia zachowują dotychczasowy format motion i ograniczenia wykonawcy.
Przyjęcie ustawień nadal wymaga potwierdzenia obu modułów, niezależnie od gotowości
metrycznej odometrii. Zwykłe strojenie nie wymaga dystansu, kątów, HOME ani tabel m/s.

### Mapowanie do SDK Rider 1.4.2

Identyfikator: rider-1.4.2-levels-v2.
- linear_step: podpisany poziom polecenia −127..127, nie licznik obrotów.
- Parametr przekazany do rider_move_x: linear_step * 1.5 / 127, zakres ±1.5.
- turn_step: podpisany poziom −70..70; parametr skrętu SDK ma tę samą wartość.
- motion.output.units = command_levels; mapping_id, linear_sdk_value i
  turn_sdk_value opisują mapowanie, nie zmierzoną prędkość ani ukończenie ruchu.
- Neutralny bajt rejestrów prędkości to 128. Adapter koryguje zaokrąglanie SDK
  w swoim kontrolowanym hooku; nie modyfikuje zainstalowanej biblioteki.
- Czas ogranicza długość polecenia. Prędkość ogranicza jego wartość.
- Pomiary odometrii wymagają conditions.command_mapping zgodnego z tym identyfikatorem.
  Dawne zapisy pozostają do wglądu, lecz bez zgodności skali model jest niegotowy.
  Zmiana mapowania wymaga nowych pomiarów; nie migrujemy współczynników automatycznie.

Formularze pomiarów, odometrii, HOME i diagnostyka pozostają w zwiniętej części
zaawansowanej. Ocena operatora „za szybko / za wolno” służy dopasowaniu sterowania;
nie potwierdza metrycznej odometrii ani autonomii.

## Globalne uzbrojenie panelu i oddzielna zgoda testowa

Jeden przycisk po prawej pokazuje potwierdzony stan wykonawcy: czerwony
„Robot rozbrojony”, zielony „Robot uzbrojony”. Kliknięcie czerwonego jest
zgodą operatora na ręczne sterowanie z panelu; kliknięcie zielonego wysyła STOP.
Kasowanie programowego ESTOP i ARM odbywa się po jednym świadomym kliknięciu,
sekwencyjnie, dopiero po świeżym potwierdzeniu DISARMED. Zewnętrzny ESTOP,
brak sprzętu, brak świeżego zegara lub brak potwierdzenia nadal blokują ARM.
Uzbrojenie nie wywołuje ruchu. Nie ma automatycznego uzbrajania ani odnawiania
zgody; pozostaje limit 30 sekund. Przejście do innego widoku nie wysyła STOP.

Kontrakt bezpieczeństwa dodaje execution_context (panel/test),
panel_motion_enabled i test_motion_enabled. Panel wysyła execution_context=panel.
Zgoda panelu nie uprawnia poleceń testowych, nawet z test_operator_consent=true.
Ręczna fizyczna próba ma osobną sesję execution_context=test i jawne
test_operator_consent=true przy ARM i każdym poleceniu ruchu. Sesja testowa
nie uprawnia panelu. Jedna sesja wykonawcy zapobiega równoległemu sterowaniu.
STOP zawsze unieważnia obie flagi.

Automatyczne pytest/CI pozostaje izolowane: prawdziwy SDK, porty sprzętowe,
SSH i sieć robota są zablokowane niezależnie od obu flag. Flaga zgody testowej
nie wyłącza tej izolacji. Skrypt manual_motion-probe.py wymaga obecnego
operatora, terminala i wpisania jednorazowego potwierdzenia; po próbie wysyła STOP.
