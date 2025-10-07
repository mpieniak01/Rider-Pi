# Konfiguracja Voice (`voice_file.toml`, `voice_streaming.toml`)

## Pliki konfiguracyjne

- **`voice_file.toml`** — tryb plikowy (REST API: ASR/Chat/TTS)
- **`voice_streaming.toml`** — tryb strumieniowy (Realtime WebSocket duplex)

## Wybór trybu

| Tryb | Use case | Latencja | Koszty | Wymagania |
|------|----------|----------|--------|-----------|
| **File** | PTT, batch processing | 1–3s | Niższe | REST API |
| **Streaming** | Konwersacja realtime | <500ms | Wyższe | WebSocket, GPT-4o-realtime |

---

## Parametry: voice_file.toml

### [logging]

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `level` | str | `INFO` | Poziom logów: DEBUG, INFO, WARNING, ERROR |

### [capture]

| Klucz | Typ | Zakres | Domyślna | Opis |
|-------|-----|--------|----------|------|
| `backend` | str | alsa, pulse | `alsa` | Backend capture audio |
| `device` | str | — | `wm8960_in` | Urządzenie ALSA (alias lub hw:X,Y) |
| `sample_rate` | int | 8k–48k | `16000` | Częstotliwość próbkowania (Hz) |
| `channels` | int | 1, 2 | `1` | Liczba kanałów (1=mono, 2=stereo) |
| `frame_ms` | int | 10–30 | `20` | Rozmiar ramki (ms) |
| `buffer_seconds` | float | 0.05–1.0 | `0.10` | Rozmiar bufora (s) |
| `sample_format` | str | — | `S16_LE` | Format próbek (S16_LE = 16-bit signed) |

**Uwagi:**
- `device = "wm8960_in"` wymaga aliasu w `.asoundrc` (patrz [alsa.md](alsa.md))
- `sample_rate = 16000` jest optymalne dla ASR (Whisper, Vosk)

### [playback]

| Klucz | Typ | Zakres | Domyślna | Opis |
|-------|-----|--------|----------|------|
| `backend` | str | alsa, pulse | `alsa` | Backend playback audio |
| `device` | str | — | `wm8960_out` | Urządzenie ALSA |
| `volume` | int | 0–100 | `80` | Głośność wyjścia (%) |

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
| `transport` | str | rest, realtime | `rest` | Transport chat |

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

## Parametry: voice_streaming.toml

### Różnice vs voice_file.toml

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
python -m apps.voice.cli diag --config config/voice_file.toml
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
