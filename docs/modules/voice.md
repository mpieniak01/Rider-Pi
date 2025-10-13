# Rider Voice Stack (2025‑09)

Pełny port aplikacji głosowej znajduje się w `apps/voice/`. Architektura jest modułowa (capture → VAD → KWS → ASR → NLU → Chat → TTS → playback), co upraszcza utrzymanie i testy. **Wspiera teraz również tryb strumieniowy (realtime) z WebSocket duplex** dla natychmiastowych interakcji głosowych.

---

## Tryby pracy

**Rider Voice** obsługuje dwa główne tryby:

1. **Tryb plikowy (file-based)** - tradycyjny pipeline: capture → plik → ASR → Chat → TTS → playback
2. **Tryb strumieniowy (realtime)** - WebSocket duplex: audio chunks → partial ASR → streaming Chat/TTS z barge-in

Wybór trybu odbywa się automatycznie na podstawie konfiguracji `transport` w sekcjach `[asr]`, `[chat]`, `[tts]`.

---

## Architektura modułu

### Refaktoryzacja (2024 Q4)

Moduł `apps/voice` przeszedł kompleksową refaktoryzację w ramach PR#1–PR#5 w celu:
- Eliminacji duplikatów kodu (usunięto ~1000 linii zduplikowanego kodu)
- Rozdzielenia logiki plikowej i strumieniowej
- Uproszczenia testowania i utrzymania
- Wprowadzenia jasnego API i punktów integracji

### Komponenty po refaktoryzacji

#### Wybór trybu i orkiestracja
- **`svc_core.py`** — centralna logika wyboru trybu (`run_listen`, `run_once`, `run_ptt`)
  - Analizuje konfigurację `transport` w `[asr]`, `[chat]`, `[tts]`
  - Deleguje do odpowiedniego serwisu (file lub stream)

#### Tryb plikowy (file)
- **`svc_file.py`** — `VoiceService` (klasa główna), `run_listen_file()`, `run_once_file()`
- **Przepływ**: Capture → WAV → ASR (pełna transkrypcja) → Chat → TTS → Playback

#### Tryb strumieniowy (realtime)
- **`svc_stream_runner.py`** — wrappery CLI dla trybu stream
  - `run_listen_stream()`, `run_ptt_stream()`, `run_once_stream()`
  - Delegują do `stream/svc_streaming.StreamingVoiceService`

**Pakiet `apps/voice/stream/`:**
- **`svc_streaming.py`** — `StreamingVoiceService` (główna klasa, 700+ linii)
  - Integruje mixiny: `StreamHandlersMixin`, `StreamPlayoutMixin`
  - Lifecycle: connect → session → audio duplex → cleanup
- **`transport.py`** — `WebSocketTransport`, `ReconnectingTransport`
  - Ping/heartbeat, exponential backoff retry (max 6 prób)
  - Obsługa `websockets` (async) i `websocket-client` (sync fallback)
- **`state.py`** — `PTTStateMachine` (Push-To-Talk state machine)
  - Stany: IDLE, LISTENING, SPEAKING, PROCESSING
  - Eventy: PTT_START, PTT_STOP, ASR_PARTIAL, TTS_START, TTS_END
- **`handlers.py`** — `StreamHandlersMixin`
  - Obsługa wiadomości WebSocket (session, ASR, TTS, błędy)
  - Keyboard PTT, ding sounds, partial transcript publishing
- **`playout.py`** — `StreamPlayoutMixin`
  - Audio capture thread (chunki 20ms → WebSocket)
  - TTS player thread (WebSocket → jitter buffer → playback)
  - Barge-in handling (przerwanie TTS przez nową mowę)

#### Moduły audio (niskopoziomowe)
**Pakiet `apps/voice/audio/`:**
- **`capture.py`** — przechwytywanie audio (ALSA/Pulse/command)
  - `CaptureConfig`, `capture_once()`, `capture_stream()`
  - VAD integration, silence detection
- **`playback.py`** — odtwarzanie audio (ALSA/Pulse)
  - `PlaybackConfig`, `play_audio()`, `play_ding()`
- **`alsa.py`** — narzędzia ALSA (lista urządzeń, konfiguracja dmix/dsnoop)
- **`errors.py`** — `ALSAError`, `AudioError`

> **Uwaga**: Pakiet `audio/*` planowany do migracji na top-level w przyszłych PR (obecnie w użyciu)

