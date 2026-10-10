# Polityka konfiguracji Rider-Pi

`config/` jest źródłem konfiguracji. Zależności i podział urządzenie/WSL opisuje
[polityka środowisk](../POLITYKA_SRODOWISK.md). Rider-Pi jest lekkim robotem:
na urządzeniu utrzymujemy pakiety wykonawcze potrzebne do używanego profilu.

## Źródło i nadpisania

`apps/voice/config.py` wczytuje wskazany TOML, a `load(None)` używa repozytoryjnego
`config/voice.toml`; potem nakłada jawnie przekazane overrides. CLI może wskazać
plik i nałożyć własne argumenty/ustawienia procesu. Nie zakładaj, że samo
`load(None)` uwzględni `VOICE_CONFIG`. Używaj istniejących plików w `config/`
i lokalnych nadpisań w `config/local/`.
Nie kopiuj konfiguracji sprzętu Pi do współdzielonego Ubuntu w WSL.

| Obszar | Lokalizacja |
| --- | --- |
| Głos | `config/voice*.toml` |
| Twarz i LCD | `config/face.toml` |
| ALSA WM8960 | `config/alsa/asoundrc.wm8960` i `config/alsa/wm8960-apply.sh` |
| Sekrety i lokalne nadpisania | `config/local/`; pliki ignorowane przez Git |

Orientacja zamontowanego wyświetlacza jest utrwalona: `FACE_LCD_ROTATE=270`.
Urządzenie ma ekran zamontowany bokiem; nie zmieniaj obrotu podczas zwykłej poprawki.

## Sekrety i Git

Sekretów nie zapisujemy w repozytorium, historii komend, opisie PR ani logu.
Używaj zmiennych środowiskowych lub pliku w ignorowanym `config/local/` z prawami
`600`. Istniejące poświadczenia SSH w `env.ssh.local` pozostają lokalne;
przed zmianą sprawdź rzeczywistą nazwę pliku i regułę `.gitignore`.
Nie pokazuj wartości sekretu do diagnostyki. Sprawdzaj jego obecność lub nazwę.

W TOML wskazuj `auth = "env:OPENAI_API_KEY"` albo `auth = "file:config/local/openai.key"`.
Nie przywracaj przestarzałego schematu `bashenv:`. Skrypty mają czytać konfigurację,
respektować istniejące ENV i nie dopisywać sekretów do profili użytkownika.

## WSL i urządzenie

Pełne testy oprogramowania oraz narzędzia deweloperskie są w istniejącym lokalnym
`Rider-Pi/.venv`. Rider-Pc i Venom zachowują osobne stosy; nie instaluj globalnie,
nie twórz następnego venv dla kolejnego worktree i nie instaluj pakietu po każdym
komunikacie o imporcie. Najpierw ustal aktywny profil, interpreter i wymagania.

Jawnie zatwierdzone przygotowanie WSL korzysta z tego samego środowiska:

```bash
/home/pi/Rider-Pi/.venv/bin/python -m pip install -r config/agent/requirements-wsl.txt
/home/pi/Rider-Pi/.venv/bin/python -m pip check
```

To instrukcja dla WSL, nie dla fizycznego Pi. Na Pi nie instaluj
`requirements-dev.txt` ani manifestu WSL. Biblioteki ML, testy i narzędzia nie są
automatyczną zależnością urządzenia. Brak wymaganej zależności aktywnego profilu ma
być jawnym `unavailable`/błędem startu; start usługi nie uruchamia instalacji ani
pobierania modelu. Zmiana runtime Pi wymaga osobnego planu zgodności i wycofania.

## Sprzęt i diagnostyka

Odczyt stanu oddzielamy od prób otwierających urządzenie. Domyślna diagnostyka:
API safety/telemetria, `systemctl show`, `journalctl` i właściciele zasobów.
Nie tworzymy SDK dla odczytu UART; wykonawca ruchu jest jego jedynym właścicielem.
`scripts/diag_sensors.py` i `scripts/sys_xgo-init.py` czytają status wykonawcy;
nie inicjalizują napędów.

ALSA preflight z otwarciem capture/playback jest próbą sprzętową, wymagającą
przygotowanego profilu i decyzji operatora. `--force` w starym preflight nie jest
zwykłą procedurą diagnostyczną ani krokiem automatycznego startu.
Po PR03 używaj diagnostyki zasobów i najpierw zatrzymaj zadanie właściciela:

```bash
python3 scripts/resource_diag.py status mic
python3 scripts/resource_diag.py status camera
python3 scripts/resource_diag.py status uart
```

Ręczne recovery w kontrakcie PR03 wymaga `--force --operator-consent --pid <PID>`
dla aktualnie zaobserwowanego właściciela. Zasoby dzierżawione przez zadanie,
UART, LCD i baza są chronione; brak odczytu oznacza `unknown`, nie `free`.
Nie ma domyślnego zabijania, SIGKILL ani automatycznego wznawiania usług.
[Diagnostyka zasobów](../resource_diagnostics.md) podaje dokładny kontrakt.

## Walidacja i ścieżki wdrożenia

Format, importy i testy oprogramowania sprawdzaj w WSL, z atrapami sprzętu:

```bash
/home/pi/Rider-Pi/.venv/bin/ruff check apps/ common/ services/ scripts/ tests/
/home/pi/Rider-Pi/.venv/bin/ruff format --check apps/ common/ services/ scripts/ tests/
RIDER_PI_CI=1 MOCK_HW=1 RUN_DEVICE_TESTS=0 /home/pi/Rider-Pi/.venv/bin/python -m pytest
git diff --check
```

Polecenie pytest dotyczy WSL i izolowanego zestawu oprogramowania. Testy ruchu są
wyłącznie osobnymi próbami za zgodą obecnego operatora, nigdy częścią pytest,
CI ani ogólnego skryptu diagnostycznego. Próby kamery/audio również nie są
automatycznie uruchamiane podczas diagnozy. Robot w trybie dev jest zasilany
kablem; ruch wymaga przygotowanej przestrzeni, przewodu i konkretnego planu.

Krótka ścieżka DEV służy sprawdzeniu zmiany na sprzęcie przed publikacją GH,
zgodnie z dokumentem wdrożenia i zgodą dla wymaganych prób fizycznych.
Ścieżka wydania: lokalny Git → zdalna gałąź GH → PR/recenzja → merge →
pobranie na urządzeniu. Sprawdzamy konkretną wersję, lokalne nadpisania i możliwość
wycofania. Zmiana kodu nie oznacza zgody na ruch ani zmianę autostartu.

[Skrypty operacyjne](../ops/utility-scripts.md) ·
[Zarządzanie usługami](../ops/systemd-scripts.md) ·
[Bezpieczeństwo](../apps/safety.md)
