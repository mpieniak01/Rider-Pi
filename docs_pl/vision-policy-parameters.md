# Parametry interpretacji obrazu

Operator wybiera niezmienny preset Ostrożny, Zrównoważony lub Płynny albo własne
korekty oparte na jednym z nich. Wybór presetu przywraca jego wersjonowane wartości.
Edycja zaawansowanego pola pokazuje „Własny na bazie: Płynny”, zamiast zmieniać
znaczenie presetu. Legacy pozostaje osobną polityką zgodności bez korekt.

## Rewizje i właściciele

Pi zapisuje wybór, korekty i rewizję konfiguracji. Venom wykonuje tę samą definicję
i dołącza skrót polityki do decyzji. Rewizja 1 zachowuje pierwotne wartości i skrót.
Rewizję 2 wybiera się jawnie; zapisanej rewizji 1 nie migrujemy przy starcie.

Przykład selekcji:
`{version:1, profile_id:"fluid", profile_revision:2, overrides:{obstacle_support_frames:3}}`.
Pominięcie overrides przywraca preset; zapisujemy tylko zmienione pola.
Transakcja `/api/navigation/config` sprawdza oczekiwaną rewizję, zatrzymanie zadań
i wykonawcy oraz tożsamość modelu. Zmiany unieważniają odbiór jazdy i zapisują
tryb obserwacji. Zapis nie uruchamia kamery, obserwacji, modelu, ARM ani ruchu.

`behavior_catalog.parameter_editing_version=1` ogłasza obsługę edycji.
parameter_schema określa typy, granice, kroki i grupy. Starszy peer udostępnia
wyłącznie dotychczasowe wybory. active_parameters to rozwiązana polityka;
active_base_parameters to te same ustawienia modelu bez własnych korekt.

## Etap modelu

Ustawienia wybranego modelu obejmują:

- DA2: początkowo residual_limit=0.06, outlier_limit=0.005, slope_min=2.0.
  Residual to względne odchylenie głębi, nie centymetry; 0.005 to 0,5%.
- Modele semantyczne ADE20K: pewność piksela, pokrycie podłogi, niepewność,
  udział regionu i jawne floor_only/floor_rug. Pewność modelu nie jest
  prawdopodobieństwem kolizji.

Kolejność: preset, ustawienia wybranego modelu, jawne korekty profilu.
Interpreter, agregacja i prezentacja efektywnych wartości semantycznych używają
tej samej końcowej korekty. Progi modelu głębi pozostają osobne.
Zmiana presetu nie zastępuje wag ani transportu i nie tworzy kalibracji kamery.

## Początkowe wartości Płynny, rewizja 2

Region wymaga wsparcia w 2 z ostatnich 3 obserwacji. Niepotwierdzona przeszkoda
staje się niepewnością, nigdy potwierdzoną podłogą. Nadal obowiązują testy
pokrycia i niepewności. Trwały region może uruchomić bliską blokadę.
Niezależne wsparcie krytyczne i dowody kolizji 3D pozostają zachowane.
Ostrożny i Zrównoważony r2 domyślnie wymagają jednej obserwacji.
Te same pola eksperckie są dostępne dla każdego presetu r2 poza Legacy.

