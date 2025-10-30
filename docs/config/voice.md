# Konfiguracja Voice

## Konwencja nazewnicza plików konfiguracyjnych

**Od wersji 2025-01**, pliki konfiguracyjne voice używają jednoznacznej konwencji nazewniczej:

```
voice_<provider>_<mode>.toml
```

Gdzie:
- **`<provider>`** — dostawca usług AI: `openai`, `gemini`, `local`
- **`<mode>`** — tryb komunikacji: `file` (REST API), `streaming` (WebSocket)

**Dostępne pliki:**

| Plik | Provider | Tryb | Opis |
|------|----------|------|------|
| `voice_openai_file.toml` | OpenAI | REST | Tryb plikowy (PTT, batch) |
| `voice_openai_streaming.toml` | OpenAI | WebSocket | Tryb strumieniowy (realtime) |
| `voice_openai_streaming_fallback.toml` | OpenAI | WebSocket | Streaming z fallbackiem |
| `voice_gemini_file.toml` | Google Gemini | REST | Tryb plikowy z Gemini |
| `voice_gemini_example.toml` | Google Gemini | - | Przykładowa konfiguracja |
| `voice.toml` | Local (Piper/Vosk) | REST | Lokalny TTS/ASR przez HTTP (port 8092) — używany przez `make PROVIDER=local` |
| `voice_local_file.toml` | Local (Piper/Vosk) | REST | Alternatywna konfiguracja lokalna |

**Przykład użycia:**
```bash
# OpenAI w trybie plikowym (domyślny)
make voice-file-ptt

# Lokalny Piper/Vosk (bez API key) - używa config/voice.toml
make voice-file-ptt PROVIDER=local

# Lub bezpośrednio z voice_local_file.toml
python -m apps.voice.cli --config ./config/voice_local_file.toml ptt

# Google Gemini w trybie plikowym
python -m apps.voice.cli --config ./config/voice_gemini_file.toml ptt

# OpenAI w trybie strumieniowym
make voice-stream-listen
```

---

## Pliki konfiguracyjne

- **`voice_openai_file.toml`** — tryb plikowy (REST API: ASR/Chat/TTS) z OpenAI
- **`voice_openai_streaming.toml`** — tryb strumieniowy (Realtime WebSocket duplex) z OpenAI
- **`voice.toml`** — tryb plikowy z lokalnymi backendami (Piper TTS, Vosk ASR) przez HTTP API na porcie 8092 (używany przez `make PROVIDER=local`)
- **`voice_local_file.toml`** — alternatywna konfiguracja lokalna (podobna do voice.toml)

## Wybór trybu

| Tryb | Use case | Latencja | Koszty | Wymagania |
|------|----------|----------|--------|-----------|
| **File** | PTT, batch processing | 1–3s | Niższe | REST API |
| **Streaming** | Konwersacja realtime | <500ms | Wyższe | WebSocket, GPT-4o-realtime |
| **Local** | Offline, bez API key | 1–2s | Brak | Lokalne modele Piper/Vosk, rider-voice-web.service |

---

## Parametry: voice_openai_file.toml

### [logging]

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `level` | str | `INFO` | Poziom logów: DEBUG, INFO, WARNING, ERROR |

### [capture]

| Klucz | Typ | Zakres | Domyślna | Opis |
|-------|-----|--------|----------|------|
| `backend` | str | alsa, pulse | `alsa` | Backend capture audio |
| `device` | str | — | `wm8960_in` | Urządzenie ALSA (alias, np. `wm8960_in` lub pełna nazwa `plughw:CARD=wm8960soundcard,DEV=0`) |
| `sample_rate` | int | 8k–48k | `16000` | Częstotliwość próbkowania (Hz) |
| `channels` | int | 1, 2 | `1` | Liczba kanałów (1=mono, 2=stereo) |
| `frame_ms` | int | 10–30 | `20` | Rozmiar ramki (ms) |
| `buffer_seconds` | float | 0.05–1.0 | `0.10` | Rozmiar bufora (s) |
| `sample_format` | str | — | `S16_LE` | Format próbek (S16_LE = 16-bit signed) |

**Uwagi:**
- `device` akceptuje:
  - **Alias ALSA** (np. `wm8960_in`) – wymaga definicji w `~/.asoundrc` (patrz [alsa.md](alsa.md))
  - **Pełna nazwa urządzenia** (np. `plughw:CARD=wm8960soundcard,DEV=0`) – działa bez aliasu
  - **Nazwa karty** (np. `hw:wm8960soundcard,0`) – bezpośrednie odwołanie do hardware
- Używanie **nazw urządzeń zamiast indeksów** zapewnia stabilność po każdym restarcie systemu
- `sample_rate = 16000` jest optymalne dla ASR (Whisper, Vosk)

