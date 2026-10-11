# Sterowanie ręczne: parametry urządzenia i zamiar operatora

Rider-Pi przechowuje kalibrację i profile. Klienci odczytują
GET /api/calibration/controls w kanonicznej kopercie API v1,
rodzina rider.manual_settings v2. Zapis pozostaje na tym samym URL przez POST.
Nie powstaje druga kopia konfiguracji na PC ani w Venom.

## Opis parametrów

Addytywne parameter_schema.version=1 zawiera direction_fields oraz
value_fields. Każde pole deklaruje type, unit, display_unit,
display_factor, minimum, maximum, display_precision, meaning;
krok ma exclusive_minimum=true. Wartość widoczna = wartość API ×
display_factor. Zapis dzieli przez ten sam czynnik dokładnie raz.
Jednostki API pozostają stałe: poziom polecenia 0–1, sekundy i poziom/s.
Procent nie oznacza prędkości w m/s ani procentu maksimum profilu.
Pole units pozostaje aliasem legacy tylko dla siły polecenia.

Granice w opisie oznaczają możliwości techniczne; minimum/maksimum w
directions oznaczają kalibrację danego profilu. Zero oznacza brak ruchu,
również gdy minimum niezerowego polecenia jest większe od zera.
constraints opisują zależności; ostateczną walidację wykonuje Pi.
Klient nie wykonuje tekstu reguł jako kodu. Nieznane dodatkowe pola są
tolerowane; nieznana wersja opisu lub tryb nie uprawnia do ruchu.

## Zamiar ruchu

control_modes.version=1 ogłasza obsługiwane tryby, kierunki, endpoint,
odstęp odnowień, timeout i semantykę zatrzymania. Komenda:
action=move, direction=forward|backward|left|right,
mode=pulse|hold|release, device_settings=true, settings_revision.
Pozostają obowiązkowe: source=manual, execution_context=panel,
generation, seq, request_id, ts, ttl_ms. Klient nie przesyła vx/yaw/duration
razem z device_settings.

- Brak mode oznacza pulse, zgodny z dotychczasowymi klientami.
- Pulse używa czasu i siły kierunku z kalibracji.
- Hold używa siły kierunku i wygładzania z Pi. Odnawiany co 150 ms;
  brak odnowienia przez 500 ms kończy ruch bez rozbrojenia operatora.
  Timeout nie jest czasem impulsu i nie przycina siły rampą końca impulsu.
- Release wyznacza cel zero, wyhamowuje i pozostawia uzbrojenie.
  Najpóźniej po 500 ms następuje twarde zatrzymanie; bardzo wolne
  wygładzanie nie może wydłużyć tego ograniczenia.
- STOP natychmiast zatrzymuje, rozbraja i unieważnia generację.
- Hold/release są dostępne tylko w sesji operator/manual/panel.
  Nie rozszerzają uprawnień testów ani autonomii.

Ostatnia poprawna sekwencja zastępuje cel; nie ma kolejki jazdy do
odtworzenia. Przeciwne kierunki przechodzą przez zero i przerwę nawrotu.
Panel ma jedno żądanie w toku i jeden najnowszy zamiar. Przed faktycznym
wysłaniem ponownie sprawdza aktualność gestu, rewizji i generacji;
STOP unieważnia także żądania czekające na negocjację kontraktu.
Puszczenie, pointercancel, utrata capture/fokusu i ukrycie strony kończą
przytrzymanie. Zanik strony/sieci jest ograniczony watchdogiem Pi.

## Gesty, wersje i potwierdzenia

Kliknięcie krótsze niż 180 ms: jeden impuls. Przytrzymanie: hold;
puszczenie: release. Mysz, dotyk oraz strzałki/WASD korzystają z tej samej
obsługi na sterowaniu i kalibracji. Edycja pól nie przechwytuje klawiszy ruchu.
Nowy kierunek zastępuje poprzedni; puszczenie starego klawisza nie kończy
nowszego zamiaru.

Wersja koperty, wersja kontraktu, wersja opisu i rewizja ustawień są
odrębne. Stan wykonawcy podaje manual_settings.revision zastosowanego
zapisu oraz intent_mode, target i output. Zapis konfiguracji jest
dozwolony wyłącznie w bezruchu, również przy uzbrojonym robocie.
Potwierdzenie SDK nie jest dowodem fizycznego wykonania.

Nowe granice istniejących parametrów nie wymagają zmian w kliencie
czytającym opisy. Nowa funkcja/typ parametru może wymagać nowego widoku.

## Weryfikacja

Testy celowe używają tylko atrapy wykonawcy i przeglądarki WSL.
Fizyczne próby ruchu wymagają osobnej zgody operatora.
