# Lokalne kontrole jakości i CI

Używaj istniejącego środowiska Rider-Pi; urządzenie korzysta z Pythona 3.9,
a Ruff jest przypięty do 0.6.9. [Polityka środowisk](POLITYKA_SRODOWISK.md),
[Sonar i pokrycie](BRAMKA_JAKOSCI.md).

## Etapy i zakres

[.pre-commit-config.yaml](../.pre-commit-config.yaml) definiuje:

| Kontrola | Etap lokalny | CI |
| --- | --- | --- |
| Ruff check/fix i format | Commit i zwykłe etapy pre-commit | Quality Guard sprawdza repozytorium |
| Długość Python | Pre-push/manual | Quality Guard sprawdza zmienione pliki względem base/head |
| Usunięte importy | Domyślne etapy hooków, także commit; always_run | Ten sam osobny check wykonuje się jawnym skryptem |

Hook importów nie jest ograniczony do pre-push. Instalacja hooków i interpreter
są lokalnym ustawieniem; nie zakładaj obecności pre_commit w każdym venv.
Skrypty działają też bez tego wrappera. Nie omijaj hooków przy publikacji.

## Polecenia

Z katalogu repozytorium:

```sh
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python scripts/dev_check-file-length.py --base origin/main --head HEAD
.venv/bin/python scripts/dev_check-legacy-imports.py
```

Kontrola długości porównuje zapisane rewizje. Dla niezapisanych zmian podaj
jawnie ścieżki plików. Kod 0 obejmuje ostrzeżenia doradcze; kod 1 oznacza
twarde przekroczenie lub brak odczytu pliku/różnic.

| Fizyczne linie Python, z komentarzami i pustymi | Wynik |
| --- | --- |
| 0–600 | Zaliczenie |
| 601–800 | Ostrzeżenie; ocena spójności |
| Powyżej 800 | Błąd |

Ta sama reguła obejmuje zmienione testy i skrypty. Niezmienione historyczne
pliki nie blokują innego przyrostu; dawna etykieta allow-oversize nie daje
wyjątku. Wydzielaj spójne odpowiedzialności i zachowuj publiczne importy.
Długość pliku nie jest pomiarem CPU ani pamięci.

## Migracja importów

Pełna lista: [scripts/dev_check-legacy-imports.py](../scripts/dev_check-legacy-imports.py).
Skrypt blokuje usunięte ścieżki voice, face i launchera oraz dawne mixiny.
Przykłady:

| Usunięta ścieżka | Aktualny odpowiednik |
| --- | --- |
| apps.voice.capture / playback | apps.voice.audio.capture / playback |
| apps.voice.service_impl | apps.voice.svc_file |
| apps.voice.state / ptt_state | apps.voice.stream.state |
| apps.voice.transport / ws_transport / stream_transport | apps.voice.stream.transport |
| apps.voice.stream.service | apps.voice.stream.svc_streaming |
| apps.voice.main | apps.voice.cli |
| apps.ui.face.driver_ili9xx | drivers.lcd.driver_ili9xx |

Podejrzenie fałszywego trafienia wymaga odczytu kodu i uzasadnionej poprawki,
nie globalnego wyłączenia kontroli. Po zmianach importów wykonaj właściwe
testy izolowane.
