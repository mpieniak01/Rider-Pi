# Przebieg zmiany siły

Select na control i calibration: Liniowy / Łagodny S / Logarytmiczny.
Wartość ramp_mode (0 / 1 / 2) w values jest zapisywana na Pi i w profilach.
Lista opcji i etykiety pochodzą z parameter_schema.ramp_modes.
Starsze ustawienia i profile bez pola przyjmują 0: bez zmiany zachowania.
Zmiana wyboru jest szkicem do przycisku Zapisz ustawienia na robocie.

Liniowy: stałe nachylenie.
Łagodny S: wielomian 6x^5-15x^4+10x^3, łagodny początek i koniec.
Logarytmiczny: log(1+4x)/log(5), największe nachylenie na początku.
Każda krzywa wydłuża czas przejścia odpowiednio do swojego maksymalnego
nachylenia, aby nie przekroczyć ograniczenia %/s.
Przejście 0 -> 60% przy 50%/s: liniowe 1200 ms,
S 2250 ms, logarytmiczne około 2982 ms.
Siła docelowa, minimum, maksimum i krok nie są przeskalowywane.

Odnowienie niezmienionego hold zachowuje postęp krzywej.
Nowy cel rozpoczyna nową krzywą od bieżącej wartości; nachylenie może się zmienić.
To wygładzanie polecenia, nie pełny regulator fizycznego jerk/przyspieszenia.
Przy zmianie kierunku wyjście przechodzi przez zero.
Impuls rezerwuje czas na zejście do zera; jego TTL nie jest przedłużany.
STOP i watchdog omijają krzywą i zerują wyjście.
Wyświetlane impuls ≤ jest wspólną górną granicą z limitów tempa,
nie obietnicą osiągnięcia tej siły w każdym przebiegu.
Krótki impuls z S może być zbyt mały, aby fizycznie poruszyć robotem.

Do wdrożenia potrzebny jest kontrolowany restart wykonawcy i API.
Sniffer jest opcjonalny i po restarcie pozostaje bez aktywnego zapisu.
Sprawdzenie fizycznej reakcji należy do oddzielnej sesji operatora.