**Jak znaleźć nazwę swojego urządzenia:**
```bash
# Lista urządzeń do nagrywania (capture)
arecord -l

# Przykładowy output:
# card 1: wm8960soundcard [wm8960-soundcard], device 0: bcm2835-i2s-wm8960-hifi wm8960-hifi-0 [bcm2835-i2s-wm8960-hifi wm8960-hifi-0]

# Z powyższego możesz użyć:
# - plughw:CARD=wm8960soundcard,DEV=0  (zalecane, automatyczna konwersja formatu)
# - hw:wm8960soundcard,0               (direct hardware access)
# - hw:1,0                             (NIE zalecane - indeks może się zmienić!)
```

### [playback]

| Klucz | Typ | Zakres | Domyślna | Opis |
|-------|-----|--------|----------|------|
| `backend` | str | alsa, pulse | `alsa` | Backend playback audio |
| `device` | str | — | `wm8960_out` | Urządzenie ALSA (alias, np. `wm8960_out` lub pełna nazwa `plughw:CARD=wm8960soundcard,DEV=0`) |
| `volume` | int | 0–100 | `80` | Głośność wyjścia (%) |

**Uwagi:**
- Podobnie jak `capture.device`, akceptuje aliasy ALSA lub pełne nazwy urządzeń
- Używanie nazw urządzeń zapewnia stabilność konfiguracji

**Jak znaleźć nazwę swojego urządzenia:**
```bash
# Lista urządzeń do odtwarzania (playback)
aplay -l

# Przykładowy output:
# card 1: wm8960soundcard [wm8960-soundcard], device 0: bcm2835-i2s-wm8960-hifi wm8960-hifi-0 [bcm2835-i2s-wm8960-hifi wm8960-hifi-0]

# Z powyższego możesz użyć:
# - plughw:CARD=wm8960soundcard,DEV=0  (zalecane)
# - hw:wm8960soundcard,0               (direct hardware)
# - hw:1,0                             (NIE zalecane - indeks może się zmienić!)
```

### [asr]

| Klucz | Typ | Wartości | Domyślna | Opis |
|-------|-----|----------|----------|------|
| `transport` | str | rest, realtime | `rest` | Transport ASR |
| `language` | str | pl, en, ... | `pl` | Język rozpoznawania |

#### [asr.vad]

| Klucz | Typ | Zakres | Domyślna | Opis |
|-------|-----|--------|----------|------|
| `enabled` | bool | — | `false` | Włącz VAD (Voice Activity Detection) |
| `aggressiveness` | int | 0–3 | `2` | Agresywność VAD (wyższy = bardziej czuły) |
| `start_ms` | int | >0 | `120` | Czas początku aktywności (ms) |
| `end_ms` | int | >0 | `650` | Czas końca aktywności (ms) |

**Uwagi:**
- VAD w trybie PTT jest zbędny (nagrywanie na klawisz)
- Włącz VAD tylko przy ciągłym nasłuchu

### [chat]

| Klucz | Typ | Wartości | Domyślna | Opis |
|-------|-----|----------|----------|------|
| `backend` | str | openai, google, local, echo | `openai` | Wybór dostawcy czatu |
| `transport` | str | rest, realtime | `rest` | Transport chat |
| `model` | str | — | — | Identyfikator modelu (np. `gpt-4o-mini` lub `gemini-pro`) |
| `system_prompt` | str | — | — | Prompt systemowy definiujący zachowanie asystenta |
| `max_history` | int | ≥0 | `4` | Maksymalna liczba par user/assistant w historii |
| `max_tokens` | int | ≥1 lub None | `None` | Limit tokenów w odpowiedzi (opcjonalny) |
| `base_url` | str | — | `http://127.0.0.1:8092` | URL serwera dla backendu `local` |
| `endpoint` | str | — | `/api/chat` | Endpoint API dla backendu `local` |
| `timeout` | float | ≥1 | `20.0` | Timeout dla żądań HTTP (sekundy) |
| `llm_main_path` | str | — | `llama.cpp/main` | Ścieżka do binarki llama.cpp (tylko backend `local`) |
| `llm_model_path` | str | — | `models/llm/phi-3-mini-3.8b-instruct.Q4_K_M.gguf` | Ścieżka do modelu GGUF (tylko backend `local`) |
| `llm_extra_args` | str | — | `-t 4 -n 256 --ctx-size 1024 --simple-io --temp 0.7` | Dodatkowe argumenty dla llama.cpp (tylko backend `local`) |

**Backendy:**
- **`openai`** — OpenAI Chat Completions API (wymaga `OPENAI_API_KEY`)
- **`google`** — Google Gemini API (wymaga `GOOGLE_API_KEY`)
- **`local`** — Lokalny LLM przez llama.cpp (wymaga instalacji llama.cpp i modelu GGUF)
- **`echo`** — Testowy backend odbijający wiadomości (bez AI)

