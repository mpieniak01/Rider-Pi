# Granica HTTP i eksport PNG

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
agentów i odtwarzania audio nadal działa niezależnie. Porównanie z hostem
żądania nie zastępuje ochrony przed DNS rebinding ani konfiguracji zaufanych
hostów/proxy. Za proxy TLS dodaj publiczny origin HTTPS do listy; aplikacja
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
