# Środowiska, zależności i testy

## Gdzie działa kod

Rider-Pi ma dwa różne środowiska. Fizyczny robot używa obrazu producenta,
Pythona 3.9 i pakietów potrzebnych uruchomionym usługom. WSL jest środowiskiem
programowania oraz automatycznych testów. Rider-PC i Venom mają własne stosy.

| Zakres | Raspberry Pi | WSL Rider-Pi |
| --- | --- | --- |
| Broker, BUS, wykonawca ruchu | `pyzmq` wymagany | `pyzmq` wymagany do testów transportu |
| API i panel | Flask/Werkzeug wymagane | wymagane do testów API |
| LCD i renderowanie | Pillow wymagany | Pillow, atrapa LCD |
| Kamera, vision, mapy | NumPy/OpenCV według wybranego profilu | NumPy/OpenCV headless do testów programowych |
| MediaPipe, modele ML, SDK providerów | tylko dla wybranego backendu; ciężkie obliczenia preferują PC | osobny profil testów, jawne mocki dla zewnętrznych SDK |
| Symulator 2D | poza podstawowym runtime; pygame może występować w starszym fallbacku splash | pygame wymagany do symulatora |
| pytest, coverage, Ruff, wtyczki testów | nie są wymaganiem wdrożenia | lokalne narzędzia WSL/CI |

Brak wymaganej zależności jest błędem przygotowania wskazanego środowiska.
Nie zmieniamy kontraktu aplikacji ani nie zastępujemy wymaganego pakietu atrapą
tylko po to, żeby pominąć jego instalację. Mock sprzętu lub zewnętrznego
providera jest jawną częścią zakresu testu. Brak opcjonalnego backendu oznacza
niedostępną funkcję, a nie gotową usługę. `pyzmq` należy do wymaganego runtime.

## Przygotowanie WSL

Używamy istniejącego `.venv` Rider-Pi także z jego worktree. Nie tworzymy
środowiska dla każdego PR. Nie instalujemy globalnie ani do środowiska Venom
lub Rider-PC. Korzystamy ze wspólnego cache pip; nie kopiujemy `site-packages`
między projektami. Oddzielne stosy mogą wymagać różnych wersji.

Deklaracja podstawowego zestawu to `config/agent/requirements-wsl.txt`.
Nie instaluj automatycznie całego `requirements-dev.txt`: zawiera także
opcjonalne ML i integracje providerów. Doinstalowanie deklarowanych braków
w WSL jest elementem przygotowania środowiska developerskiego.

```bash
# Z Rider-Pi, istniejący interpreter; bez sudo i bez --upgrade.
.venv/bin/python -m pip install -r config/agent/requirements-wsl.txt
.venv/bin/python -m pip check
.venv/bin/ruff --version
.venv/bin/python -m pytest --collect-only -q
```

`make test-env` sprawdza pakiety i Ruff. `make test` oraz `make lint` używają
tego samego istniejącego venv także z worktree; brak venv kończy się czytelnym
błędem. `TEST_PY=/ścieżka/.venv/bin/python` pozwala wskazać inne istniejące
środowisko Rider-Pi, a `TEST_ARGS='-q tests/wybrany_test.py'` zawęża sprawdzenie.

Z worktree użyj bezwzględnej ścieżki do tego samego interpretera i Ruff.
Nowszy Python WSL nie dowodzi zgodności z Pythonem 3.9. CI sprawdza wersję
docelową; wydanie utrwala wybrane wersje. Plik constraints musi zawierać
wyłącznie składnię pip i komentarze, nigdy instrukcje dla asystenta.

## Przygotowanie urządzenia

Nie przenosimy `.venv` WSL, pakietów testowych, cache ani modeli razem z kodem.
Przed uruchomieniem profilu sprawdzamy jego wymagania w interpreterze używanym
przez konkretny unit. Brak pakietu wykonawczego wymaga jednej zaplanowanej
zmiany runtime: zgodność z Pythonem 3.9 i obrazem producenta, wymagany profil,
koszt pamięci/dysku, procedura instalacji i powrotu. Nie wykonujemy doraźnych
instalacji przy każdym błędzie importu. Nie usuwamy istniejących pakietów
tylko dlatego, że nie należą do minimalnego profilu.

## Podział testów

- Automatyczne testy programowe, integracyjne i E2E działają w WSL/CI,
  z odizolowanym BUS, atrapami sprzętu i bez połączenia z robotem.
- Na Pi wykonujemy wybrany, krótki test funkcji sprzętowej oraz odczyt stanu,
  np. kamera, LCD, telemetria. Nie przenosimy tam pełnego pytest/coverage.
- Ruch, skręt, wysokość, balans, akcje i autonomia mogąca poruszyć robotem
  wymagają osobnej zgody operatora na konkretną ręczną próbę. Nigdy nie są
  uruchamiane automatycznie przez test, diagnostykę, wdrożenie lub panel.

Zgoda na instalację pakietów WSL, kamerę lub wdrożenie nie uzbraja ruchu.
Zasady ruchu: [bezpieczeństwo](apps/safety.md). Dwie ścieżki kodu:
[podgląd lokalnego commita i wydanie przez GH](WDROZENIE.md).
