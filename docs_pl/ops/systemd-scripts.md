# Skrypty systemd

## Katalog i własność zadania

Allowlisty jednostek pochodzą z `common/service_catalog.py`. Nie dodawaj drugiej
tablicy w skrypcie. Zobacz [zadania, usługi i zasoby](../ZADANIA_USLUGI_ZASOBY.md).

`sys_control.sh UNIT ACTION` obsługuje katalogowe jednostki i start/stop/restart/enable/disable.
Korzysta wyłącznie z systemowego managera, bez fallbacku do innego zakresu.
Brama odmawia startu usług ruchowych bez zgody właściwego właściciela. Sam start
bazowego executora tworzy DISARMED, bez uzbrojenia ani aktuacji.
Stop usług ruchowych wymaga potwierdzenia STOP; restart nie odtwarza zgody.
Usług opcjonalnych/dev/manual nie można tu włączyć do autostartu.
Zadaniami i wspólnymi konsumentami zarządza API; administracja przez shell jest jawna.

## systemd-sync.sh

Domyślne wywołanie wyświetla plan instalacji bez zmian. Katalog zawiera źródła
S6/S7/S10, ale stan instalacji i gotowości wymaga odczytu `/svc` i `/api/logic/features`.

```bash
./scripts/systemd-sync.sh
sudo ./scripts/systemd-sync.sh --apply
sudo ./scripts/systemd-sync.sh --apply --consolidate-boot
sudo ./scripts/systemd-sync.sh --rollback /etc/systemd/system/_rider_catalog_<znacznik>
```

`--apply` linkuje źródła, zapisuje kopie plików/linków i manifest, po czym wykonuje
daemon-reload. Nie uruchamia, nie zatrzymuje i nie restartuje procesu.
Konsolidacja rozruchu jest osobną decyzją: minimal/splash/LCD/Wi-Fi pozostają
właścicielami startu; redundantne enabled i opcjonalne zadania są wyłączane bez --now.
Nie zmienia default target, sieci, SSH, orientacji LCD, cudzych unitów ani drop-inów.
`--with-dev` zachowano dla zgodności; nie instaluje legacy. Rollback odmawia
nadpisania jednostki zmienionej po migracji.

Targety zadań są znacznikami. Uruchamiaj zadanie przez API, zamiast zakładać
gotowość po starcie targetu. Zastane usługi mają konsumenta base/external;
restart managera nie odtwarza intencji ruchu.

## Guard kamery i recovery

`vision-resource-guard.sh claim|release` tylko sprawdza warunki. Claim potwierdza
właściciela RAW i feed dla offloadu; release sprawdza zakończenie offloadu.
Nie zatrzymuje innego zadania ani nie przywraca podglądu po cichu.

`sys_camera-free.sh` wymaga dokładnych ścieżek V4L2, aktualnego PID, --force i
--operator-consent dla konkretnego recovery. Nie dotyka SPI/LCD i nie eskaluje
automatycznie do SIGKILL. Najpierw zakończ zadanie. HTTP recovery również
odmawia działania na używanym zasobie i chroni UART/LCD/właścicieli bazy.

## Weryfikacja

Automatyczne kontrole używają wyłącznie izolowanych atrap systemd/zasobów/BUS.
Aktywacja targetu ani próba napędów nie jest ogólnym smoke testem migracji.
Fizyczna próba aktuatorów wymaga osobnej zgody operatora dla dokładnego planu.
Podgląd aplikacji i migracja unitów są oddzielne; zachowaj API/SSH/Wi-Fi,
boot/splash, obrót LCD i ręczny Jupyter.
