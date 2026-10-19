# Bezpieczeństwo HTTP i plików runtime

Wspólna ochrona działa przed handlerami głównego API, aplikacji kompatybilności,
bridge ruchu i obu workerów voice. Nie uruchamia usług ani nie zmienia zgody
operatora, generacji poleceń, TTL lub reguł STOP.

## Origin i typ treści

Domyślnie przeglądarka może używać własnego originu serwera. Dodatkowe originy
wpisz jawnie w `RIDER_ALLOWED_ORIGINS`, rozdzielając je przecinkami, np.
`http://localhost:3300,https://venom.example:8443`. Zgodność obejmuje schemat,
host i port; domyślne porty HTTP/HTTPS są normalizowane. Nie ma wildcardów,
ścieżek ani wartości `null`. Nagłówek żądania `Origin` z obcej lub niepoprawnej
wartości kończy się HTTP 403 przed wywołaniem handlera. Preflight podlega tej
samej regule. Odpowiedź dla dozwolonego originu wskazuje konkretny origin,
dodaje `Vary: Origin` i nie włącza cross-origin cookies.

Klienci CLI i połączenia między serwerami bez `Origin` pozostają obsługiwane.
Żądanie zmieniające stan z `Sec-Fetch-Site: cross-site` lub `same-site`, lecz
bez `Origin`, jest odrzucane. Nie wystawiaj API do niezaufanej sieci: ta granica
ogranicza żądania przeglądarkowe, nie uwierzytelnia klienta. Autoryzacja bearer
agentów i odtwarzania audio nadal działa niezależnie. Nazwa hosta wyznacza
granicę same-origin dopiero po zaufaniu lokalnym lub operatora. Zgodna para
Host/Origin z niezaufaną nazwą jest odrzucana (ochrona przed DNS rebinding).
Za proxy TLS dodaj publiczny origin HTTPS do listy; aplikacja
nie ufa automatycznie `X-Forwarded-Host`.

Niepuste `POST`, `PUT`, `PATCH` i `DELETE` wymagają JSON (`application/json`
lub `application/*+json`), inaczej zwracają HTTP 415 `unsupported_content_type`.
Puste żądania pozostają obsługiwane, np. rozpoczęcie OAuth lub STOP. Nieznana
długość strumienia nie omija kontroli; dla żądania bez typu JSON sprawdzany jest
najwyżej jeden bajt, po którym niepuste żądanie zostaje odrzucone.

Jawne wyjątki dla istniejących uploadów to `/api/compute/tasks/<task>`,
`/api/voice/playback`, `/api/voice/asr` oraz `/api/asr` workera voice. Typ/format,
limit wejścia i uwierzytelnianie nadal sprawdzają ich handlery. Kontrola Origin
obowiązuje również uploady. `/api/voice/playback/cancel` wymaga JSON.

## Eksport PNG twarzy

`/face/render`, `/api/draw/face` i `/draw/face` mają te same ograniczenia.
Pole `out` przyjmuje nazwę `face.png` albo `face_<nazwa>.png`, gdzie nazwa
zawiera 1–100 liter ASCII, cyfr, myślników lub podkreśleń. Dozwolona jest też
pełna ścieżka o takim basename bezpośrednio w `FACE_RENDER_DIR` (domyślnie
`/tmp`). Podkatalogi, `..`, inne rozszerzenia i inne katalogi zwracają HTTP 400
`invalid_face_output`. Przykłady: `face_api.png`, `/tmp/face_api_test.png`.
Konfiguracja katalogu należy do operatora; nie pochodzi z JSON żądania.

Zapis korzysta z otwartego deskryptora katalogu, losowej nazwy tymczasowej,
`O_EXCL`, `O_NOFOLLOW` i atomowej podmiany. Wynik ma prawa `0600`; podmiana
symlinka lub hardlinka nie modyfikuje pliku, do którego prowadził. Katalog musi
być własnością użytkownika procesu lub roota, nie może być symlinkiem i nie
może być zapisywalny dla innych bez sticky bit. Dla nowej konfiguracji zalecany
jest prywatny katalog operatora. Błąd dostępu zwraca HTTP 503
`face_export_unavailable`. Istniejące pliki PNG można nadpisać w tym zakresie.

Rozmiar jest ograniczony do 16–1024, rotacja do 0/90/180/270 przed renderowaniem;
błąd zwraca HTTP 400 `invalid_face_preview`. `Accept: image/png` bez pola `out`
zwraca podgląd w pamięci. Jawne `out: null` lub puste `out` nie omija walidacji.

## Powód zmiany providera

Opcjonalne `reason` dla zmiany domeny i adresu PC musi być niepustym,
drukowalnym tekstem o długości do 256 znaków. Znaki sterujące, nowe linie oraz
wartości innych typów kończą się HTTP 400 `invalid_provider_reason` przed
zapisem stanu i publikacją BUS. Brak pola oznacza `manual`; jawna pusta wartość
nie jest domyślnym powodem. Logger dodatkowo używa reprezentacji cytowanej.

## Pliki runtime i blokady właściciela

Zapis migawki przez starszy `FileSink` animacji używa losowego pliku `0600`
i atomowej podmiany, tak jak eksport PNG. Nie otwiera już przewidywalnego
`face_latest.tmp`. Wszystkie elementy ścieżki katalogu są otwierane bez
podążania za symlinkami i sprawdzane pod kątem właściciela oraz praw zapisu.
Nazwa wyniku i ustawienia `FACE_LATEST_PATH` / `FACE_LEGACY_PATH` pozostają
obsługiwane; odbiorca pliku musi mieć uprawnienia do odczytu `0600`.

