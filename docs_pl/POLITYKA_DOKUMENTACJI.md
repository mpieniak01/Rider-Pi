# Polityka dokumentacji

Utrzymujemy dwie aktualne wersje dokumentacji projektu: `docs_pl/` (PL)
i `docs/` (EN). Punktem wyjścia jest wersja polska; zmiany kontraktów,
konfiguracji i instrukcji aktualizujemy także po angielsku w tym samym commicie.
Indeksy obu języków wskazują wyłącznie na utrzymywane dokumenty i assety.

| Materiał | Miejsce | GitHub |
| --- | --- | --- |
| Wizja, architektura, kontrakty, instrukcje, wydania | `docs_pl/`, `docs/`, główne przewodniki | Publikujemy |
| Obrazy i diagramy używane w dokumentacji | `docs/assets/`, ewentualnie `docs_pl/assets/` | Publikujemy |
| Plany i prace w toku | `docs_pl/_to_do/` | Lokalnie, ignorowane |
| Ukończone zadania, audyty i raporty sesji | `docs_pl/_done/` | Lokalnie, ignorowane |
| Ustawienia developera i sekrety | `.env`, prywatne `.env.*`, `evn.ssh.local`, `config/local/` | Lokalnie, ignorowane |
| Szablony konfiguracji bez sekretów | `.env.example`, `.env.*.example` | Publikujemy |

Katalogi operacyjne istnieją tylko w `docs_pl/`. Nie tworzymy ich kopii
w `docs/` ani osobnych katalogów `done`. Po scaleniu usuwamy puste katalogi.
Historyczne materiały można zachować pod `_done/`; różne wersje pozostają
oznaczone, a identycznych kopii nie powielamy.

Do dokumentacji publicznej trafia wynik pracy: opis interfejsu, procedura
lub decyzja projektowa. Logi, checklisty, inwentaryzacja hosta i wyniki
konkretnego uruchomienia pozostają lokalne. Nie dodajemy ich przez `git add -f`,
do załączników PR ani do paczek wdrożeniowych. Link publiczny nie wskazuje
na lokalny plan lub raport. Funkcje planowane opisujemy jako planowane.

Przed commitem sprawdź `git diff --cached --name-status` i
`git diff --cached --check`. Ignorowanie pliku nie usuwa go z indeksu Git;
wcześniej śledzony materiał operacyjny odłączamy, zachowując kopię na dysku.


## Weryfikacja aktualności

Źródłem kontraktu są bieżąca rejestracja tras, walidatory i deskryptory konfiguracji,
nie data ostatniej edycji dokumentu ani historyczna etykieta wydania.
Sprawdzaj osobno: obecność celu linku, kotwicę nagłówka, dostępność przewodnika
z indeksu oraz zgodność opisu z kodem. Istniejący link nie dowodzi aktualności.

Przy zmianie parametru aktualizuj oba języki i wszystkie powielone limity
w kontrakcie, przewodniku aplikacji i opisie UI. Domyślna wartość, dopuszczalny
zakres i aktywny zapis na urządzeniu są osobnymi faktami.
Dla profili podawaj rewizję; dla API oddzielaj kopertę, schemat i rewizję danych.

Różne nazwy plików w PL/EN są dopuszczalne (np. BRAMKA_JAKOSCI/QUALITY_GATE,
WDROZENIE/DEPLOYMENT). Główne przewodniki EN PROJECT/ARCHITECTURE/WORKING-AGREEMENTS
znajdują się w korzeniu repozytorium, a ich wersje PL w docs_pl.
Nowe samodzielne tematy otrzymują odpowiednik i odsyłacze w obu indeksach.
Opisy dawnych tagów oznaczaj jako historyczne; planu wdrożenia ani ustawień
jednego urządzenia nie przedstawiaj jako aktualnej instrukcji projektu.
