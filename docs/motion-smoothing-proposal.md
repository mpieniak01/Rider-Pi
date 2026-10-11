# Przygotowanie: łagodna zmiana siły polecenia

Status: dokument analizy. Realizacja trzech przebiegów opisana w motion-curves.md. Odczyt panelu urządzenia 2026-10-11: rewizja 20;
jazda zwiększanie 50%/s, zmniejszanie 100%/s; skręt 400%/s w obie strony.

## Diagnoza

Obecna funkcja approach ogranicza przyrost wartości polecenia do rate * dt.
Podczas dochodzenia do celu nachylenie jest stałe; na początku i przy osiągnięciu
celu nachylenie zmienia się nagle. Obniżenie rate zmniejsza przyrost polecenia,
ale nie wygładza tych przejść. Nie oznacza to nieuchronnego późniejszego
gwałtownego wzrostu wartości: sam przyrost jest ograniczony przez cały czas.
Nieliniowość reakcji fizycznej i regulator równowagi pozostają osobnymi czynnikami.

Przy 50%/s przejście 0 -> 60% trwa 1200 ms; powrót przy 100%/s trwa 600 ms.
Jednostka %/s oznacza punkty procentowe skali polecenia na sekundę.
Krótkie impulsy obejmują również wygaszanie i zwykle nie osiągają siły docelowej.

## Wariant

Dodać jeden wybór w profilu i w centralnych ustawieniach Pi:
- Stałe tempo: zgodne z obecnym zachowaniem.
- Łagodny start i koniec: ograniczać tempo oraz szybkość zmiany tempa polecenia.

Zwykła rosnąca funkcja logarytmiczna ma największe nachylenie na początku.
Funkcja wykładnicza może zwiększać je przy końcu. Profil S łagodzi oba końce.
To wygładzanie polecenia, nie gwarantowane ograniczenie przyspieszenia fizycznego.

Nie stosować wyłącznie interpolacji typu smoothstep w dotychczasowym czasie:
jej szczytowe nachylenie może przekroczyć istniejący limit.
Zachować 50%/s jako górną granicę nachylenia, dopuszczając dłuższy czas przejścia.
Przechowywać bieżącą wartość oraz tempo zmiany dla obu osi; odnowienie hold
nie może restartować krzywej. Zmiana celu musi wychodzić z aktualnego stanu.
Algorytm ma powstrzymywać przekroczenie celu i zwrotu przez zero,
obsługiwać krótkie impulsy, release oraz zmianę kierunku bez wydłużania TTL.
STOP, watchdog i utrata możliwości wykonania muszą nadal zerować wyjście natychmiast.
Nie podnosić automatycznie siły, minimum ani limitów napędu.

Nie jest potrzebna nowa ciężka biblioteka na Pi.
Przykłady praktyki: https://ruckig.com/s-curve-trajectory.html

## Kontrakt i zapis

Jeden parametr trybu oraz jeden parametr łagodności, wspólne dla jazdy i skrętu.
Pi przechowuje je w nastawach i profilach; klient odczytuje opisy i dozwolone opcje.
Ograniczenia tempa zwiększania i zmniejszania pozostają osobne dla obu osi.
Propozycja łagodności: czas dojścia do limitu tempa w ms. Wartość i zakres
wymagają doboru w realizacji; nie ustalono ani nie zapisano nowej wartości.
Starsze profile przyjmują Stałe tempo; brak nieznanego pola nie zmienia zachowania.
Zmiana trybu nie wysyła ruchu. Ekran sterowania pokazuje ten sam zapisany tryb.

## Formularz

Zamiast niejednoznacznego checkboxa dwa widoczne warianty:
Przebieg: [Stałe tempo] [Łagodny start i koniec].
Tylko w drugim wariancie widoczne pole Łagodność (ms).
Pozostawić Zwiększanie siły (%/s) oraz Zmniejszanie siły (%/s), z krótkimi
podpowiedziami: większa wartość = szybsza zmiana / większa łagodność = płynniejsze przejście.
Nie dodawać bloków instrukcji ani formularzy pomiarów fizycznych.

Bieżące problemy odczytane w przeglądarce:
- szacowany impuls 8,33333333333333%: zaokrąglić według deskryptora jednostki z Pi;
- dwa wyniki w jednej etykiecie suwaka: docelową Siłę odróżnić od szczytu Impulsu;
- aktywny profil ze zmienionymi nastawami: krótki stan Zmienione nastawy;
- dla próby hold prezentować szacunek dojścia do celu, dla impulsu szczyt
  wynikający z aktualnego algorytmu, nie ze starego wzoru liniowego.

## Sprawdzenie przed wdrożeniem

Celowe testy offline: ciągłość wartości i tempa, zachowanie limitów,
brak przeskoku przy odnowieniu hold / zmianie celu, osiągnięcie dokładnego zera,
krótkie impulsy, reversal, STOP, watchdog, błędy dt, profile i migracja.
Sprawdzenie przeglądarkowe: zapis/odczyt tego samego trybu w control i calibration,
wąski i szeroki ekran, jednostki, precyzja, stan zapisany/niezapisany.
Porównanie wykresów polecenia i zapisów TX przez sniffer w oddzielnej sesji operatora.
Ocena fizycznego ruchu wymaga osobnej zgody operatora.