#### Moduły integracji backendu
- **`asr.py`** — ASR backends (OpenAI, Vosk)
- **`chat.py`** — Chat API (streaming generator dla realtime)
- **`tts.py`** — TTS backends (OpenAI, Piper)
- **`vad.py`** — Voice Activity Detection
- **`kws.py`** — Keyword Spotting (hotword)

#### CLI i API
- **`cli.py`** + **`cli_commands.py`** — interfejs linii poleceń
  - Komendy: `listen`, `ptt`, `once`, `asr`, `tts`, `diag`
  - Obsługa `--mode {stream,file}` dla każdej komendy
- **`web.py`** — HTTP API (Flask)
  - Endpointy: `/asr`, `/tts`, `/capture`, `/healthz`
- **`main.py`** — entry point dla systemd

### Przepływ danych — szczegóły

#### Tryb plikowy
1. **Trigger**: Hotword detection lub PTT (Enter key)
2. **Capture**: `audio/capture.py` → WAV file (VAD kończy nagranie po ciszy)
3. **ASR**: `asr.py` → pełna transkrypcja tekstu
4. **Chat**: `chat.py` → odpowiedź (pełny tekst)
5. **TTS**: `tts.py` → synteza audio (WAV/MP3 file)
6. **Playback**: `audio/playback.py` → speaker
7. **Loop**: Powrót do kroku 1 (w trybie `listen`)

**Zalety**: Niskie zużycie zasobów, kompatybilność z offline backends  
**Wady**: Brak partial results, opóźnienie (pełny pipeline sekwencyjny)

#### Tryb strumieniowy
1. **Connection**: `stream/transport.py` → WebSocket connect do realtime endpoint
2. **Session**: `session.create` → inicjalizacja konfiguracji (ASR/Chat/TTS)
3. **PTT Start**: User trigger → `PTTStateMachine.LISTENING`
4. **Audio duplex**:
   - **TX**: Capture thread → chunki 20ms PCM16 → `audio.append` WebSocket
   - **RX**: WebSocket → partial ASR (`transcript.delta`) → UI update
5. **Silence**: Server VAD → `audio.commit` → finalna transkrypcja
6. **Chat streaming**: Response generator → tekst (streaming) → sentence buffer
7. **TTS streaming**: Zdanie kompletne → TTS chunks → `audio.delta` (PCM16 base64)
8. **Playback**: TTS player thread → jitter buffer → speaker
9. **Barge-in**: Nowa mowa wykryta → cancel TTS, clear buffers, nowa tura (krok 4)
10. **PTT Stop**: Session cleanup → `PTTStateMachine.IDLE`

**Zalety**: Natychmiastowe partial results, niskie latencje, interaktywność  
**Wady**: Wymagany realtime backend (OpenAI Realtime API), wyższe koszty

### Historia zmian (PR#1–PR#5)

**PR#1: Clean & Freeze** (usunięto legacy files)
- ❌ `apps/voice/ws_transport.py` (289 linii) → duplikat, zastąpiony przez `stream/transport.py`
- ❌ `apps/voice/stream_transport.py` (120 linii) → duplikat, nieużywany
- ✅ Zachowano `audio/*` (aktywne użycie, migracja odroczona)

**PR#2: CLI Unification** (konsolidacja CLI)
- Usunięto odniesienia do nieistniejącego `cli_new.py`
- Jeden spójny moduł: `apps/voice/cli` + `cli_commands`
- Zaktualizowano Makefile (6 targets) i dokumentację

**PR#3: Tests Migration & Shim Removal** (cleanup shims)
- ❌ `apps/voice/svc_stream.py` (104 linii) → re-export shim, usunięty
- ❌ `apps/voice/state.py` (364 linii) → `StreamingVoicePTTMixin`, zastąpiony przez `stream/state.PTTStateMachine`
- ❌ `apps/voice/ptt_state.py` (324 linii) → duplikat, nieużywany
- ❌ Mixiny: `StreamingVoiceTransportMixin`, `StreamingVoicePTTMixin` → usunięte
- ✅ Nowy moduł: `svc_stream_runner.py` (wrappery CLI dla stream mode)
- Migracja 9 testów z legacy shims do nowych modułów

**PR#4: WebSocket Transport Consolidation** (deduplikacja transportu)
- ❌ `apps/voice/transport.py` (319 linii) → duplikat `stream/transport.py`, usunięty
- Jeden transport: `apps/voice/stream/transport.py`
- Aktualizacja quality guards (`scripts/dev_check-legacy-imports.py`)

