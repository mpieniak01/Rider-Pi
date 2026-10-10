# Diagnostyka zasobów sprzętowych

Własność, stany i migrację instalacji opisuje [kontrakt zadań i zasobów](ZADANIA_USLUGI_ZASOBY.md).

## Odczyt

`GET /api/resource/<camera|mic|speaker|lcd|uart>` pokazuje dokładne ścieżki
urządzeń, obserwowane PID, jednostki systemd, konsumentów i `observed_at`.
Nie inicjalizuje SDK robota ani nie zmienia procesów.

| Stan | Znaczenie | free |
| --- | --- | --- |
| free | Poprawny odczyt własności bez właściciela | true |
| busy | Co najmniej jeden obserwowany właściciel | false |
| unavailable | Brak pasującej ścieżki urządzenia | null |
| unknown | Nie udało się wiarygodnie odczytać własności | null |

Kamera obejmuje V4L2 `/dev/videoN`; SPI i framebuffer należą do LCD.
UART jest odrębnym zasobem, zarezerwowanym dla jednego executora ruchu.
Sensor-reader korzysta z telemetrii BUS.

CLI wykonuje ten sam odczyt:

```bash
./scripts/resource_diag.py status camera
./scripts/resource_diag.py status uart
```

## Stop i ręczne recovery

Najpierw zakończ zadanie przez API zadań. Współdzielone jednostki działają, dopóki
nie zakończy się ostatni konsument. Zadanie ruchowe wymaga potwierdzonego STOP
przed zwalnianiem usług. Administracja odmawia zatrzymania jednostki używanej przez zadanie.

`POST {"action":"stop"}` na endpoint zasobu zatrzymuje tylko jednostki katalogu,
których metadane zawierają dany zasób. Nieznany właściciel lub błąd odczytu oznacza
odmowę. Sukces wymaga zakończenia wszystkich żądanych kroków.

Release jest osobnym, świadomie sprawdzonym recovery. Wymaga `force: true`,
`operator_consent: true` i dokładnych obecnie obserwowanych PID. Odpowiedź pokazuje
właścicieli, konsumentów i skutki. Aktywni konsumenci zadania blokują release.
Polecenie wysyła SIGTERM wyłącznie wybranym właścicielom. Nie przechodzi do
SIGKILL ani nie uruchamia automatycznie innej usługi. UART, LCD i baza są chronione.

```bash
# Wyłącznie po sprawdzeniu właścicieli i zakończeniu ich zadań:
./scripts/resource_diag.py release camera --pid 1234 --force --operator-consent
```

## Feed kamery i blokada

RAW capture jest właścicielem kamery; frame-distributor dostarcza dane konsumentom,
także offloadowi PC. Offload nie może awaryjnie otworzyć drugiej fizycznej kamery.
`vision-resource-guard.sh claim|release` sprawdza te warunki odczytowo.
Nie zabija innego właściciela ani nie wznawia preview. Konflikt RAW/EDGE/SSD oznacza
odmowę; wybierz jedno narzędzie przez API zadań.

Automatyczne sprawdzenia korzystają z atrap własności i procesów. Fizyczna próba
ruchu wymaga zgody operatora dla konkretnego planu. Podgląd kamery nie daje takiej zgody.
