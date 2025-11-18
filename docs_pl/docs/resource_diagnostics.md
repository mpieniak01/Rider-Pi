# Diagnostyka zasobów sprzętowych

Opisujemy, jak karta „Diagnostyka zasobów” na `/web/control.html` inspekcjonuje
mikrofon, głośnik, kamerę i ekran LCD oraz jak każda operacja (stop/zakończ
zajęcie) trafia do jednego strażnika zasobów, żeby `/dev/video0` nigdy nie był
jednocześnie blokowany przez wiele usług.

## Narzędzie CLI

```
./scripts/resource_diag.py status camera
./scripts/resource_diag.py release camera --pid 1234
```

- `status` zwraca JSON z listą PID-ów i jednostek systemd trzymających dany zasób.
- `release` uruchamia skrypt czyszczący (dla kamery `scripts/sys_camera-free.sh`,
  dla audio `config/alsa/preflight.sh`, dla LCD `scripts/sys_lcd-control.py`) i
  wywołuje `scripts/vision-resource-guard.sh release`, żeby po zwolnieniu zasobu
  ponownie włączyć preview.

## API / panel sterowania

Endpoint `/api/resource/<mic|speaker|camera|lcd>` obsługuje:

- `GET` → taką samą inspekcję co CLI (`resource_diag.inspect` z `lsof` + `ProcessInfo`).
- `POST {"action":"stop"}` → zatrzymuje usługi blokujące zasób przez
  `resource_stop`, a przed kamerą zawsze uruchamia `resource_diag.guard_camera("claim")`,
  więc kamera jest „przydzielona” raz i nie ląduje w stanie „zajęty”.
- `POST {"action":"release"}` → wywołuje skrypty czyszczenia i guard z `release`,
  dzięki czemu po odblokowaniu preview wracają automatycznie.

Przyciski „Odśwież”, „Stop usługi” i „Zwolnij” korzystają z tego API, a dane
zostają odświeżone (`updateResourceRow` w `web/control.html:1645-1718`).

## Integracja ze strażnikiem zasobów

- `scripts/vision-resource-guard.sh` zatrzymuje `rider-cam-preview.service`,
  `rider-edge-preview.service` i `rider-ssd-preview.service` przed startem
  `rider-vision-offload.service` oraz wznawia je po zatrzymaniu offloadu.
- `scripts/sys_control.sh` uruchamia tego strażnika podczas wywołania `/svc`
  (np. przez panel) – najpierw `claim`, potem `stop`/`start`, następnie `release`.
- `resource_diag.guard_camera(action)` jest wspólną funkcją, z której korzystają
  API i systemowe skrypty, więc wszystkie ścieżki prowadzą do tego samego
  mechanizmu zarządzania kamerą.

## Procedura

1. Operator sprawdza kartę „Diagnostyka zasobów”.
2. „Stop usługi” zatrzymuje service’y przez `/svc` i jednocześnie wywołuje guard,
   który zwalnia `/dev/video0`.
3. „Zwolnij” uruchamia skrypt (np. `sys_camera-free.sh`) i guard w wersji `release`,
   który odtwarza preview.
4. Panel pokazuje nowe statusy i logi, więc nie trzeba ręcznie analizować `lsof`.

Dzięki temu wszystkie mechanizmy (CLI, `/svc`, UI) korzystają z jednej ścieżki
zarządzania zasobem kamery.