**PR#5: Dokumentacja** (aktualizacja docs)
- Aktualizacja `ARCHITECTURE.md` z nową sekcją "Moduł Voice — Architektura szczegółowa"
- Rozszerzenie `docs/modules/voice.md` z sekcją "Architektura modułu"
- Konsolidacja informacji z PR#1–PR#4 summaries

### Statystyki refaktoryzacji

- **Usunięto**: ~1600 linii duplikatów i legacy code
- **Dodano**: ~500 linii nowych modułów (svc_stream_runner, dokumentacja)
- **Saldo netto**: -1100 linii (redukcja złożoności)
- **Pliki usunięte**: 6 (ws_transport, stream_transport, svc_stream, state, ptt_state, transport)
- **Pliki dodane**: 1 (svc_stream_runner)
- **Testy**: 100% migracja z legacy shims, wszystkie przechodzą



---

## Wymagania

- **Sprzęt/OS**: Raspberry Pi, Debian/Bookworm.
- **Python**: 3.11 (runtime na RPi), CI celuje w 3.9.
- **Audio**: ALSA / PulseAudio (`arecord`, `parec`, `paplay`).
- **Opcjonalnie modele offline**:
  - **Vosk** (ASR) — katalog modelu: `models/vosk` lub ustaw `vosk_model_dir`.
  - **Piper** (TTS) — plik `.onnx` (+ opcj. `.json`): `piper_model`, `piper_config`.
- **Chmura**: `OPENAI_API_KEY` dla ASR/TTS/chat jeśli używasz backendów OpenAI.

---

## Konfiguracja audio

### Konfiguracja dupleksu karty dźwiękowej WM8960

Karta dźwiękowa WM8960 nie obsługuje pełnego dupleksu na surowych urządzeniach `hw:`, co powoduje konflikty między odtwarzaniem dźwięku (`aplay`) a przechwytywaniem głosu (`arecord`). Aby rozwiązać ten problem:

1. **Skopiuj plik konfiguracyjny ALSA:**
   ```bash
   cp config/alsa/asoundrc.wm8960 ~/.asoundrc
   ```

2. **Konfiguracja dostarcza następujące aliasy:**
   - `wm8960_out` - dla odtwarzania audio (używa dmix do miksowania)
   - `wm8960_in` - dla przechwytywania audio (używa dsnoop do współdzielenia)
   - `wm8960` - dla interfejsu kontrolnego

3. **Konfiguracja jest już ustawiona w `config/voice.toml`:**
   ```toml
   [capture]
   device = "wm8960_in"
   
   [playback]
   alsa_device = "wm8960_out"
   ```

4. **Użyj trybów realtime z pasuspender:**
   ```bash
   make voice-once-realtime    # Pojedyncza interakcja
   make voice-listen-realtime  # Ciągłe nasłuchiwanie
   ```

5. **Parametry serwisu dla kontroli dźwięku:**
   - `--service beep=false` - Wyłącz dźwięk całkowicie
   - `--service beep_delay_ms=250` - Opóźnienie po dźwięku przed rozpoczęciem przechwytywania

---

## Konfiguracja

### Tryb strumieniowy (Realtime WebSocket)

Aby włączyć tryb strumieniowy, ustaw `transport = "realtime"` w odpowiednich sekcjach:

```toml
[asr]
backend = "openai"
transport = "realtime"          # Włącza strumieniowy ASR
model = "gpt-4o-realtime-preview"
language = "pl"
partial_results = true

[chat]
backend = "openai"
transport = "realtime"          # Włącza strumieniowy chat
model = "gpt-4o-realtime-preview"
system_prompt = "Odpowiadaj krótko po polsku."
max_tokens = 70

[tts]
backend = "openai"
transport = "realtime"          # Włącza strumieniowy TTS
model = "gpt-4o-realtime-preview"
voice = "ash"
format = "pcm16"

# Parametry streaming
[stream]
protocol = "websocket"
endpoint = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"
auth = "env:OPENAI_API_KEY"
chunk_ms = 20                   # Chunki audio co 20ms
sample_rate = 16000
turn_end_silence_ms = 700       # Czas ciszy kończącej turę
max_turn_ms = 6000              # Maksymalny czas tury
send_partials = true            # Publikuj partial ASR
server_vad = true               # Używaj VAD serwerowego
ping_interval_s = 10            # Ping WebSocket co 10s

[stream.reconnect]
max_retries = 6                 # Maksymalne próby reconnect
base_ms = 250                   # Bazowy delay reconnect
max_ms = 5000                   # Maksymalny delay reconnect

[stream.audio]
jitter_buffer_ms = 120          # Bufor jitter dla TTS
barge_in = true                 # Włącz przerwania TTS
```

