# Sonar i pokrycie testami

Workflow `Sonar quality gate` działa dla PR w tym repozytorium i dla push do
main. Pobiera dokładny opublikowany SHA, wykonuje izolowane testy Python 3.9
oraz Node 22, importuje oba raporty pokrycia i czeka na wynik bramki Sonara.
Istniejące workflow Tests i Quality Guard pozostają aktywne.

Token jest sekretem repozytorium GitHub Actions `SONAR_TOKEN`. Otrzymuje go
wyłącznie krok skanera, przez środowisko kontenera. Workflow nie zapisuje go
w repozytorium ani nie wstawia do poleceń powłoki. Entrypoint przypiętego obrazu
wewnętrznie mapuje go na właściwość uwierzytelniania skanera. PR z forka bez sekretu wymaga zaufanego
skanu ręcznego; brak sekretu jest widocznym błędem, a nie pozornym sukcesem.
Automatic Analysis w Sonarze pozostaje wyłączone; skan uruchamia CI.

## Odtwarzanie

Polecenia są w [instrukcji EN](../docs/QUALITY_GATE.md). Korzystaj z istniejącego
venv oraz Node 22. Na hoście Windows można użyć istniejącego Node 22 wobec
tego samego checkoutu WSL. Raporty Python obejmują również `scripts`; wyniki
JavaScript są importowane jako LCOV. Wszystkie wyniki powstają w ignorowanym
katalogu `docs_pl/_done/ci-sonar`.

Moduły JavaScript są mierzone pod rzeczywistymi nazwami plików, bez zmiany ich
kodów źródłowych. Fixture ze wstrzykniętymi zależnościami zachowują pozycje znaków
i linii oryginału. Normalizator zachowuje trafienia linii i warunków, odrzuca
nieistniejące ścieżki oraz nie uwzględnia końcowego wiązania dodanego przez fixture
jako kodu produkcyjnego. Testy procesów wdrożenia przypisują wysyłany kod do jego
prawdziwego pliku. Poprzednio część poprawnie wykonanych testów nie trafiała do
raportu źródeł, przez co Sonar pokazywał 0% dla tych plików.

## Zakres bramki

Zachowana baza main to poprzednia wersja z 2026-02-17. Zielony wynik PR nie
usuwa zaległości main. Bramka wymaga m.in. niezawodności A, bezpieczeństwa A
oraz co najmniej 80% pokrycia nowego kodu, a także odpowiedniego poziomu
duplikacji i przeglądu hotspotów. Nie obniżamy progów, nie resetujemy bazy i nie
wykluczamy plików produkcyjnych dla uzyskania zielonego wyniku.

Naprawy kodu i indywidualne klasyfikacje zgłoszeń należy rozliczać osobno.
Po świeżym skanie main porównuj identyfikatory; przeniesienie wskazania do
funkcji pomocniczej nie oznacza jego naprawy. CI nigdy nie wykonuje ruchu robota.
