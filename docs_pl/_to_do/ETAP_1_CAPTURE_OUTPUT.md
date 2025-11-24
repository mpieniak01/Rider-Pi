# Etap 1 – Konsolidacja warstwy capture/output

## Podsumowanie wykonanych zmian
- **Usługa `camera-capture@.service`** – nowy template systemd (instancje `@raw|edge|ssd`) uruchamia moduł `apps.camera.capture_service` z flockiem `/tmp/camera.lock` i wspólną logiką zapisu klatek (`snapshots/`).
- **Frame distributor** – dodatkowa usługa `frame-distributor.service` publikuje klatki w strumieniu ZMQ (`camera.frame.raw`). To umożliwia współdzielenie feedu między modułami wizji bez utrzymywania kilku preview.
- **Wyświetlacz LCD** – nowa usługa `lcd-renderer.service` (skrypt `scripts/lcd_renderer.py`) renderuje aktualny scenariusz i ewentualne ostrzeżenia na LCD; `rider-post-splash.service` przeniesiony do `systemd/legacy/`.
- **Warstwa audio** – wprowadzono targety `audio-input.target` (mikrofon/ASR) oraz `audio-output.target` (TTS/web) skupiające odpowiednio `rider-voice.service` i `rider-voice-web.service`. Dzięki temu App Logic może startować/monitorować audio jako logiczne moduły.
- **Aktualizacja narzędzi i dokumentacji** – `FeatureManager`, `/svc`, `scripts/sys_control.sh`, Makefile oraz przewodniki operacyjne używają nowych nazw (`camera-capture@*`, `frame-distributor`, `lcd-renderer`, `audio-*.target`). Legacy preview (`rider-cam-preview`, `rider-edge-preview`, `rider-ssd-preview`) i `rider-post-splash` znajdują się w `systemd/legacy/`.

## Wnioski
Warstwa capture ma jednolity punkt wejścia – niezależnie od tego, czy potrzebny jest surowy podgląd, wariant edge czy pipeline z SSD. App Logic oraz narzędzia ops przestały operować na rozproszonych nazwach, co eliminuje konflikty o kamerę i upraszcza kolejne etapy migracji.

## Następny krok
Kontynuować Etap 2 (warstwa processing): moduły `rider-tracker`, `rider-obstacle`, `rider-mapper` powinny pobierać klatki z `camera-capture` (np. przez `frame-distributor`) zamiast otwierać kamerę samodzielnie. Dzięki temu scenariusze S3–S9 będą mogły współdzielić feedy bez ręcznych blokad.***
