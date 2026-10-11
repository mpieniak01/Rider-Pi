# Development

Rider-Pi i Rider-PC są osobnymi repozytoriami. Wspólny workspace VS Code
nie zmienia katalogu terminala ani wybranego interpretera. Polecenia wykonuj
z właściwego repozytorium i korzystaj z jego środowiska.

```bash
pwd
git status --short --branch
git fetch origin
git log --oneline HEAD..origin/main
.venv/bin/python --version
.venv/bin/python -m pip check
```

Przed aktualizacją sprawdź niezapisane zmiany i stashe. Na czystym `main`
używaj `git pull --ff-only`; wcześniejsze prace zachowuj zamiast resetować.
Zmiany aplikacji prowadź na osobnej gałęzi, z odpowiednimi kontrolami
i review w PR. Same porządki dokumentacyjne mogą trafić bezpośrednio
na `main`, jeżeli właściciel repozytorium tak poleci.

## Dwie ścieżki pracy z urządzeniem

Drobna poprawka może przejść krótką ścieżkę: lokalny commit → `make pi-preview`
→ test funkcji na Pi. Kontrola w WSL jest dobrana do zmiany; pełny pytest nie jest
obowiązkowym krokiem każdej iteracji. Podgląd działa przed push i PR. Kolejny
commit można od razu sprawdzić na urządzeniu; `make pi-rollback` przywraca bazę.

Zaakceptowany kod utrwalamy ścieżką wydania: push → PR → powiązane kontrole
i review → merge → `make pi-release PI_COMMIT=<pełny-hash-main>`.
Kod po review musi odpowiadać temu sprawdzonemu na Pi. Szczegóły, restart
zmienionego komponentu i odzyskiwanie opisuje [wdrożenie](WDROZENIE.md).

## Konfiguracja i notatki lokalne

Korzystamy ze zwykłych lokalnych plików env. `.env`, prywatne `.env.*`,
`evn.ssh.local` i `config/local/` zawierają ustawienia developera i sekrety.
Nie trafiają do Git, załączników PR, logów ani paczek wdrożeniowych.
Publiczne `.env.example` i `.env.*.example` zawierają wyłącznie placeholdery.
Zachowuj istniejący `.env`; nie nadpisuj go szablonem.

Prywatny plik SSH powinien mieć uprawnienia `600`. Hasło wpisuj w lokalnym
edytorze, bez przekazywania go w argumentach poleceń lub dokumentacji.
Zwykły SSH nie wczytuje automatycznie `evn.ssh.local`.

Plany zadań zapisuj w ignorowanym `docs_pl/_to_do/`, a ukończone notatki
i audyty sesji w `docs_pl/_done/`. Nie tworzymy ich angielskich kopii. Utrzymywane instrukcje i potrzebne obrazy
publikuj zgodnie z [polityką dokumentacji](POLITYKA_DOKUMENTACJI.md).
Przed commitem sprawdź `git diff --cached --name-status` oraz
`git diff --cached --check`. Nie dodawaj plików lokalnych przez `git add -f`.

## Środowisko Pi i kontrole

Stosuj [politykę środowisk i testów](POLITYKA_SRODOWISK.md): deklarowane braki
WSL uzupełniaj w istniejącym `.venv` Rider-Pi. Pełne testy automatyczne działają
w WSL/CI, a urządzenie zachowuje zależności wybranych profili wykonawczych.

Runtime obrazu producenta korzysta z Pythona 3.9 na Raspberry Pi OS / Debian.
Nowszy interpreter WSL nie potwierdza zgodności z tym środowiskiem.
Przeczytaj [instrukcje agenta](../AGENT.md) i [ustalenia pracy](WORKING-AGREEMENTS.md).
Korzystaj z istniejących zależności; w zwykłym zadaniu aplikacyjnym
nie instaluj pakietów online na Pi.

Użyj Ruff 0.6.9 z dostępnego środowiska i odpowiednich testów bezpośrednich:

```bash
ruff check .
ruff format --check .
make test TEST_ARGS="-q tests/test_systemd_services.py tests/config/"
.venv/bin/python -m pytest tests/test_version_api.py -q
```

Testy wersji wymagają zależności API. Sprzęt, audio, vision i przeglądarka
mają osobne wymagania; zakres dobieraj do zmiany. Polecenia powyżej są
przykładami, a nie obowiązkowym pełnym zestawem przed każdym podglądem.
Rewizję, polecenie i wynik
zapisuj w lokalnej notatce zadania. Mocki nie potwierdzają pracy silników,
sensorów ani fizycznego śledzenia.

[Panel Pi](ui/panel-diagnostyka.md) korzysta z portu `8080`.
Prace aplikacyjne zachowują rozruch, sieć i SSH.
Przed aktualizacją urządzenia przeczytaj [wdrożenie i odtwarzanie](WDROZENIE.md).


## Szybkie poprawki i naturalne recenzje — ustalenie 2026-10-11

- Lokalny commit i podgląd na urządzeniu nie wymagają push, PR ani recenzji.
  Korzystaj z istniejącego narzędzia Git/SSH Pi, bez doraźnych skryptów
  kopiujących pojedyncze pliki i bez kopiowania całego workspace.
- Nie żądaj płatnych recenzji, nie wywołuj botów przez wzmianki/komendy,
  nie ponawiaj przeglądów i nie dodawaj pustych commitów dla ich uruchomienia.
  Zbieraj naturalnie pojawiające się recenzje, sprawdzaj zasadność uwag
  i naprawiaj rzeczywiste problemy. Brak opcjonalnej recenzji lub limit usługi
  nie blokuje wydania. Nie zmieniaj ustawień GitHub bez osobnego polecenia.
- Zbierz poprawki w spójny zakres wydania. Obowiązują istniejące wymagane CI
  i rzeczywista ochrona gałęzi. Nie czekaj na opcjonalnego recenzenta;
  ewentualną wymaganą przez ochronę gałęzi zgodę zgłoś jako konkretną blokadę.
- Drobne iteracje nie uruchamiają pełnych testów ani instalacji pakietów.
  Kontrole dobieraj do zmiany; testy na polecenie operatora.
  Ruch fizyczny zawsze wymaga osobnej zgody na konkretną próbę.
- Web/CSS/JS: wdrożenie i odświeżenie strony, bez restartu usług.
  Backend API: jawny restart tylko API. Inne usługi według zakresu zmiany.
  Nie restartuj robota, LCD, executora ruchu ani wszystkich usług dla panelu.
