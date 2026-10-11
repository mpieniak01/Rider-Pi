# Studio buźki i runtime twarzy

Ekran `/face-studio` służy do porównania stylów, tworzenia gestów i jawnego
uruchomienia buźki na LCD. Podgląd i odtwarzanie używają wspólnego renderera,
animatora i katalogu. Funkcja nie wysyła poleceń napędów ani nie zmienia uzbrojenia.

## Obsługa

1. Wybierz gest i styl: **Przyjazna**, **Prosta** lub **Dotychczasowa**.
2. Obejrzyj gest, przewiń czas, ustaw intensywność i tempo. Szczegóły póz są zwijane.
3. Zapisz własny gest; wbudowane gesty można kopiować, ale nie nadpisywać.
4. Dodaj gest do zestawu robota i zapisz ustawienia. **Zapis nie uruchamia LCD.**
5. **Pokaż na LCD** rozpoczyna odtwarzanie; **Wyłącz buźkę** zatrzymuje wykonawcę
   i zwalnia własny zasób LCD. Nie zatrzymuje usług ruchu, kamery ani Device Info.

**Podgląd gestu** renderuje szkic bez sprzętu. **Aktywna buźka** czyta ostatnią
klatkę istniejącego wykonawcy; nie uruchamia drugiego renderera i nie przejmuje
LCD. Jest to obraz programu, a nie potwierdzenie fizycznej widoczności lub
zasilania panelu. Inny właściciel LCD (kamera, Device Info) nie jest zastępowany;
przy zajętym lub nieznanym zasobie start buźki jest odrzucany.

Symulacja mówienia działa wyłącznie w oznaczonym podglądzie. Runtime ust
przyjmuje rzeczywistą znormalizowaną obwiednię odtwarzanego audio przez endpoint
zdarzeń. Samo ustawienie `speak(True)` nie generuje pozornej synchronizacji.

## Parametry i zapis

Studio pobiera zakresy, jednostki, style i emocje z backendu. Czas pokazuje w ms,
parametry grafiki w %. Spojrzenie, brwi i uśmiech: −100…100; powieki i otwarcie
ust: 0…100. Intensywność: 0…100%; tempo: 50…200%. To parametry obrazu.

Tabela póz przebudowuje przejścia na wspólną oś czasu. Oryginalne ścieżki
pozostają zachowane do pierwszej edycji tabeli. Wartości tabeli są zaokrąglone;
edycja świadomie zastępuje je wartościami wyświetlonymi. Zmiana emocji ustawia
jej domyślną pozę w kanałach bez zapisanych ścieżek.

- Własne gesty: `config/local/face-studio.json` / `FACE_STUDIO_LIBRARY`.
- Ustawienia zestawu: `config/local/face-runtime.json` / `FACE_RUNTIME_SETTINGS`.
- Pliki są lokalne, ignorowane przez Git, zapisane atomowo z synchronizacją pliku.
- Pi przechowuje aktywny zestaw urządzenia. WSL ma osobne szkice; import/eksport
  jest jawnym transferem, bez automatycznej synchronizacji.
- Karty przeglądarki odczytują wspólne ustawienia. Zapis z `if_revision` odrzuca
  nieaktualną rewizję kodem 409. Przycisk **Wczytaj ustawienia** rozwiązuje konflikt.
- Zapis gestu, import i zapis ustawień nie aktywują LCD ani ruchu.

## API — rider.face v1

| Endpoint | Znaczenie |
| --- | --- |
| GET /api/face-studio/gestures | Gesty, zakresy, deskryptory, ustawienia i rewizje |
| POST /api/face-studio/gestures | Zapis; opcjonalne id aktualizuje własny gest |
| DELETE /api/face-studio/gestures/&lt;id&gt; | Usuwa własny gest i wybór w aktywnym zestawie |
| POST /api/face-studio/frame | PNG 240×240 szkicu w czasie at (sekundy) |
| GET /api/face-studio/runtime | Stan wykonawcy, ustawienia, settings_revision, deskryptory |
| POST /api/face-studio/runtime | Częściowy zapis ustawień; opcjonalne if_revision |
| POST /api/face-studio/runtime/play | Jawny start; sink=lcd/file/null, expr, gesture_id, fps, duration_s |
| POST /api/face-studio/runtime/stop | Zatrzymuje tylko buźkę |
| POST /api/face-studio/runtime/event | mood / gesture / listening / waiting / audio |
| GET /api/face-studio/runtime/frame | Ostatnia klatka aktywnej buźki; 404 przy wyłączeniu |

Specyfikacja gestu: `contract_version:1`, `name`, `expr`, `duration` (0.05–10 s),
`initial` (ścieżka → wartość), `tracks` (ścieżka → segmenty `t0/t1/v0/v1/ease`).
Stare gesty bez wersji pozostają zgodne. Emocje: neutral, calm, happy, sad,
curious, surprised, sleepy. Kanały: eyes.dx, eyes.dy, eyes.blink, brows.lift,
brows.tilt, mouth.open, mouth.curve. API: −1…1 lub 0…1; czas w sekundach.
Przejścia: lin, in, out, in_out (smoothstep); wybór original zachowuje gest.
Maks. 32 segmenty na kanał, 200 własnych gestów i 64 KiB żądania klatki.
Przy tempie 50% maksymalny czas odtwarzania wynosi 20 s.

