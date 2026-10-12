# Pomiary systemu i odświeżanie panelu

API ma jeden sampler na proces, uruchamiany na żądanie. Liczniki CPU są odczytywane
co 250 ms; ważona średnia CPU, maksimum krótkich próbek, RAM, obciążenie i temperatura
są publikowane razem co sekundę. Żądania HTTP tylko pobierają gotowy pomiar.
Dysk i informacje o systemie są odczytywane co 60 sekund. Po 30 sekundach bez
odbiorców sampler zasypia. Po wznowieniu zostawia rzeczywistą przerwę w historii.

Dotychczasowe tablice CPU/RAM pozostają zgodne. /sysinfo dodaje cpu_peak_pct,
hist_cpu_peak, hist_ts oraz sampling. Wartość bieżąca i ostatni punkt wykresu
pochodzą z tej samej próbki. Wykres pokazuje ostatnie 60 sekund i osobno średnią
oraz szczyt CPU. Szczyt dotyczy okna pomiaru 250 ms, nie chwilowego maksimum
krótszego od tego okna.

Panel korzysta ze wspólnych profili: telemetria 1 s, system 2 s, usługi 5 s,
zasoby 10 s, wizja 2 s i metryki aplikacji 10 s. /sysinfo przekazuje wskazówki
czasowe prezentacji. Wspólny rytm grupuje odczyty komponentów; grupy droższych
odczytów mają przesunięte fazy. Poprawna odpowiedź katalogu jest współdzielona
przez sekundę w obrębie karty. Jawna akcja kamery i negocjacja kontraktu pomijają
cache. Operacje zapisu go unieważniają, również dla wcześniejszych żądań w toku.
Ukryte karty zasypiają, a po błędach odczyty zwalniają.

Czasy sterowania ruchem, odpytywania bramy bezpieczeństwa, podtrzymania kierunku
i synchronizacji kalibracji pozostają dotychczasowe. Wskazówki prezentacji nie
sterują aktuatorami ani watchdogiem. Rider-PC i inni klienci nadal mogą używać
dotychczasowych pól. Przy wielu procesach API każdy ma własny sampler/cache.


Potwierdzone wolne zasoby i błędy odczytu właścicieli współdzielą obserwację przez
5 sekund (zasoby zajęte: 3 sekundy). Odzyskiwanie zasobu nadal wymaga bezpośredniej,
aktualnej diagnostyki; wynik operacji unieważnia cache prezentacji.
