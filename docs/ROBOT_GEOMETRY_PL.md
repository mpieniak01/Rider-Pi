# Wymiary i referencja obrazu XGO-Rider CM4

To trwały punkt odniesienia dla tego egzemplarza Rider-Pi i modułu Venom.
Dane przyjmujemy w projekcie jako obowiązujące: nie wymagają ponownego pomiaru
ani ponownego kwestionowania przy kolejnych zmianach oprogramowania. Jeśli
operator zgłosi zmianę sprzętu, montażu kamery lub pozy referencyjnej, należy
zaktualizować powiązane wartości i zachować historię zmian w Git.

## Wymiary konstrukcji

| Parametr | Wartość | Pochodzenie |
| --- | --- | --- |
| Model | XGO-Rider CM4 | Inwentaryzacja projektu Rider-Pi |
| Długość katalogowa | 135 mm (13,5 cm) | Specyfikacja XGO-Rider CM4 |
| Szerokość katalogowa | 118 mm (11,8 cm) | Specyfikacja XGO-Rider CM4 |
| Wysokość katalogowa | 116–158 mm (11,6–15,8 cm) | Specyfikacja XGO-Rider CM4; zależy od postawy |

Źródła: [opis XGO-Rider CM4](https://wiki.elecfreaks.com/en/microbit/robot/cm4-xgo-rider-kit/products-description/)
oraz [inwentaryzacja sprzętu Rider-Pi](https://github.com/mpieniak01/Rider-Pi/blob/main/docs_pl/FACE_PERFORMANCE.md).

## Ustalone pomiary operatora dla obrazu

Wcześniejszy [PR modułu #53](https://github.com/mpieniak01/venom-module-rider/pull/53)
utrwalił pomiary operatora dla najniższej pozycji i potwierdził ich widoczność
w panelu. [PR Pi #329](https://github.com/mpieniak01/Rider-Pi/pull/329)
zdefiniował zapis referencji na Pi.

| Parametr | Wartość |
| --- | --- |
| Szerokość robota przyjęta w referencji obrazu | 11,5 cm |
| Szerokość toru referencyjnego | 16 cm |
| Wysokość kamery nad podłożem | 14 cm |
| Odległości znaczników | 18, 20, 40 i 60 cm |
| Wymiary obrazu referencyjnego | 320 × 240 px |
| Poza referencyjna | Najniższa (`lowest`) |

Szerokość katalogowa 11,8 cm i wartość 11,5 cm z referencji operatora pochodzą
z różnych zapisów; należy zachować obie wraz z opisem. Szerokość toru 16 cm
jest szerokością toru referencyjnego, a nie długością korpusu.

Zachowana referencja obrazu, wersja 1, rewizja 2, ma współrzędne znormalizowane:

- Lewa krawędź: `[0.375, 0.6916666666666667]`,
  `[0.271875, 0.9958333333333333]`.
- Prawa krawędź: `[0.59375, 0.6916666666666667]`,
  `[0.728125, 0.9958333333333333]`.
- Znaczniki `[odległość_cm, y]`: `[18, 1.0]`,
  `[20, 0.9458333333333333]`, `[40, 0.7541666666666667]`,
  `[60, 0.6666666666666666]`.

Są to zapisane dane konkretnej referencji, a nie polecenie ustawienia postawy.
Aktualna referencja zapisana na Pi ma pierwszeństwo przed wartościami
startowymi interfejsu; sam podgląd wartości nie zapisuje konfiguracji.

## Wykorzystanie w Automat2

Przy zmianach korytarza i logiki omijania najpierw korzystać z powyższych
wymiarów i zapisanej referencji; nie rozpoczynać od pytania operatora o
ponowne zmierzenie robota. Należy jawnie zachować pochodzenie danych, pozę,
wymiary obrazu i konfigurację kamery przy przenoszeniu ich do nowej geometrii.

Referencja z PR #53 i #329 ma status `visual_reference_only`; same wymiary
korpusu i znaczniki nie definiują automatycznie obrysu podczas obrotu ani
nie stanowią zgody na ruch. Obrys zależy także od osi obrotu, postawy,
przebiegu manewru, pola widzenia oraz marginesu. Należy wykorzystać dostępne
wyniki wcześniejszych prób i dokumentację przed określeniem, czy istnieje luka
w danych o **manewrze**. Nie należy mylić tej oceny z ponownym ustalaniem
potwierdzonych wymiarów robota.

Ten dokument jest utrzymywany w obu repozytoriach projektu jako
`docs/ROBOT_GEOMETRY_PL.md`; przy zmianie danych aktualizować obie kopie.