Przykłady zdarzeń:
`{"intent":"mood","expr":"happy"}`,
`{"intent":"gesture","id":"builtin:look"}`,
`{"intent":"audio","level":0.6,"playing":true}`.
Audio ma priorytet ust; wygładzenie otwarcia 80 ms, zamknięcia 140 ms.
Brak nowych poziomów przez 250 ms zamyka usta. Zdarzenia wymagają aktywnej buźki;
przyszły dostawca AI/audio jest poza tym przyrostem.

Legacy `/face/play`, `/face/stop`, `/face/state`, `/face/render` i
`/api/draw/face` pozostają dostępne. Bezpośredni `FaceController` domyślnie
zachowuje styl legacy; Studio i wspólny runtime wybierają friendly.

## Wydajność i LCD

- Bezpośredni PIL/RGB → LCD; PNG tylko na żądanie odbiorcy/eksportu.
- Jeden wykonawca, maksymalnie 7 kanałów; nowy zamiar zastępuje stary.
- Idle ma niski priorytet; wraca do pozy spoczynkowej emocji.
- Najnowsza klatka i jej PNG w pamięci; podgląd szkiców ma LRU 16 klatek
  i jeden slot renderowania. Zajęty slot zwraca 429 z Retry-After.
- Stan nieruchomy nie jest ponownie wysyłany na LCD. Zapis do pliku to pierwszy
  diagnostyczny kadr; nie zapisujemy każdej klatki na SD.
- Bateria: maks. 6 FPS, rzadszy idle, wyłączenie po 45 s bez intencji/audio.
  Kabel: maks. 12 FPS, brak automatycznego limitu bezczynności.
  Tryb wybiera operator; bateria 100% nie dowodzi podłączenia kabla.
- Ukryta karta zatrzymuje podgląd, odpytywanie i timery.
- Obrót fizycznego LCD pozostaje **270°**. Bufor prezentacji ma 240×320,
  twarz 240×240 jest wyśrodkowana. Ekran startowy IP/baterii pozostaje istniejący.
- Otwarcie sterownika dopiero po sprawdzeniu własności; zamknięcie dotyczy własnych
  deskryptorów. Wyłączenie podświetlenia wymaga ponownego sprawdzenia zasobu.
  Nie wywołujemy globalnego GPIO.cleanup().

Pomiar bez sprzętu:
`python scripts/face_benchmark.py`.
Porównanie z wcześniejszym kodem:
`python scripts/face_benchmark.py --baseline-ref 354cfddccb7602de4e642d0f454af8f6821364ef`.
Raport rozdziela koszt render+RGB565, CPU jednego rdzenia przy 12 FPS i RAM.
RAM procesu obejmuje zależności; przyrost pętli nie jest pomiarem energii.
Runtime pokazuje także czas renderowania i przekazania zmienionej klatki.
Wyniki urządzenia zapisujemy w [raporcie pomiarów](FACE_PERFORMANCE.md).

## Oprawa postaci

Wybór **Postać** jest niezależny od stylu oczu: Bez oprawy, Piegusek, Kotek
, Robocik i Profesjonalna. Bez oprawy pozostaje domyślne i zachowuje dotychczasowy obraz.
Skórki dodają głowę, uszy i włosy lub antenkę; na nich rysowane są te
same animowane oczy, brwi i usta.

Opcjonalne ustawienie `skin` zapisuje się na Pi razem z resztą nastaw buźki.
Studio wysyła je do podglądu szkicu, a wykonawca korzysta z tej samej zapisanej
wartości. Zapis nie uruchamia LCD. Skórka zmienia wygląd; nie zmienia emocji,
ruchu ani zachowania robota. Import/eksport gestu jest niezależny od postaci.

Deskryptory zwracają `skins` ze stałymi identyfikatorami i nazwami PL/EN.
Starsze ustawienia bez `skin` korzystają z `none`; nieznane identyfikatory są
odrzucane. Oprawa jest rysowana do cache tylko przy zmianie postaci/stylu.
Nadal są najwyżej trzy renderery podglądu i 16 klatek PNG w cache; nie
dodajemy pakietów graficznych ani plików obrazków.


Postać Profesjonalna ma własne dorosłe proporcje: gładki owal, migdałowe oczy,
subtelne brwi i usta, nos oraz włosy, bez kreskówkowych policzków. Wszystkie
siedem emocji, mruganie, spojrzenia i wejście obwiedni audio korzystają ze
wspólnego animatora. To wariant wyglądu; nie tworzy odrębnej osobowości ani
dostawcy mowy. Style zmieniają barwy; dorosła geometria pozostaje w każdym
stylu. Wygładzana i skalowana jest wyłącznie statyczna oprawa przy wyborze;
klatki są rysowane bezpośrednio w rozdzielczości LCD.