| Parametr | Płynny r2 | Granice | Grupa |
| --- | ---: | --- | --- |
| pixel_confidence | 0.7 | 0.05–1.0 float | evidence |
| min_region_fraction | 0.003 | 0–0.02 float | evidence |
| thin_span_fraction | 0.15 | 0.01–1.0 float | evidence |
| near_zone_fraction | 0.35 | 0.05–1.0 float | evidence |
| min_floor_fraction | 0.92 | 0.5–1.0 float | evidence |
| min_near_floor_fraction | 0.95 | 0.5–1.0 float | evidence |
| max_uncertain_fraction | 0.06 | 0–0.5 float | evidence |
| enter_frames | 3 | 1–8 int | temporal |
| enter_ms | 100 | 0–1000 int | temporal |
| release_frames | 3 | 1–8 int | temporal |
| release_ms | 100 | 0–1000 int | temporal |
| history_ms | 500 | 100–2000 int | temporal |
| max_gap_ms | 300 | 50–1000 int | temporal |
| max_uncertain_ms | 200 | 0–1000 int | temporal |
| min_tracking_ratio | 0.5 | 0.1–1.0 float | temporal |
| slow_speed_factor | 0.6 | 0.1–1.0 float | temporal |
| obstacle_support_frames | 2 | 1–5 int | persistence |
| obstacle_window_frames | 3 | 2–5 int | persistence |
| obstacle_match_overlap | 0.1 | 0.01–1.0 float | persistence |
| obstacle_match_tolerance_px | 1 | 0–3 int | persistence |
| obstacle_min_previous_coverage | 0.9 | 0.5–1.0 float | persistence |
| object_tracking_enabled | false | boolean | objects |
| object_min_area_px | 80 | 8–4096 int | objects |
| object_match_iou | 0.1 | 0.01–0.9 float | objects |
| object_appearance_min | 0.2 | 0–1.0 float | objects |
| object_area_ratio_min | 0.5 | 0.1–1.0 float | objects |
| object_area_ratio_max | 2.0 | 1.0–5.0 float | objects |
| object_max_gap_frames | 2 | 0–3 int | objects |
| object_trend_frames | 3 | 2–5 int | objects |
| object_growth_min | 1.1 | 1.0–3.0 float | objects |
| object_lower_min_px | 2 | 0–40 int | objects |

Udziały mają skalę 0–1; ms i px są częścią nazw pól. Liczba potwierdzeń nie
przekracza okna obserwacji, a limity czasu mieszczą się w historii.
Nieprawidłowe wartości, liczby niefinitywne, nieznane pola i stare rewizje są
odrzucane bez zapisu. Źródłem zakresów jest [schemat](../services/policy_parameters.py);
definicji presetów — [navigation_profiles](../services/navigation_profiles.py).

## Diagnostyka obiektów

Śledzenie obiektów jest domyślnie wyłączone i służy wyłącznie diagnostyce.
Używa map bieżącego modelu, bez ładowania kolejnego. Mapa semantyczna może
dostarczyć propozycje całej klatki. DA2 używa szerszego kontekstu względnej
głębi i tej samej płaszczyzny, bez zmiany regionu oceny.
Propozycje nie są gwarantowanymi maskami pojedynczych obiektów.

Po włączeniu obraz pokazuje fioletowe ramki, ID śladu, wzrost i przemieszczenie
w dół. Obraz i adnotacja pochodzą z jednej klatki. temporal.objects zawiera
rozmiar, przecięcie toru, obcięcie i dostępną pewność semantyczną.
Włączenie diagnostyki ani parametry wzrostu nie zmieniają GO/SLOW/STOP.

Dopasowanie ogranicza zmiany pola, zachowuje ograniczoną historię braku detekcji
i szacuje wspólny ruch obrazu. Ruch kamery, obcięcia i złączenie segmentów mogą
zniekształcić wzrost. To nie odległość, czas do kolizji ani kwalifikacja jazdy.

## Praca operatora

Otwórz „Poziom ostrożności → Parametry profilu”, wybierz preset r2, zmień pola
i jawnie zastosuj. Widoczne pozostają rewizja Pi i etykieta własnej konfiguracji.
Przywrócenie presetu usuwa korekty; Odśwież odrzuca niezapisany szkic.
Zapis w innym panelu unieważnia stary szkic zamiast go nadpisywać.
Progi wybranego modelu pozostają w sekcji jego ustawień.

Kalibracja, założenia o pomieszczeniu, świeżość transportu i odbiór fizyczny
pozostają niezależne. Pewność i residual nie tworzą geometrii w centymetrach.
[Profile](apps/navigation-profiles.md) · [Modele](apps/perception-models.md).
