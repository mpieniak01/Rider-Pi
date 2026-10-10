# Polityka dokumentacji

Repozytorium zawiera utrzymywaną dokumentację projektową w `docs/` (EN)
i `docs_pl/` (PL): wizję, architekturę, interfejsy, konfigurację, instrukcje
developmentu i obsługi. Po dodaniu lub przeniesieniu dokumentu aktualizujemy
oba indeksy językowe.

| Materiał | Lokalizacja | GitHub |
| --- | --- | --- |
| Dokumentacja projektu i informacje o wydaniach | `docs/`, `docs_pl/`, główne przewodniki repo | Publikujemy |
| Obrazy i diagramy używane w dokumentacji | `docs/assets/`, `docs_pl/assets/` | Publikujemy |
| Plany, checklisty zadań i materiały robocze | `_to_do/` | Lokalnie, ignorowane |
| Notatki ukończonych zadań, audyty i raporty sesji | `_done/` lub `done/` | Lokalnie, ignorowane |
| Ustawienia i poświadczenia developera | `.env`, prywatne `.env.*`, `evn.ssh.local`, `config/local/` | Lokalnie, ignorowane |
| Publiczne szablony konfiguracji | `.env.example`, `.env.*.example` | Publikujemy z placeholderami |

Katalogi lokalne mogą znajdować się również wewnątrz obu drzew dokumentacji.
Nie dodajemy ich do Git, załączników PR ani paczek wdrożeniowych. Stare nazwy
`archive/`, `_todo/` i `_pr_summaries/` również oznaczają materiały robocze.

Przed publikacją usuwamy z dokumentu ścieżki konkretnej sesji, inwentaryzację
hostów, logi wykonań, rozmowy review i checklisty zadania. Wynikowe opisy
interfejsów, instrukcje obsługi i decyzje architektoniczne zapisujemy w publicznym
przewodniku. Datę, rewizję i rezultat konkretnego testu przechowujemy w lokalnym
rekordzie zadania. Funkcje planowane opisujemy jako plany, bez deklaracji
potwierdzonego działania na sprzęcie.

Odnośniki publiczne prowadzą do innych publikowanych plików, assetów projektu
lub trwałych źródeł zewnętrznych. Link do ignorowanego raportu lokalnego nie
zadziała w nowym klonie repo. Utrzymujemy jedno źródło danego dokumentu;
tłumaczenia mogą mieć własne nazwy i indeksy.

Wycofując wcześniej śledzony plik operacyjny, zachowujemy kopię lokalną i usuwamy
go z indeksu Git. Sama reguła ignore nie wycofuje już śledzonego pliku.
Przed commitem sprawdzamy `git diff --cached --name-status`. Nie używamy
`git add -f` dla notatek lokalnych ani poświadczeń.