**Zmienne środowiskowe:**
- `OPENAI_API_KEY` — klucz API dla backendu OpenAI
- `GOOGLE_API_KEY` — klucz API dla backendu Google Gemini

**Przykład konfiguracji (Google Gemini):**

```toml
[chat]
backend = "google"
model = "gemini-pro"
system_prompt = "Jesteś asystentem głosowym. Odpowiadaj krótko po polsku."
max_history = 4
```

**Przykład konfiguracji (Local LLM):**

```toml
[chat]
backend = "local"
base_url = "http://127.0.0.1:8092"
endpoint = "/api/chat"
timeout = 20.0
system_prompt = "Jesteś asystentem głosowym Rider-Pi. Odpowiadaj krótko po polsku."
max_history = 4
max_tokens = 512

# Konfiguracja llama.cpp (wymagane dla backendu 'local')
llm_main_path = "llama.cpp/main"
llm_model_path = "models/llm/phi-3-mini-3.8b-instruct.Q4_K_M.gguf"
llm_extra_args = "-t 4 -n 256 --ctx-size 1024 --simple-io --temp 0.7"
```

**Uwagi dla backendu `local`:**
- Wymaga uruchomionego serwera `rider-voice-web.service` na porcie 8092
- Wymaga instalacji [llama.cpp](https://github.com/ggerganov/llama.cpp) i pobrania modelu GGUF
- Rekomendowany model dla Raspberry Pi: Phi-3-mini (3.8B parametrów, quantized Q4)
- Flagi `llm_extra_args`: `-t 4` (4 wątki), `--simple-io` (prostsze wyjście), `--temp 0.7` (temperatura generowania)

### [tts]

| Klucz | Typ | Wartości | Domyślna | Opis |
|-------|-----|----------|----------|------|
| `transport` | str | rest, realtime | `rest` | Transport TTS |
| `voice` | str | alloy, ash, ... | `ash` | Głos TTS |
| `format` | str | mp3, wav, pcm16 | `mp3` | Format audio wyjściowego |

**Dostępne głosy:** `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`

### [service]

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `beep` | bool | `true` | Odtwórz "beep" po aktywacji |
| `beep_delay_ms` | int | `250` | Opóźnienie beep (ms) |

#### [service.turn]

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `max_turn_ms` | int | `6000` | Maksymalny czas tury (ms) |
| `key_exit` | bool | `true` | Klawisz kończy turę |
| `commit_on_key` | bool | `true` | Commit na klawisz (PTT) |

---

## Parametry: voice_openai_streaming.toml

### Różnice vs voice_openai_file.toml

Streaming używa tych samych sekcji `[logging]`, `[capture]`, `[playback]`, ale z dodatkowymi parametrami:

### [asr]

```toml
[asr]
transport = "realtime"  # WebSocket duplex
language  = "pl"
```

### [chat]

```toml
[chat]
transport     = "realtime"
system_prompt = "Mów po polsku, krótko i rzeczowo. Jeśli pytanie jest krótkie, odpowiadaj w 1–2 zdaniach."
```

### [tts]

```toml
[tts]
transport = "realtime"
voice     = "ash"
format    = "pcm16"     # Realtime używa PCM16
```

### [stream]

**Kluczowe parametry strumieniowania:**

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `auth` | str | `env:OPENAI_API_KEY` | Autoryzacja (czytaj z ENV) |
| `endpoint` | str | wss://api.openai.com/... | Endpoint WebSocket |
| `chunk_ms` | int | `20` | Rozmiar chunka audio (ms) |
| `sample_rate` | int | `16000` | Sample rate (Hz) |
| `turn_end_silence_ms` | int | `700` | Cisza kończąca turę (ms) |
| `max_turn_ms` | int | `15000` | Maksymalny czas tury (ms) |
| `send_partials` | bool | `false` | Wysyłaj częściowe transkrypty |
| `server_vad` | bool | `true` | Użyj VAD po stronie serwera |
| `local_vad_fallback` | bool | `false` | Fallback na lokalny VAD |
| `ping_interval_s` | int | `10` | Interwał ping WebSocket (s) |

#### [stream.audio]

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `jitter_buffer_ms` | int | `80` | Bufor jitter (balans: płynność vs. latencja) |
| `barge_in` | bool | `true` | Przerwanie wypowiedzi asystenta |

#### [stream.reconnect]

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `max_retries` | int | `6` | Maksymalna liczba prób reconnect |
| `base_ms` | int | `250` | Bazowy czas backoff (ms) |
| `max_ms` | int | `5000` | Maksymalny czas backoff (ms) |

---

## Parametry: voice_local_file.toml

Konfiguracja dla lokalnych backendów (Piper TTS, Vosk ASR) dostępnych przez HTTP API na porcie 8092.

### [asr]

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `backend` | str | `local` | Backend ASR (local = Vosk przez HTTP) |
| `base_url` | str | `http://127.0.0.1:8092` | URL voice-web API |
| `endpoint` | str | `/api/asr` | Endpoint ASR |
| `content_type` | str | `audio/wav` | Typ zawartości |
| `language` | str | `pl` | Język rozpoznawania |
| `timeout` | int | `8` | Timeout żądania (sekundy) |

### [tts]

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `backend` | str | `local` | Backend TTS (local = Piper przez HTTP) |
| `base_url` | str | `http://127.0.0.1:8092` | URL voice-web API |
| `endpoint` | str | `/api/tts` | Endpoint TTS |
| `voice` | str | `pl_m` | Głos Piper (pl_m = polski męski) |
| `model` | str | `small` | Model głosu |
| `format` | str | `wav` | Format audio |
| `timeout` | int | `10` | Timeout żądania (sekundy) |
| `transport` | str | `file` | Tryb transportu |

### [chat]

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `backend` | str | `local` | Backend chat (local = lokalny model) |
| `model` | str | `small` | Model chat |
| `system_prompt` | str | - | Prompt systemowy |
| `transport` | str | `file` | Tryb transportu |
| `max_history` | int | `4` | Maksymalna historia konwersacji |
| `max_tokens` | int | `512` | Maksymalna długość odpowiedzi |
| `base_url` | str | `http://127.0.0.1:8092` | URL API (dla przyszłych rozszerzeń) |

**Uwagi:**
- Wymaga uruchomionego `rider-voice-web.service` na porcie 8092
- Modele Piper i Vosk muszą być zainstalowane lokalnie (patrz `PIPER_MODEL_DIR`, `VOSK_MODEL_DIR`)
- Działa offline bez API keys

---

## Przykłady konfiguracji

### Minimalna (PTT, offline)

```toml
[capture]
backend = "alsa"
device = "wm8960_in"

[playback]
backend = "alsa"
device = "wm8960_out"

[asr]
transport = "rest"
backend = "vosk"  # offline ASR

[tts]
transport = "rest"
backend = "piper"  # offline TTS
```

### Produkcyjna (streaming, WM8960)

```toml
[capture]
backend = "alsa"
device = "wm8960_in"
sample_rate = 16000
channels = 1

[playback]
backend = "alsa"
device = "wm8960_out"
volume = 55

[stream]
auth = "env:OPENAI_API_KEY"
turn_end_silence_ms = 700
max_turn_ms = 15000
server_vad = true

[stream.audio]
jitter_buffer_ms = 80
barge_in = true
```

### Debug (wysokie logi, VAD disabled)

```toml
[logging]
level = "DEBUG"

[asr.vad]
enabled = false

[service]
beep = false  # bez beep dla debug
```

---

## Diagnostyka

### Sprawdzenie załadowanej konfiguracji

```bash
python -m apps.voice.cli diag --config config/voice_openai_file.toml
```

### Test urządzeń ALSA

```bash
# Capture
arecord -D wm8960_in -d 5 -f S16_LE -r 16000 test.wav

# Playback
aplay -D wm8960_out test.wav
```

### Typowe problemy

| Problem | Możliwa przyczyna | Rozwiązanie |
|---------|-------------------|-------------|
| Brak dźwięku | Zły alias device | Sprawdź `.asoundrc`, użyj `aplay -L` |
| Zniekształcony dźwięk | Niewłaściwy sample_rate | Ustaw `16000` (standard dla voice) |
| Wysoka latencja | Zbyt duży buffer | Zmniejsz `buffer_seconds` (min 0.05) |
| Reconnect loop | Zły klucz API | Sprawdź `OPENAI_API_KEY` |

---

**Related docs:**
- [docs/modules/voice.md](../modules/voice.md) — pełna dokumentacja modułu voice
- [alsa.md](alsa.md) — konfiguracja ALSA
- [CONFIG_POLICY.md](../CONFIG_POLICY.md) — polityka konfiguracji

**Ostatnia aktualizacja:** 2025-01

---

## Deprecated Configuration Files

**⚠️  Legacy configuration patterns:**

The voice module has been refactored. Configuration files remain unchanged, but internal imports have been reorganized:

- Legacy transport files (`ws_transport.py`, `stream_transport.py`) → Use `apps.voice.stream.transport`
- Legacy state files (`state.py`, `ptt_state.py`) → Use `apps.voice.stream.state`
- `apps/voice/audio/*` directory (pending migration to top-level modules)

**No action required** for users - configuration keys remain the same. See [docs/modules/voice.md](../modules/voice.md#deprecated--legacy-files) for developer migration guide.
