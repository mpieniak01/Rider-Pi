# Skrypty pomocnicze i diagnostyka

Obowiązuje [polityka środowisk](../POLITYKA_SRODOWISK.md) oraz
[polityka konfiguracji](../config/POLICY.md). Odczyt, próba sprzętu i ruch mają
osobne procedury. Skrypt diagnostyczny nie jest zgodą na ruch.

## Testy oprogramowania w WSL

`scripts/diag_test-suite.sh` uruchamia wybrane izolowane testy kontraktu ruchu,
HTTP i piaskownicy. Nie otwiera kamery, audio, LCD ani UART. Użyj istniejącego venv:

```bash
PYTHON=/home/pi/Rider-Pi/.venv/bin/python scripts/diag_test-suite.sh
RIDER_PI_CI=1 MOCK_HW=1 RUN_DEVICE_TESTS=0 /home/pi/Rider-Pi/.venv/bin/python -m pytest
```

Pełny pytest uruchamiaj w WSL. Nie instaluj pełnego zestawu testowego na lekkim Pi
i nie traktuj starych nazw `diag_*` jako dowodu, że skrypt jest tylko odczytowy.
`diag_tests-audit.sh` analizuje zestaw testów; benchmark detekcji jest osobnym
zadaniem dla wybranego backendu i wejścia. Próba na rzeczywistej kamerze wymaga
decyzji operatora i przygotowanego profilu.

## Odczyt wykonawcy i usług

`diag_motion-status.py`, `diag_sensors.py` i `sys_xgo-init.py` korzystają ze statusu
jednego wykonawcy. Nie tworzą drugiej instancji SDK, nie resetują robota i nie
udzielają zgody na napędy. Nazwa `sys_xgo-init` zachowuje kompatybilność CLI;
nie oznacza już fizycznej inicjalizacji.

```bash
python3 scripts/diag_motion-status.py
systemctl show motion-executor.service -p LoadState -p ActiveState -p SubState -p UnitFileState -p MainPID
journalctl -u motion-executor.service --since "5 min ago" -n 50 --no-pager
curl --fail http://127.0.0.1:8080/api/control/state
```

Aktywny proces i ACK transportu nie dowodzą zatrzymania napędów. Safety status
pokazuje zgodę, generację, potwierdzenie STOP i dostępność poszczególnych aktuatorów.
Nieopisane możliwości sprzętu pozostają niedostępne do czasu osobnej próby ręcznej.

`diag_xgo-bootloader.py` jest historycznie błędnie nazwanym skryptem LCD: inicjalizuje
wyświetlacz i zmienia podświetlenie. Nie jest odczytem wersji firmware ani UART;
nie uruchamiaj go w automatycznej diagnostyce. Ekran ma zachować obrót
`FACE_LCD_ROTATE=270` i aktualną sekwencję startową.

## Ruch i E-STOP

`demo_trajectory.py` ma wyłączoną dawną automatyczną sekwencję ruchu.
`manual_motion-probe.py` wykonuje pojedynczą próbę przez API, po przygotowaniu
konkretnego planu, aktualnej zgodzie i w obecności operatora. Nigdy nie wywołujemy
go z pytest, CI, wdrożenia ani ogólnego skryptu testów. Robot dev ma kabel zasilający;
operator musi przygotować przewód i przestrzeń.

`sys_emergency-stop.py` używa kanonicznego API safety:

```bash
python3 scripts/sys_emergency-stop.py status
python3 scripts/sys_emergency-stop.py stop
python3 scripts/sys_emergency-stop.py on
```

`stop` unieważnia zgodę i żąda STOP; `on` zatrzaskuje E-STOP. `off` wymaga osobnego
planu i interaktywnej zgody, a jego wynik pozostaje DISARMED. Nie ma bezpośredniego
otwierania UART ani automatycznego ponownego uzbrojenia. Oceniaj `confirmed` i ACK
wykonawcy, nie tylko kod HTTP czy kod wyjścia CLI.
[Kontrakt bezpieczeństwa](../apps/safety.md) opisuje szczegóły.

## Usługi, zasoby i migracja PR03

Do diagnostyki wystarcza odczyt katalogu, stanu jednostek i właścicieli zasobów:

```bash
curl --fail http://127.0.0.1:8080/api/logic/catalog
curl --fail http://127.0.0.1:8080/svc
python3 scripts/resource_diag.py status camera
python3 scripts/resource_diag.py status uart
scripts/systemd-sync.sh
```

Katalog i domyślny plan `systemd-sync` należą do PR03; starsza wersja może jeszcze
ich nie udostępniać. Przed użyciem starego `systemd-sync` sprawdź wersję skryptu,
bo stary wariant zmieniał system. Instalacja planu PR03 wymaga jawnego `--apply`.
Zmiana autostartu jest osobną operacją `--consolidate-boot`; żaden przykład odczytu
nie oznacza zatwierdzenia tych zmian.

Uruchamiaj tylko wybrane zadanie przez panel/API katalogu, po sprawdzeniu
zależności i wymaganych urządzeń. Stan zadania `requested/starting/ready` jest
odrębny od `ActiveState` usługi. Zakończenie zadania ruchowego wymaga potwierdzonego
STOP przed zwolnieniem zasobów. Recovery jest ręczne, dla wskazanych właścicieli,
z jawnie opisanymi skutkami. UART i SPI/LCD nie należą do zwalniania kamery.

`util_export-env.sh` i `util_load-config.sh` służą do lokalnej konfiguracji bieżącego
procesu; nie dodawaj globalnej instalacji pakietów ani zmian profilu Ubuntu.
`sys_cleanup.sh` zmienia pliki: przeczytaj jego zakres przed osobnym użyciem;
nie jest rutynową diagnostyką lub krokiem każdego wdrożenia.

[Diagnostyka zasobów](../resource_diagnostics.md) ·
[Zarządzanie systemd](systemd-scripts.md) ·
[Moduły aplikacyjne](../apps/)
