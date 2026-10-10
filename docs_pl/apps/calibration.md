# Kalibracja: profile, pomiary i odniesienie

Panel /calibration korzysta z istniejących modułów JavaScript i Flask.
Nie instaluje pakietów ani modeli. Otwarcie strony wykonuje odczyty;
nie uruchamia usług, nie wysyła ARM, STOP ani prób ruchu.

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
