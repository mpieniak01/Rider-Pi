# Diagnostyka zasobów sprzętowych

Ten moduł pozwala szybko ustalić, czy mikrofon, głośnik lub kamera są
zajęte i umożliwia selektywne zwolnienie blokujących procesów. Całość
oparta jest na prostych narzędziach (`lsof`, `fuser`) oraz istniejących
skryptach (`config/alsa/preflight.sh`, `scripts/sys_camera-free.sh`).

## Narzędzie CLI

```
scripts/resource_diag.py status mic
scripts/resource_diag.py release camera --pid 1234
```

- `status` – zwraca JSON ze stanem zasobu (lista PID-ów, nazwy usług
  systemd, ścieżki urządzeń).
- `release` – uruchamia odpowiedni skrypt czyszczący. Dla audio
  wykorzystywany jest `config/alsa/preflight.sh --force`, dla kamery
  `scripts/sys_camera-free.sh`. Opcjonalny `--pid` pozwala zawęzić
  operację do konkretnych procesów.

## API /panel sterowania

Endpoint `/api/resource/<mic|speaker|camera>` obsługuje:

- `GET` – status jak wyżej.
- `POST {"action":"stop"}` – zatrzymuje usługi systemd, które
  aktualnie blokują zasób (np. `rider-voice.service`).
- `POST {"action":"release"}` – wymusza zwolnienie urządzenia przez
  skrypt (również przy procesach spoza systemd).

Panel `web/control.html` prezentuje dane oraz udostępnia trzy przyciski
(odświeżenie, stop usługi, zwolnij zasób) dla mikrofonu, głośnika i
kamery.

## Integracja skryptów

- `config/alsa/preflight.sh` przyjmuje nową opcję `--limit-pid`, dzięki
  czemu można zabić tylko wskazane procesy audio.
- `scripts/sys_camera-free.sh` zabija wyłącznie procesy mające otwarte
  `/dev/video*`/`/dev/spidev*`, opcjonalnie ograniczone do PID-ów.
- `scripts/sys_control.sh` dopuszcza obsługę `rider-voice.service` oraz
  `rider-voice-web.service`, aby panel mógł zatrzymać usługę blokującą
  mikrofon.

## Typowa procedura

1. Operator sprawdza kartę „Diagnostyka zasobów” w panelu.
2. Jeśli widzi usługę systemd, klika „Stop usługi”, co woła `/svc`.
3. Jeżeli zasób nadal zajęty (skrypt testowy), naciska „Zwolnij”, co
   wywołuje odpowiedni skrypt czyszczący.
4. Informacje trafiają też do logu zdarzeń w panelu.

Całość pozostaje prosta (shell + istniejące skrypty), ale eliminuje
zgadywanie „kto trzyma urządzenie”.
