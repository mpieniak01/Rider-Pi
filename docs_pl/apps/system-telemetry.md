# Historia i diagnostyka CPU/RAM

`GET /sysinfo` (`rider.system`, wersja 1) zachowuje dotychczasowe pola i dodaje metadane ciągłości. CPU/RAM pochodzą z Linuksa; zasilanie kablem, nauka/leżenie i DISARMED nie oznaczają restartu hosta.

## Próbkowanie i jakość

Kolektor pozostaje współdzielony i działa na żądanie. Bez odczytów usypia po 30 s. CPU jest odczytywany co 250 ms, podsumowanie co 1 s, wolne dane dysku co 60 s. Te wartości nie zostały zmienione. Więcej paneli nie tworzy dodatkowych producentów.

Historia zawiera do 60 rzeczywistych wierszy w pamięci procesu. Nie jest nagraniem sesji i nie odtwarza brakujących próbek. CPU oraz RAM są niezależne: nieznany CPU ma wartość null, ale poprawny RAM nadal trafia do historii. Nieudany odczyt pamięci nie daje pozornego 0%.

Wyjątek nie kończy na stałe kolektora. Próba wznowienia jest ograniczona rytmem podsumowania i nadal respektuje idle. Ostatni dobry snapshot pozostaje ze swoim pierwotnym czasem; `stale=true` sygnalizuje błąd producenta. Po zimnym starcie z błędem wartości są null.

## Dodatkowe pola

| Pole | Znaczenie |
| --- | --- |
| `observation.boot_id` | Tożsamość uruchomienia Linuksa; null, jeżeli nie można jej odczytać. |
| `observation.instance_id` | Tożsamość kolektora w procesie API; zmienia się wraz z jego nową instancją. |
| `observation.generation` | Kolejne uruchomienie kolektora po pauzie. |
| `observation.sequence` | Numer rzeczywistego wiersza w obrębie instancji. |
| `observation.state` | `warming`, `collecting`, `error`; wewnętrznie także `idle` przed ponownym odczytem. |
| `observation.age_s`, `monotonic_s` | Monotoniczny wiek ostatniej udanej próbki i jej czas. |
| `observation.error_count`, `last_error_at`, `last_error_code` | Licznik, czas i nazwa klasy wyjątku; bez surowej treści błędu. |
| `hist_mono`, `hist_generation`, `hist_seq` | Tablice równoległe do dotychczasowych tablic historii. |

`hist_ts` i `ts` pozostają czasem ściennym. Kolejność i pozycja nowych próbek korzystają z zegara monotonicznego, dlatego korekta czasu nie odwraca przebiegu. `cpu_peak_pct` oznacza maksimum zagregowanego CPU w podokresach, nie pojedynczy rdzeń.

## Prezentacja i awarie

Oba panele rysują ostatnie 60 s, wygaszają zachowaną historię według wieku i przerywają krzywą przy luce, brakującym kanale, zmianie generacji lub przerwaniu sekwencji. Starszy format bez metadanych używa znaczników czasu i wykrywania luk. Zgodność wsteczna nie oznacza pełnej diagnostyki restartów starszego API.

Panel zachowuje ostatnią historię po błędzie HTTP. Moduł Venoma nie odmładza powtórzonego wyniku cache i nie przenosi historii między urządzeniami lub sesjami modułu. Potwierdzona zmiana bootu, instancji API lub generacji kolektora daje odrębną etykietę zdarzenia; sama luka nie daje diagnozy restartu.

Awaria tunelu Venoma nie jest dowodem awarii bezpośredniego panelu LAN. Identyfikacja zerwania i konfliktu forwardów wymaga korelacji transportu; przyczyna niepotwierdzona pozostaje nieznana. Ta zmiana nie modyfikuje SSH, częstotliwości, timeoutów, progów bezpieczeństwa ani aktuatorów.

Pole `uptime_s` w `/healthz` mierzy czas procesu API; panel oznacza je jako czas działania API, a nie uptime Linuksa.
