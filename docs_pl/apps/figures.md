# Własne figury Ridera — lokalne próby ręczne

Figury wykonuje `FigureSequences` w istniejącej pętli `motion-executor`.
Nie uruchamiamy programów producenta ani ACTION, PERFORM czy generatorów
okresowych firmware. Nie ma dodatkowego procesu ani drugiego właściciela UART.

To własne, eksperymentalne receptury do ręcznej oceny. Nie są jeszcze
fizycznie zakwalifikowanymi kopiami figur producenta. ACK potwierdza
przyjęcie polecenia, nie wykonanie fizyczne. Status `completed` oznacza
koniec zaprogramowanej sekwencji, a `physical_completion` pozostaje `unverified`.

## Receptury v1

- `sway`: przechył 0, +3, -3, +3, -3, 0 SDK.
- `vertical`: wysokość 90, 95, 85, 95, 90 SDK.
- `forward_backward`: krótki przejazd w przód i w tył z zerowym wyjściem pomiędzy.
- `snake`: cztery odcinki jazdy z naprzemiennym skrętem i zatrzymaniami.
- `lift_rotate`: wysokość 90, 95, 85, 90 SDK połączona z obrotem, następnie STOP.
- `circular_sway`: zsynchronizowane zmiany wysokości i przechyłu; bez jazdy po okręgu.

Figury korzystają maksymalnie z 30% zapisanej prędkości kierunku,
z dodatkowym maksimum 0.25 i aktualnym globalnym limitem prędkości.
Nie zmieniają aktywnego profilu, jego minimum/maksimum ani ramp.
Za wysokie minimum kierunku jest odrzucane przed uzbrojeniem.
Wysokość i przechył są nastawami SDK, nie pomiarami pozycji.
Początkowe pozycje są jawne w katalogu i planie operatora.
Przy nieznanej poprzedniej pozycji pierwszy cel jest nastawą początkową;
nie udajemy pomiaru, z którego można wyliczyć fizyczną szybkość tego przejścia.

## Sterowanie i zatrzymywanie

W panelu manualnym sekcja Figury ma wybór, opis, Start, Przerwij oraz eksport JSON.
Wybór figury i odczyt statusu są bezruchowe. Start jest jawną zgodą na cały
widoczny plan, przez dotychczasową bramę operatora.
Receptur nie przesyła przeglądarka: Pi wybiera własną, wersjonowaną definicję.

Panel podtrzymuje wyłącznie istniejący run co około 200 ms. Brak kontaktu
przez 500 ms kończy run; spóźnione podtrzymanie nie może go wznowić.
Ukrycie/opuszczenie sekcji prosi o anulowanie, a niezależny timeout Pi
pozostaje obowiązujący. GET i eksport nigdy nie podtrzymują ruchu.

STOP, rozbrojenie, E-Stop i przejęcie ręczne usuwają pozostałe kroki.
Przerwanie zeruje napęd i nie odsyła robota automatycznie do pozy początkowej.
Ostatnia zadana wysokość/przechył pozostają nastawami; SDK STOP nie jest
niezależnym hamulcem serw pozycyjnych ani dowodem zatrzymania mechanicznego.
Normalny koniec zawiera tylko powrót zapisany w recepturze, po czym STOP
i rozbrojenie. Restart wykonawcy nie odtwarza historycznego runu.

## HTTP

- GET `/api/motion/figures`: katalog i dostępne osie istniejącego adaptera.
- POST `/api/motion/figures/runs`: Start lub podtrzymanie z `figure_run_id`.
- GET `/api/motion/figures/runs/<request_id>`: bieżący stan i lokalna historia.
- POST `/api/motion/figures/runs/<request_id>/cancel`: STOP ograniczony do generacji tego runu.

Start/podtrzymanie mają `action=arm`, `owner=manual`, `arming_mode=operator`,
`figure_id`, `figure_version=1`, jawny plan i zgodę oraz zwykłe metadane:
request_id/panel_id/generation/seq/ts/TTL/settings_revision. Podtrzymanie
dodatkowo wskazuje istniejący `figure_run_id`; nie może ponownie uzbroić.
Ponowienie identycznego Startu nie wykonuje kolejnej figury.
Nie przyjmujemy dowolnych kroków, natywnych ID akcji ani dodatkowych aktuatorów.

Rodzina kontraktu: `rider.figures` v1. Moduł Venoma udostępnia analogiczne
ścieżki pod `/api/v1/rider/motion/figures` i eksport `/runs/<id>/export`.
Start zawsze trafia do nowego endpointu Pi; starsze Pi nie dostaje zastępczego ARM.

## Dowody i granice

Bieżący run zawiera rewizję i kopię ustawień, kroki, nastawy, czasy,
powód zakończenia oraz do 96 ostatnich zdarzeń. Odrzucone wcześniejsze
zdarzenia liczy `events_dropped`. Trzy poprzednie runy w statusie są
skrócone i oznaczone `evidence_partial`. Dane runtime znikają po restarcie.
Wynik bieżącej próby należy pobrać przyciskiem JSON przed kolejną próbą.
Zewnętrzny film i IMU z istniejącego zbierania próbek są osobnymi dowodami.

Automatyczne testy używają fake adaptera i zegara. Ruchy fizyczne wykonuje
operator po przygotowaniu stanowiska i zatwierdzeniu konkretnej próby.
Do publikacji wymagane jest osobne potwierdzenie każdej receptury, jej
obszaru ruchu, wpływu balansu i przerwania. Lokalne wdrożenie nie daje
takiego potwierdzenia.
