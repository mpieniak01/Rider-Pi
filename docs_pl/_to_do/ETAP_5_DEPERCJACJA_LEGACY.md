# Etap 5 – Deprecjacja legacy usług

## Podsumowanie wykonanych prac
- **Katalog `systemd/legacy`** – utworzono dedykowane miejsce na przestarzałe jednostki (`rider-face.service`, `rider-edge-preview.service`, `rider-ssd-preview.service`). Dzięki temu repozytorium rozróżnia, które usługi są wspierane produkcyjnie, a które pozostają tylko dla trybów DEV/S11.
- **Warstwa ruchu legacy** – `rider-motion-bridge.service` została przeniesiona do `systemd/legacy/` po wdrożeniu `motion-executor.service` + `sensor-reader.service`. Legacy pozostaje tylko na potrzeby ewentualnego rollbacku.
- **Aktualizacja systemd-sync** – lista `ALLOW_UNITS` została oczyszczona z legacy preview, więc skrypt `scripts/systemd-sync.sh` nie będzie ich już linkował ani uruchamiał automatycznie. Dokumentacja operacyjna (`docs*/ops/systemd-scripts.md`) zawiera adnotację o nowym katalogu.
- **Instrukcja migracji** – dodano `docs_pl/UPGRADE_SCENARIOS.md`, opisujący kroki operatora: zatrzymanie legacy, wywołanie sync, uruchamianie scenariuszy przez App Logic (`scripts/robot_ctl.py` lub API). Dokument podkreśla, że legacy można nadal uruchomić ręcznie z katalogu `systemd/legacy/`.
- **Ujednolicone odwołania** – README i dokumenty modułu Face wskazują na nowe położenie jednostek legacy, co zapobiega błędnym instrukcjom w przyszłych wdrożeniach.

## Wnioski
Etap 5 został zamknięty – repozytorium jasno rozdziela wspierane usługi od jednostek legacy, a operator otrzymał instrukcję migracji. Dzięki temu kolejne wdrożenia targetów scenariuszy (Etap 3) i nowej warstwy capture/processing (Etapy 1–2) mogą być prowadzone bez ryzyka, że stare preview wrócą do produkcji.

## Następny krok
- **Kontynuacja Etapu 2 (processing)** – po wdrożeniu `camera-capture` należy dopracować warstwę przetwarzania (frame-distributor, wspólne feedy dla tracker/obstacle/slam), aby legacy preview nie były już potrzebne nawet w scenariuszach rozwojowych.