**Funkcje trybu strumieniowego:**
- **Partial ASR**: Publikacja `ui.partial` z bieżącą hipotezą tekstu
- **Streaming TTS**: Odtwarzanie audio natychmiast po otrzymaniu pierwszych chunków
- **Barge-in**: Możliwość przerwania TTS przez rozpoczęcie nowej mowy
- **Reconnect**: Automatyczne wznawianie połączenia z exponential backoff
- **Duplex audio**: Równoczesne wysyłanie i odbieranie audio

**Nowa architektura (od v0.6+):**
- **Modułowy pipeline**: ASR (transkrypcja) → Chat (streaming) → TTS (sentence buffering)
- **Async streaming**: Odpowiedzi czatu generowane jako async generator
- **Sentence buffering**: TTS buforuje tekst do wykrycia końca zdania (`.`, `!`, `?`) przed syntezą
- **Elastyczność**: Możliwość użycia własnych modułów Chat/TTS zamiast end-to-end Realtime API

### Pliki i ENV

> **Pełna dokumentacja konfiguracji i polityki sekretów:** [docs/CONFIG_POLICY.md](../CONFIG_POLICY.md)

1. Skopiuj przykładowe ENV i uzupełnij:

   ```bash
   mkdir -p ~/.config/rider
   cp .env.voice.sample ~/.config/rider/voice.env
   export OPENAI_API_KEY=sk-...
   export VOICE_ASR_BACKEND=vosk
   export VOICE_TTS_BACKEND=piper
   export VOICE_TTS_VOICE=pl
   export VOICE_CAPTURE_BACKEND=pulse
   ```

2. Skopiuj TOML i dostosuj backendy/urządzenia/ścieżki modeli:

   ```bash
   cp config/voice.toml.sample config/voice.toml
   # edytuj: asr.backend, tts.backend, devices.*, models.*
   ```

3. (systemd) Możesz użyć ENV‑file dla usług:

   ```bash
   sudo mkdir -p /etc/rider
   sudo cp systemd/rider-voice.env.sample /etc/rider/voice.env
   ```

### Kluczowe ustawienia (ENV/TOML/CLI)

- `VOICE_ASR_BACKEND`: `openai` | `vosk` (obsługiwane obecnie).
- `VOICE_TTS_BACKEND`: `openai` | `piper`.
- `VOICE_CAPTURE_BACKEND`: `pulse` | `alsa` | `command` (+ `VOICE_CAPTURE_COMMAND`).
- `VOICE_TTS_VOICE` / `VOICE_TTS_MODEL`: zależnie od backendu.
- `VOICE_LOG_LEVEL`: `DEBUG` / `INFO` / `WARNING`…
- Gdzie ma słuchać Web: `VOICE_BIND` (np. `0.0.0.0:8092`).

> **Zasada repo‑first:** konfiguracja = TOML + ENV; brak nowych zależności instalowanych online.

---

## CLI (`apps.voice.cli`)

Każda subkomenda akceptuje dopasowania w stylu `--sekcja key=value` (np. `--asr backend=vosk model=...`).

```bash
python3 -m apps.voice.cli listen --hotword off
python3 -m apps.voice.cli ptt --asr backend=vosk --tts backend=piper
python3 -m apps.voice.cli once --lang pl
python3 -m apps.voice.cli asr --file samples/test.wav
python3 -m apps.voice.cli tts --text "Cześć, tu Rider!" --play
python3 -m apps.voice.cli diag
```

Najważniejsze przełączniki:

- `--hotword on|off|ptt` — tryb KWS; `ptt` = push‑to‑talk (ENTER).
- `--asr key=value` — np. `backend=vosk`, `language=pl`.
- `--tts key=value` — np. `backend=piper`, `voice=pl`.
- `--vad key=value` — np. `frame_ms=20`, `tail_ms=300`.
- `--save-audio on|off path=/sciezka` — zapis wejściowych WAV.
- `--log-level` — `DEBUG`/…

### Makefile (skrót)

```bash
make voice-run                 # ≈ listen
make voice-ptt                 # push-to-talk
make voice-once                # jeden cykl
make voice-asr-file FILE=...   # ASR na pliku
make voice-tts TEXT="Hello"     # TTS + odtwarzanie
make voice-web VOICE_BIND=0.0.0.0:8092
```

