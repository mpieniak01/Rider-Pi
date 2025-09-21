# Rider Voice Stack

Pełny port aplikacji głosowej został przeniesiony do `apps/voice/`. Nowa
architektura dzieli odpowiedzialności na niewielkie moduły (capture,
VAD, KWS, ASR, NLU, Chat, TTS, playback, service, CLI, Web API), co
upraszcza debugowanie i utrzymanie. Poniżej znajdziesz opis instalacji,
konfiguracji oraz sposobów uruchamiania.

## Wymagania systemowe

* Raspberry Pi z Debian/Bookworm, Python 3.11.
* Dostęp do urządzeń audio ALSA lub PulseAudio (`arecord`, `paplay`,
  `parec`).
* Opcjonalne modele offline:
  * **Vosk** – katalog modelu ustaw w `vosk_model_dir` (domyślnie
    `models/vosk`).
  * **Piper** – model `.onnx` i opcjonalny plik `.json` (`piper_model`,
    `piper_config`).
* Klucz OpenAI (`OPENAI_API_KEY`) jeśli korzystasz z chmury dla ASR/TTS
  lub chatu.

## Konfiguracja

### Pliki i ENV

1. Skopiuj `.env.voice.sample` do `.env.voice` (albo innej lokalizacji) i
   uzupełnij wartości, np.

   ```bash
   cp .env.voice.sample ~/.config/rider/voice.env
   export OPENAI_API_KEY=sk-...
   export VOICE_ASR_BACKEND=vosk
   export VOICE_TTS_BACKEND=piper
   export VOICE_TTS_VOICE=pl
   export VOICE_CAPTURE_BACKEND=pulse
   ```

2. Skopiuj `config/voice.toml.sample` do `config/voice.toml` i
   dostosuj backendy, urządzenia audio, ścieżki do modeli offline.

3. Zmiennych środowiskowych możesz używać bezpośrednio albo poprzez
   plik `systemd/rider-voice.env.sample` (przykładowy plik dla
   `/etc/rider/voice.env`).

### Kluczowe ustawienia

* `VOICE_ASR_BACKEND` – `openai`, `vosk`, `faster-whisper`, `whispercpp`
  (obecnie zaimplementowano `openai` i `vosk`).
* `VOICE_TTS_BACKEND` – `openai` lub `piper`.
* `VOICE_CAPTURE_BACKEND` – `pulse`, `alsa` lub `command` (wtedy
  `VOICE_CAPTURE_COMMAND`).
* `VOICE_TTS_VOICE` / `VOICE_TTS_MODEL` – zależnie od backendu.
* `VOICE_LOG_LEVEL` – poziom logów (`DEBUG`, `INFO`, `WARNING`...).

## CLI (`apps.voice.cli`)

CLI oferuje subkomendy z bogatym zestawem parametrów. Każda subkomenda
akceptuje dodatkowe pary `--sekcja key=value` (np.
`--asr backend=vosk model=...`).

```bash
python3 -m apps.voice.cli listen --hotword off
python3 -m apps.voice.cli ptt --asr backend=vosk --tts backend=piper
python3 -m apps.voice.cli once --lang pl
python3 -m apps.voice.cli asr --file samples/test.wav
python3 -m apps.voice.cli tts --text "Cześć, tu Rider!" --play
python3 -m apps.voice.cli diag
```

Najważniejsze przełączniki:

* `--hotword on|off|ptt` – sterowanie KWS; `ptt` wymaga ENTER.
* `--asr key=value` – konfiguracja backendu ASR (np. `backend=vosk`,
  `language=pl`).
* `--tts key=value` – konfiguracja TTS (`backend=piper`, `voice=pl`).
* `--vad key=value` – zmiana parametrów VAD (`frame_ms=20`,
  `tail_ms=300`).
* `--save-audio on|off path=/ścieżka` – zapisz nagrania wejściowe.
* `--log-level` – szybka zmiana poziomu logowania.

### Makefile

Najczęstsze wywołania opakowano w cele Makefile:

```bash
make voice-run                    # równoważne listen
make voice-ptt                    # push-to-talk
make voice-once                   # pojedynczy cykl
make voice-asr-file FILE=...      # test ASR na pliku
make voice-tts TEXT="Hello"      # TTS z odtwarzaniem
make voice-web VOICE_BIND=0.0.0.0:8092
```

Zmienna `VOICE_ARGS` pozwala przekazać dodatkowe parametry (np.
`VOICE_ARGS="--asr backend=vosk"`).

