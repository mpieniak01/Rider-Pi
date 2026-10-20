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

## Jeden nadawca raportu dla opublikowanego kodu

Analizy main i PR z tego repozytorium należą do CI. Uruchomienia dla tego samego
celu Sonara korzystają ze wspólnej grupy współbieżności. Aktywny przebieg kończy
przetwarzanie raportu i ocenę bramki; nowy oczekujący przebieg może zastąpić
starszy oczekujący zgodnie z zasadami GitHub Actions.

Po merge czekaj na workflow uruchomiony przez push main i sprawdź raport dla
jego SHA. Ręczne odświeżenie main uruchamiaj przez **Run workflow** w
`Sonar quality gate`, wybierając gałąź `main`. Trafia ono do tej samej grupy.
Nie uruchamiaj drugiego lokalnego skanera, gdy danym celem zarządza CI.
Równoległe raporty mogą zostać odrzucone przez Sonara jako starsze również
wtedy, gdy dotyczą identycznego commitu.

Kanoniczny lokalny launcher sprawdza stan workflow przed testami oraz przed
wysłaniem analizy. Przy aktywnym CI odmawia lokalnego wysyłania; `--check`
pozostaje odczytem i podaje właściciela skanowania. Lokalny skan jest opcją
awaryjną przy wyłączonym workflow, nie zastępuje błędnego wyniku CI. Jeśli nie
można ustalić właściciela skanowania, nie wysyłaj kolejnego raportu.
Automatic Analysis pozostaje wyłączone. Odtworzenie coverage opisane poniżej
tworzy lokalne pliki bez publikowania analizy.

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

## Większy zakres napraw zaległości

Przed podziałem prac zapisz SHA i identyfikator istniejącej analizy main oraz
identyfikatory wybranych zgłoszeń. Rozdziel pakiety według odpowiedzialności
modułów, z jednym właścicielem każdego pliku. Zintegrowana gałąź wydania musi
przejść testy całego utrzymywanego katalogu, również gdy osobne pakiety
przeszły już testy lokalne. Zachowaj zgodność z Pythonem 3.9 urządzenia.

Przy podziale złożonej funkcji sprawdź wszystkie nowe funkcje pomocnicze.
Zachowaj kolejność walidacji, pierwszeństwo STOP, okresy ważności, blokady,
propagację wyjątków i sprzątanie zasobów. Testy graniczne powinny obejmować
odmowy i awarie, nie tylko ścieżkę sukcesu. Dla współdzielonych katalogów
porównaj też kolejność oraz deduplikację wyników.

Lokalna ocena złożoności i zaliczone testy są dowodem pomocniczym. Wynik
Sonara dla opublikowanego SHA dostarcza CI. Po scaleniu sprawdź osobno analizę
main i identyfikatory zamkniętych oraz pozostałych zgłoszeń; same statystyki
PR nie potwierdzają usunięcia globalnych zaległości.

## Odznaki i kontrole PR

README PL/EN pokazują dostępne kontrole, zgodnie z ich zakresem:

| Wskaźnik | Zakres |
| --- | --- |
| Tests | Workflow push na `main`; Python 3.9, API i wybrane izolowane fixture JavaScript. |
| Quality Guard | Workflow PR; Ruff 0.6.9, długość zmienianych plików Python, statyczny systemd i API. |
| SonarCloud Quality Gate | Wynik ostatniej analizy `main`, nie aktualnie otwartego PR. |
| Coverage | Całkowite pokrycie `main`, odrębne od progu nowego kodu. |
| Snyk | Zewnętrzny monitoring zależności; odznaka „monitored” nie jest werdyktem konkretnego PR. |
| GitGuardian | Odznaka informacyjna; wynik wykrywania sekretów odczytujemy z kontroli PR. |

Przy scalaniu sprawdzaj kontrole i statusy bieżącego head SHA. Puste dane,
queued i in_progress nie oznaczają zaliczenia. Quality Guard działa na PR;
nie przedstawiamy go jako osobnego przebiegu push `main`. Warunkowo pominięty
`systemd-smoke` nie potwierdza działania systemd ani sprzętu. Jego zakres jest
osobny od statycznej walidacji unitów w Quality Guard. Wymagania scalania
wynikają z aktualnej ochrony gałęzi, a nie liczby odznak. Opcjonalna recenzja
lub jej limit nie zastępują testów i nie wymagają ponawiania bota.

Warunki Sonara dla nowego kodu obejmują rating A niezawodności, bezpieczeństwa
i utrzymania, pokrycie co najmniej 80%, duplikację najwyżej 3% i 100% przejrzanych
hotspotów. Zielona bramka i zerowe liczniki zależą od bieżącego raportu;
nie zapisujemy ich jako stałych zielonych odznak. Publikacja nowej wersji
projektu według [zasad wersjonowania](WERSJONOWANIE.md) nie resetuje bazy Sonara.