Blokady PID i właściciela UART zachowują dotychczasowe ścieżki, lecz akceptują
wyłącznie zwykły plik należący do użytkownika procesu, z jednym dowiązaniem,
bez praw zapisu grupy i innych użytkowników. Symlinki, hardlinki i pliki obcego
właściciela są odrzucane przed zapisem PID lub uruchomieniem SDK. Prawidłowy
istniejący plik jest ograniczany do `0600`; PID jest aktualizowany dopiero po
uzyskaniu blokady. Inwentaryzacja UART i brama bezpieczeństwa nadal obowiązują.

Plik blokady pozostaje po zamknięciu procesu, aby następny właściciel użył tego
samego inode. Samo istnienie pliku ani zapisany PID nie potwierdzają aktywnego
właściciela. Nie usuwaj ani nie podmieniaj pliku blokady, gdy którykolwiek
korzystający z niego proces działa. Zakończenie procesu zwalnia blokadę systemową.

## Opcjonalne nagrania voice

`save_audio` pozostaje domyślnie wyłączone. Po jego włączeniu katalog nagrań
musi należeć do użytkownika usługi i mieć prawa `0700`; nowe katalogi są tworzone
z tymi prawami. Istniejący katalog dostępny grupie lub innym użytkownikom jest
odrzucany. Operator powinien wcześniej przygotować dedykowany prywatny katalog;
usługa nie zmienia automatycznie praw skonfigurowanego katalogu ani starych nagrań.

WAV otrzymuje losową nazwę, prawa `0600` i jest publikowany dopiero po zakończeniu
zapisu. Kolizja nazwy nie nadpisuje poprzedniego nagrania. Prawa plików i katalogu
nie zależą od liberalnego `umask` procesu. Przechwytywanie audio i jego format
pozostają bez zmian.

## Trwały stan i pamięć poleceń

Generacje LED (`RIDER_LED_STATE_PATH`), stan funkcji (`FEATURE_STATE_PATH`)
i ostatnie polecenie Google (`DATA_DIR/google/last_command.json`) korzystają
ze wspólnego zapisu atomowego. Eksport PNG również sprawdza każdy element
ścieżki katalogu bez podążania za dowiązaniami. Losowy plik tymczasowy powstaje
wyłącznie przez utworzenie nowego pliku; publikacja następuje po ukończeniu
zapisu. Zastąpienie dowiązania docelowego nie zmienia powiązanego pliku.
Błąd zapisu zachowuje poprzednią opublikowaną zawartość.

Nowe pliki mają uprawnienia `0600`, a nowe katalogi `0700`. Istniejące zaufane
katalogi zachowują uprawnienia, w tym `/run/rider-motion` (`0750`). Odczyt wymaga
użytkownika zapisującej usługi lub roota. Przygotuj ścieżki jako użytkownik usługi,
bez dowiązań w katalogach. Wartości JSON, także tekst zawierający `../`, pozostają
danymi i nie wyznaczają nazwy pliku; ścieżki konfiguruje operator.

Błąd utrwalenia stanu nadal blokuje start producenta ruchu bez zapisanej generacji.
Błąd dziennika LED pozostaje wynikiem niepotwierdzonym, a błąd pamięci poleceń
nie przerywa obsługi polecenia i jest logowany. Równoległe zapisy publikują
kompletne pliki niezależnie; nie dodaje to transakcji ani łączenia aktualizacji.

## Zaufanie Host, dostawców i narzędzi CLI

Prywatne adresy liczbowe, loopback i nazwa urządzenia (także `.local`) nadal
obsługują panel. Inne nazwy proxy wymagają `RIDER_TRUSTED_HOSTS` lub hosta
z `RIDER_ALLOWED_ORIGINS`. Dowolna zgodna para Host/Origin nie nadaje sobie
uprawnień; odrzucenie hosta zwraca `host_not_allowed`.
Zdalne adresy dostawców wymagają HTTPS. HTTP pozostaje dla loopback i tuneli SSH.
Odrzucane są dane logowania w URL, znaki sterujące i niejednoznaczne adresy.
Istniejące zdalne adresy HTTP należy przenieść na HTTPS lub szyfrowany tunel
z końcem loopback przed użyciem.

Eksport wyników compute/UART z CLI pozostaje w katalogu uruchomienia, sprawdza
ścieżkę po rozwiązaniu dowiązań i nie nadpisuje istniejącego wyniku. Uruchamiaj
polecenie z właściwego katalogu danych. Diagnostyka HTTP korzysta z list
`RIDER_DIAGNOSTIC_HOSTS` (domyślnie loopback) i `RIDER_DIAGNOSTIC_PORTS`
(8080,8081,443), bez przekierowań i automatycznych proxy. Host urządzenia w LAN
należy jawnie wskazać w konfiguracji operatora.

Blokada LCD wymaga zwykłego pliku z jednym dowiązaniem, bez zapisu dla innych
użytkowników, otwieranego względem sprawdzonych katalogów. Root przy rozruchu
i usługa pi mogą współdzielić istniejącą blokadę otwieraną tylko do odczytu.
Własność wynika z deskryptora i stałego inode; plik nie zawiera poświadczeń.
