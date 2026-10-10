# Zadania i sterowanie

Widok /control zawiera jeden katalog zadań oraz jawne przygotowanie ruchu.
[Kontrakt panelu operatora](operator-panel.md) opisuje gotowość,
bezpieczeństwo, metadane, ACK i skróty.

1. Odczytaj aktualny stan oraz możliwości napędów.
2. Przygotuj robota, przestrzeń i przewód zasilania; wpisz konkretny plan próby.
3. Wybierz właściciela, potwierdź przygotowanie i jawnie ARM najwyżej na 30 sekund.
4. Uruchom odpowiednie zadanie albo wyślij krótki ręczny impuls.
5. Obserwuj robota niezależnie od ACK SDK; użyj STOP i zakończ zadanie.

Impulsy ręczne mają znormalizowane wartości -1..1 i czas do 0.25 sekundy.
To żądania, nie zmierzona prędkość ani droga.
Wysokość, balans i gotowe akcje pozostają widoczne, ale zablokowane,
gdy brakuje ręcznej charakterystyki bezpiecznego przerwania.

W/S/A/D i strzałki działają poza polami edycji z aktualną zgodą manual.
Spacja poza polami wysyła STOP. Utrata fokusu, połączenia lub widoku
unieważnia lokalną zgodę i próbuje STOP. Nawigacja i System mają własny
formularz ARM do działania na tym samym widoku.

Obraz znajduje się w /devices, administracja w /system.
Otwarcie widoku lub wybór opcji zadania nie uruchamia usług.
Weryfikacja korzysta z izolowanych atrap; ruch fizyczny wymaga osobnej
świadomej zgody przygotowanego operatora.