## Web API (`apps.voice.web`)

Serwer HTTP (Flask) udostępnia trzy endpointy:

* `GET /healthz` – status i backendy.
* `POST /tts` – JSON `{text, backend, voice, model}` → audio (`wav` lub
  `mpeg`).
* `POST /asr` – `multipart/form-data` z `file=@...` oraz polami `backend`,
  `lang`.
* `POST /capture` – JSON z konfiguracją (`asr`, `tts`, `hotword`...) –
  zwraca audio odpowiedzi i nagłówki `X-Transcript`, `X-Intent`,
  `X-Latency`.

Uruchomienie:

```bash
python3 -m apps.voice.web --bind 127.0.0.1:8092
curl -s http://127.0.0.1:8092/healthz | jq
```

### Przykłady

```bash
# TTS → WAV
curl -s -X POST http://127.0.0.1:8092/tts \
  -H 'content-type: application/json' \
  -d '{"text":"Cześć, tu Rider-Pi!","backend":"piper","voice":"pl"}' \
  -o reply.wav

# ASR na pliku
curl -s -X POST http://127.0.0.1:8092/asr \
  -F file=@samples/test.wav \
  -F backend=vosk \
  -F lang=pl

# Jednorazowy cykl capture→ASR→chat/TTS
curl -s -X POST http://127.0.0.1:8092/capture \
  -H 'content-type: application/json' \
  -d '{"asr":{"backend":"openai","lang":"pl"}, "tts":{"backend":"openai"}}' \
  -o reply.wav
```

## Instalacja jako usługa (`systemd`)

Dostarczono dwa unity: `rider-voice.service` (CLI listen) oraz
opcjonalnie `rider-voice-web.service` (HTTP API). Plik
`systemd/rider-voice.env.sample` przenieś do `/etc/rider/voice.env`.

```bash
sudo cp systemd/rider-voice.service /etc/systemd/system/
sudo cp systemd/rider-voice-web.service /etc/systemd/system/
sudo mkdir -p /etc/rider
sudo cp systemd/rider-voice.env.sample /etc/rider/voice.env
sudo systemctl daemon-reload
sudo systemctl enable --now rider-voice.service
sudo systemctl enable --now rider-voice-web.service
journalctl -u rider-voice.service -f
```

Integracja z repo-first `systemd_sync.sh` działa automatycznie – nowe
unity są na allow-liście.

## Logowanie

Moduł `apps.voice.logging` ustawia JSON logi na stdout. Poziom logów
możesz ustawić w `VOICE_LOG_LEVEL` lub przez `--log-level` w CLI.
Przykładowy wpis:

```json
{"ts":"2025-03-21T12:00:00.123Z","level":"INFO","name":"voice.service","msg":"service.cycle.done","extra":{"data":{"latency":1.42,"intent":"chat"}}}
```

## Diagnostyka

`python3 -m apps.voice.cli diag` wypisuje konfigurację, listę urządzeń
`arecord -l` / `pactl` (jeśli dostępne) oraz odtwarza sygnał „ding”.

Jeśli `webrtcvad`, `libnyumaya` lub `piper` nie są zainstalowane, kod
loguje ostrzeżenie, ale dalej umożliwia pracę w trybie push-to-talk lub
z backendami chmurowymi.

## Notatki o modelach offline

* **Vosk** – użyj skryptu `ops/fetch_models.sh` (gdy będzie dostępny) aby
  pobrać lekkie modele `vosk-model-small-pl-0.22` lub podobne. Wskazówkę
  zapisz w `config/voice.toml` (`vosk_model_dir`).
* **Piper** – modele `.onnx` są duże, nie commitujemy ich. W dokumentacji
  `VOICE.md` linkujemy do oficjalnych buildów (`https://github.com/rhasspy/piper/releases`).
* **Nyumaya/Porcupine** – moduł KWS potrafi korzystać z bibliotek jeśli
  znajdują się w systemie (ścieżki konfigurowane w `hotword.model` i
  `hotword.library`).

## Różnice względem `_apps/voice`

* Brak bezpośrednich importów z `_apps` – nowy kod jest samodzielny.
* Konfiguracja TOML + ENV + CLI zamiast globalnych zmiennych.
* JSON logi oraz modularna architektura (łatwiejsze testy i ewentualny
  fallback backendów).
* Opcjonalne API HTTP oraz definicje `systemd` z repozytorium.

W razie problemów skorzystaj z logów (`journalctl -u rider-voice`) lub
odpal CLI w trybie debug (`--log-level DEBUG`).
