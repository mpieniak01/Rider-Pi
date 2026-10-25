# Zadania i sterowanie

Widok /control zawiera jeden katalog zadań oraz jawne przygotowanie ruchu.
[Kontrakt panelu operatora](operator-panel.md) opisuje gotowość,
bezpieczeństwo, metadane, ACK i skróty.

1. Odczytaj aktualny stan oraz możliwości napędów.
2. Przygotuj robota, przestrzeń i przewód zasilania; wpisz konkretny plan próby.
3. Potwierdź przygotowanie i jawnie ARM sesję operator/manual/panel.
   Nie ma timera zgody; czasowe sesje testów/nawigacji pozostają osobne.
4. Uruchom odpowiednie zadanie albo wyślij krótki ręczny impuls.
5. Obserwuj robota niezależnie od ACK SDK; użyj STOP i zakończ zadanie.

Ręczne impulsy używają kierunkowych nastaw Pi: wartości -1..1 i czas
0.01–1.0 s (początkowo 0.25 s). Zakres odczytuj z aktualnego deskryptora.
To żądania, nie zmierzona prędkość ani droga.
Wysokość i balans używają ogłoszonych możliwości pozycji/trybu.
Gotowe figury pozostają zablokowane do charakterystyki przerwania.

W/S/A/D i strzałki działają poza polami edycji z aktualną zgodą manual.
Spacja poza polami wysyła STOP. Utrata fokusu, ukrycie strony i puszczenie
kończą hold, ale nie rozbrajają automatycznie operatora. Brak odnowień zatrzymuje
ruch przez watchdog Pi. [Własność panelu](../manual-panel-authority.md) blokuje
odnawianie i zwalnianie polecenia właściciela przez inny panel. Nawigacja i System mają własny
formularz ARM do działania na tym samym widoku.

Obraz znajduje się w /devices, administracja w /system.
Otwarcie widoku lub wybór opcji zadania nie uruchamia usług.
Weryfikacja korzysta z izolowanych atrap; ruch fizyczny wymaga osobnej
świadomej zgody przygotowanego operatora.