`VOICE_ARGS` pozwala przekazać dodatkowe opcje, np. `VOICE_ARGS="--asr backend=vosk"`.

---

## Web API (`apps.voice.web`)

Serwer (Flask) udostępnia:

- `GET /healthz` — status backendów.
- `POST /tts` — body JSON `{text, backend, voice, model}` → audio (`wav`/`mpeg`).
- `POST /asr` — `multipart/form-data`: `file=@…`, `backend`, `lang`.
- `POST /capture` — JSON z konfiguracją (`asr`, `tts`, `hotword`…) → audio odpowiedzi + nagłówki `X-Transcript`, `X-Intent`, `X-Latency`.

Start:

```bash
python3 -m apps.voice.web --bind 127.0.0.1:8092
curl -s http://127.0.0.1:8092/healthz | jq
```

Przykłady:

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

---

## Usługi (`systemd`)

Dostarczone unity:

- `rider-voice.service` — tryb CLI `listen`.
- `rider-voice-web.service` — HTTP API.

Instalacja:

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

> Integracja z `scripts/systemd-sync.sh`: unity są na allow-liście.

---

## Logowanie

`apps.voice.logging` wymusza kompaktowe JSON‑logi na stdout. Poziom ustawia `VOICE_LOG_LEVEL` lub `--log-level`.

```json
{"ts":"2025-09-21T12:00:00.123Z","level":"INFO","name":"voice.service","msg":"service.cycle.done","extra":{"data":{"latency":1.42,"intent":"chat"}}}
```

---

## Diagnostyka

```bash
python3 -m apps.voice.cli diag
```

Wyświetla bieżącą konfigurację, urządzenia audio (`arecord -l`, `pactl list short` jeśli dostępne)

- odtwarza sygnał kontrolny. Brak bibliotek opcjonalnych (np. `webrtcvad`, `libnyumaya`, `piper`) skutkuje ostrzeżeniem — wciąż działają tryby PTT i/lub chmurowe backendy.

---

## Notatki o modelach offline

- **Vosk** — pobierz lekkie modele (np. `vosk-model-small-pl-0.22`). Ścieżkę ustaw w `config/voice.toml` lub ENV `vosk_model_dir`.
- **Piper** — nie commitujemy modeli. Odnośniki: oficjalne wydania `rhasspy/piper`.
- **Nyumaya/Porcupine** — KWS skorzysta z bibliotek, jeśli obecne (konfiguruj w `hotword.*`).

---

## Różnice vs `_apps/voice` (migracja zakończona)

- **Brak importów** z `_apps/*` — nowy kod jest samowystarczalny.
- **Konfiguracja**: TOML + ENV + CLI zamiast globali.
- **Logi**: JSON + spójne nazwy loggerów.
- **Modułowość**: łatwe testy i fallback backendów, prostszy debug.
- **Web/API** i `systemd` w repo — gotowe do włączenia.

---

## Jakość i testy

- **Ruff** (lint/format) jest odpalany w hooku pre‑commit oraz na CI — błędy lintu blokują commit/PR.
- **Pytest**: testy jednostkowe/integracyjne w `tests/` (voice ma własne scenariusze).

Szybki start lokalnie:

```bash
ruff check apps/voice tests -q
pytest -q -k voice
```

---

## FAQ

**Q:** „Nie mam zainstalowanego `piper`/`webrtcvad`/`vosk` — co wtedy?”\
**A:** Odpal tryb `ptt` (`python3 -m apps.voice.cli ptt`) i backendy chmurowe (`openai`).

**Q:** „Jak przełączyć wejście audio na Pulse?”\
**A:** `VOICE_CAPTURE_BACKEND=pulse`, a urządzenie wybierz w `config/voice.toml`.

**Q:** „Czy Web API można wystawić poza localhost?”\
**A:** Tak, `--bind 0.0.0.0:8092` lub `VOICE_BIND=0.0.0.0:8092` (pamiętaj o zaporze).


## WM8960 (Raspberry Pi) – realtime
- ALSA: ustaw `~/.asoundrc` z `dmix` (play) + `dsnoop` (cap) i aliasami `wm8960_out`, `wm8960_in` (16 kHz).
- W `config/voice.toml` ustaw:
  - `[playback] device = "wm8960_out"`
  - `[capture]  device = "wm8960_in", sample_rate=16000, channels=1`
  - `[service]  beep=false` (na start); potem można `beep=true` + `beep_delay_ms=250`.
