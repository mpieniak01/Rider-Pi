# Studio buźki

Ekran `/face-studio`, dostępny w menu panelu, służy do podglądu i tworzenia
gestów twarzy bez LCD. Wykorzystuje produkcyjny `FaceRenderer` i `Animator`.
Nie otwiera UART/SPI, nie steruje napędami i nie przełącza właściciela LCD.

## Praca z gestami

- Wybierz wbudowane mrugnięcie, spojrzenie lub wyraz twarzy.
- Odtwarzaj, zapętlaj, zatrzymuj i przewijaj czas; zapisz klatkę PNG.
- Utwórz nowy gest lub kopię istniejącego. Dodawaj kolejne pozy i ich czas
  od początku w milisekundach. Pierwsza poza określa stan początkowy.
- Spojrzenie i brwi mają zakres −100…100; zamknięcie powiek i otwarcie ust
  0…100. To parametry grafiki, nie pomiary ani polecenia ruchu robota.
- Zapisz jako nowy lub aktualizuj własny gest. Wbudowanych nie nadpisujemy.
- Import JSON tworzy szkic; zapis utrwala go. Eksport zawiera kompletny gest.

Zmiana tabeli buduje przejścia pomiędzy pozami. Oryginalne ścieżki wbudowanego
lub importowanego gestu pozostają zachowane do pierwszej edycji tabeli.
Tabela pokazuje zaokrąglone parametry; edycja jest świadomym przepisaniem
ścieżek na wspólną oś póz. Wyraz twarzy dotyczy całego gestu.

## Zapis i API

Własne gesty są zapisane atomowo na serwerze panelu w
`config/local/face-studio.json` (lokalne, ignorowane przez Git).
`FACE_STUDIO_LIBRARY` pozwala ustalić inną ścieżkę. Instancja panelu WSL ma
własną bibliotekę; biblioteki urządzenia nie synchronizujemy automatycznie.
Przenoszenie gestów odbywa się przez import/eksport.

- `GET /api/face-studio/gestures`: biblioteka i zakresy parametrów.
- `POST /api/face-studio/gestures`: zapis; opcjonalne `id` aktualizuje własny gest.
- `DELETE /api/face-studio/gestures/<id>`: usunięcie własnego gestu.
- `POST /api/face-studio/frame`: PNG 240×240 dla specyfikacji i czasu `at` w sekundach.

Specyfikacja: `name`, `expr` (neutral/happy/sad), `duration` (0.05–10 s),
`initial` (ścieżka → wartość), `tracks` (ścieżka → segmenty `t0/t1/v0/v1/ease`).
W API wartości mają zakres −1…1 lub 0…1. Dopuszczalne ścieżki:
`eyes.dx`, `eyes.dy`, `eyes.blink`, `brows.lift`, `brows.tilt`, `mouth.open`.
Przejścia: `lin`, `in`, `out`, `in_out`. Maksymalnie 32 segmenty na ścieżkę,
200 własnych gestów. Niedozwolone wartości są odrzucane.

Podgląd pobiera klatki na żądanie, maksymalnie około 12/s, z jednym żądaniem
w toku. Ukrycie karty zatrzymuje odtwarzanie i pobieranie klatek. Nie ma
stałej pętli renderowania na serwerze. Pauza zamraża także mikrodryf źrenic.
Podgląd jest w orientacji czytelnej dla operatora; montaż LCD i kompensacja
270° pozostają bez zmian. Nie jest to kopia aktualnego obrazu fizycznego LCD.
Zapis gestu nie aktywuje go automatycznie w zachowaniu robota.
