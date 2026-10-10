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

## Konfiguracja i notatki lokalne

Korzystamy ze zwykłych lokalnych plików env. `.env`, prywatne `.env.*`,
`evn.ssh.local` i `config/local/` zawierają ustawienia developera i sekrety.
Nie trafiają do Git, załączników PR, logów ani paczek wdrożeniowych.
Publiczne `.env.example` i `.env.*.example` zawierają wyłącznie placeholdery.
Zachowuj istniejący `.env`; nie nadpisuj go szablonem.

Prywatny plik SSH powinien mieć uprawnienia `600`. Hasło wpisuj w lokalnym
edytorze, bez przekazywania go w argumentach poleceń lub dokumentacji.
Zwykły SSH nie wczytuje automatycznie `evn.ssh.local`.

Plany zadań zapisuj w ignorowanym `_to_do/`, a ukończone notatki i audyty
sesji w `_done/` lub `done/`. Utrzymywane instrukcje i potrzebne obrazy
publikuj zgodnie z [polityką dokumentacji](POLITYKA_DOKUMENTACJI.md).
Przed commitem sprawdź `git diff --cached --name-status` oraz
`git diff --cached --check`. Nie dodawaj plików lokalnych przez `git add -f`.

## Środowisko Pi i kontrole

Runtime obrazu producenta korzysta z Pythona 3.9 na Raspberry Pi OS / Debian.
Nowszy interpreter WSL nie potwierdza zgodności z tym środowiskiem.
Przeczytaj [instrukcje agenta](../AGENT.md) i [ustalenia pracy](WORKING-AGREEMENTS.md).
Korzystaj z istniejących zależności; w zwykłym zadaniu aplikacyjnym
nie instaluj pakietów online na Pi.

Użyj Ruff 0.6.9 z dostępnego środowiska i odpowiednich testów bezpośrednich:

```bash
ruff check .
ruff format --check .
.venv/bin/python -m pytest tests/test_systemd_services.py tests/config/ -q
.venv/bin/python -m pytest tests/test_version_api.py -q
```

Testy wersji wymagają zależności API. Sprzęt, audio, vision i przeglądarka
mają osobne wymagania; zakres dobieraj do zmiany. Rewizję, polecenie i wynik
zapisuj w lokalnej notatce zadania. Mocki nie potwierdzają pracy silników,
sensorów ani fizycznego śledzenia.

[Panel Pi](ui/panel-diagnostyka.md) korzysta z portu `8080`.
Prace aplikacyjne zachowują rozruch, sieć i SSH.
Przed aktualizacją urządzenia przeczytaj [wdrożenie i odtwarzanie](WDROZENIE.md).