- Aplikacja odtwarza przez `aplay` z `PULSE_SERVER=127.0.0.1`, więc PulseAudio nie przeszkadza.

---

## Deprecated / Legacy Files

**⚠️  The following files/modules have been removed or deprecated during refactoring (PR#1–PR#4):**

### Summary Table

| Usunięty plik | PR | Powód | Migracja do |
|---------------|----|-----------------------------------------|-----------------|
| `ws_transport.py` | #1 | Duplikat WebSocket transport | `stream/transport.py` |
| `stream_transport.py` | #1 | Duplikat, nieużywany | `stream/transport.py` |
| `svc_stream.py` | #3 | Re-export shim, zbędny po modularyzacji | `stream/svc_streaming.py` lub `svc_stream_runner.py` |
| `state.py` | #3 | `StreamingVoicePTTMixin` duplikat | `stream/state.PTTStateMachine` |
| `ptt_state.py` | #3 | Duplikat PTT state, nieużywany | `stream/state.PTTStateMachine` |
| `transport.py` | #4 | Duplikat `stream/transport.py` | `stream/transport.py` |

**Usunięto razem**: 6 plików, ~1600 linii duplikatów i legacy code

### Removed in PR-1 (Clean & Freeze)
- **`apps/voice/ws_transport.py`** (289 linii) → Use `apps.voice.stream.transport` (WebSocket transport)
- **`apps/voice/stream_transport.py`** (120 linii) → Use `apps.voice.stream.transport`

### Removed in PR-2 (CLI Unification)
- Old CLI files consolidated into single `apps.voice.cli` module
- References to non-existent `cli_new.py` removed from Makefile and docs

### Removed in PR-3 (Tests Migration & Shim Removal)
- **`apps/voice/svc_stream.py`** (104 linii) → Use `apps.voice.stream.svc_streaming.StreamingVoiceService` or `apps.voice.svc_stream_runner` for CLI entry points
- **`apps/voice/state.py`** (364 linii, StreamingVoicePTTMixin) → Use `apps.voice.stream.state.PTTStateMachine`
- **`apps/voice/ptt_state.py`** (324 linii) → Use `apps.voice.stream.state.PTTStateMachine`
- **`StreamingVoiceTransportMixin`** → Use concrete transport classes from `apps.voice.stream.transport`
- **`StreamingVoicePTTMixin`** → Use `apps.voice.stream.state.PTTStateMachine`

### Removed in PR-4 (WebSocket Transport Consolidation)
- **`apps/voice/transport.py`** (319 linii) → Use `apps.voice.stream.transport` (duplicate removed, single implementation)

### Pending Migration
- **`apps/voice/audio/*`** directory (currently in use, migration planned)
  - Current: `from apps.voice.audio import alsa, capture, playback`
  - Future: Functionality will be integrated into top-level modules or remain as specialized subpackage
  - Note: Quality guard warns about imports but doesn't block (exit code 0)

### Migration Guide

**Streaming service:**
```python
# ❌ OLD (removed)
from apps.voice.svc_stream import StreamingVoiceService
from apps.voice.transport import WebSocketTransport
from apps.voice.state import StreamingVoicePTTMixin

# ✅ NEW (correct)
from apps.voice.stream.svc_streaming import StreamingVoiceService
from apps.voice.stream.transport import WebSocketTransport, ReconnectingTransport
from apps.voice.stream.state import PTTStateMachine
```

**CLI entry points:**
```python
# ❌ OLD (removed)
from apps.voice.svc_stream import run_listen_stream

# ✅ NEW (correct)
from apps.voice.svc_stream_runner import run_listen_stream
# or use high-level API:
from apps.voice.svc_core import run_listen
```

**PTT state machine:**
```python
# ❌ OLD (removed)
class MyService(StreamingVoicePTTMixin):
    pass

# ✅ NEW (correct)
from apps.voice.stream.state import PTTStateMachine, PTTEvent
ptt_state = PTTStateMachine(logger)
ptt_state.handle_event(PTTEvent.PTT_START)
```

### Quality Guards

Automatyczne sprawdzanie w pre-commit i CI (`scripts/dev_check-legacy-imports.py`):
- **Blokuje** importy usuniętych plików (exit code 1)
- **Ostrzega** o importach `audio/*` (exit code 0, soft warning)


