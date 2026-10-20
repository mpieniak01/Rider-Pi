# Priorytet operatora — kontrakt v1

Osobna podróż bez limitu całej sesji ma jawny kontrakt [Automat2 v1](AUTOMAT2_JOURNEY_V1.md); poniższy cykl timed nadal dotyczy trial 10 s.

Rozszerzenie jest jawne: `POST /api/navigation/trial` przyjmuje
`operator_control_version: 1` i niepusty `panel_id`. Dotychczasowe żądania bez tych
pól zachowują dotychczasowy cykl. Ruch nadal wykonuje wyłącznie motion-executor.

## Kamera i życie percepcji

Opt-in uruchamia raz istniejący worker S14. S15 pozostaje starszym trybem samej
obserwacji; przygotowanie S14 zwalnia S15 i nie uruchamia obu producentów naraz.
Ręczna korekta, pauza, wznowienie i wygaśnięcie zgody pozostawiają ten sam worker
oraz źródło obrazu. W pauzie worker tylko analizuje. Zmiana konfiguracji, awaria
procesu i jawne wyłączenie kamery mają osobny cykl; nie są ciepłym wznowieniem.

`POST /api/resource/camera/pipeline` z `action: stop` najpierw unieważnia zależną
sesję przez potwierdzony STOP ograniczony do zaobserwowanej generacji, następnie
zatrzymuje zarządzanego producenta i zwalnia kamerę. Stare powtórzone żądanie oraz
niezgodna rewizja nie zatrzymują nowszej sesji. Obcy konsument daje jawny konflikt.
Start kamery uruchamia wyłącznie obraz i nie daje zgody na ruch.

## Sterowanie i zgoda

Nowe operacje używają `POST /api/control` i dotychczasowego BUS. Każda wymaga
`source: manual`, `execution_context: panel`, `panel_id`, `request_id`,
`generation`, `seq`, `ts`, `ttl_ms` i bieżącej `settings_revision`.

| Operacja | Wynik |
| --- | --- |
| `action: move, intervene: true` | Unieważnia stary automat, wykonuje ograniczoną korektę według ustawień Pi; automat zostaje w pauzie |
| `action: navigation_pause` | Zeruje ruch i przekazuje sterowanie operatorowi, zachowując percepcję |
| `action: navigation_resume` | Przekazuje prawo automatowi w nowej generacji; rozpoczyna kwalifikację |
| Globalny `stop` / `estop` | Dotychczasowa niezależna ścieżka zatrzymania / zatrzasku |

Wersja v1 dopuszcza wyłącznie jawną zgodę nawigacyjną `owner: navigation`,
`arming_mode: timed`, `0 < lease_s <= 10`, związaną z panelem. Przejęcie i
wznowienie zachowują pierwotny deadline i nie przedłużają zgody. Wygaśnięcie
zatrzymuje również ręczną korektę. Następna zgoda wymaga świadomej akcji.
Zwykłe ręczne ARM w trybie operator działa jak wcześniej i nie uprawnia do
wznowienia automatu.

`supersedes_operation_id` na pauzie lub `move+intervene` wskazuje aktualną
operację automatu. Pozwala temu samemu panelowi przerwać własne oczekujące
wznowienie także przed nadejściem ACK, używając jego poprzedniej generacji.
Sekwencja musi przekraczać sekwencję przyjętego wznowienia; szybkie polecenia
NAV w nowej generacji nie wypierają sekwencji operatora. Inna operacja, panel,
stara zgoda, nieświeży TTL lub odtworzenie po STOP nie korzystają z wyjątku.
Transfer daje nową generację i zużywa ten cel. Alias `turn` ma tę samą ochronę
lokalnie; panel wysyła `move`.

Powtórzenie tego samego `request_id` i identycznego żądania zwraca zapisany
wynik bez ponownego wyjścia na aktuator. Zmienione żądanie daje
`operator_request_conflict`. Pamięć obejmuje ostatnie 32 operacje i znika przy
restarcie; starsze generacje/sekwencje nadal odrzuca brama. ACK odtworzony po
nowszym ARM zachowuje pierwotną generację.

## Kwalifikacja i stan

Wznowienie tworzy nowy `run_id`. Pi lokalnie wymaga trzech różnych kolejnych
poprawnych klatek przechwyconych po nowej epoce; sprawdza model, rewizję,
protokół, sekwencję, wiek i kontekst źródła
`camera_session/transport_epoch/pipeline_revision/device_id`.
Licznik `clear_count` z hosta sam nie wystarcza. Niepoprawny lub powtórzony wynik
zeruje serię. Starszy wynik i callback STOP nie mogą dotknąć nowszej generacji.
Po kwalifikacji nadal obowiązują lease decyzji, watchdog i świeżość kolejnych wyników.

Stan bezpieczeństwa zawiera `operator_control`:
`{version:1,state:idle|paused|qualifying|active,operation_id,generation,reason}`.
`panel_control.holder` pozostaje przypisany podczas automatu. Samo `version:1`
oznacza obsługę kontraktu, nie działający proces ani zgodę na ruch.
`GET /api/navigation/status` dodaje `operator_control_version:1`,
`qualification_count` i identyfikator operacji dla opt-in workera; odbiorca musi
również sprawdzić `running`, `stale` i aktualne uprawnienie Pi.

Testy automatyczne używają wyłącznie atrap. Opóźnienia LAN, obciążenie CPU,
zachowanie sprzętowe i droga hamowania wymagają odrębnego odbioru operatora
przed wydaniem. Sam ACK nie potwierdza fizycznego wykonania.

OFF przy aktywnej jezdzie recznej zwraca camera_pipeline_motion_busy bez STOP.
Gdy operator stoi w pauzie sesji nawigacji, jawne OFF konczy takze jej zgode.
Ponowne ON nie przywraca zgody.
