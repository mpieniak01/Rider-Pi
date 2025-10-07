# Skrypty głosowe (`ops/voice-*.sh`)

## voice-run.sh

### Opis

**Legacy script** do uruchamiania aplikacji głosowej z konfiguracją przez zmienne środowiskowe.

⚠️ **Uwaga:** Dla nowych wdrożeń rozważ nowoczesne podejście z plikami konfiguracyjnymi TOML (patrz `apps/voice/cli.py`).

### Użycie

```bash
./ops/voice-run.sh             # domyślnie tryb BUS (VOICE_STANDALONE=0)
./ops/voice-run.sh bus         # wymuś tryb BUS
./ops/voice-run.sh standalone  # wymuś tryb STANDALONE (mowa + chat w voice)

# Nadpisywanie parametrów
HOTWORD_THRESHOLD=0.62 ./ops/voice-run.sh standalone
```

### Parametry ENV

| Zmienna | Typ | Domyślna | Opis |
|---------|-----|----------|------|
| `OPENAI_API_KEY` | str | z `~/.bash_profile` | Klucz API OpenAI |
| `ALSA_DEVICE` | str | `plughw:1,0` | Urządzenie ALSA |
| `HOTWORD_THRESHOLD` | float | `0.60` | Próg detekcji hotword |
| `EXTRACTOR_GAIN` | float | `1.0` | Wzmocnienie ekstraktora cech |
| `VAD_MODE` | int | `3` | Tryb VAD (0–3, wyższy = bardziej agresywny) |
| `VAD_FRAME_MS` | int | `20` | Rozmiar ramki VAD (ms) |
| `VAD_SILENCE_TAIL_MS` | int | `300` | Ogon ciszy VAD (ms) |
| `VAD_MAX_LEN_S` | float | `4.0` | Maksymalna długość nagrania (s) |
| `ENERGY_CUTOFF_DBFS` | float | `-36.0` | Próg energii (dBFS) |
| `ENERGY_TAIL_MS` | int | `180` | Ogon energii (ms) |
| `ALSA_BUFFER_US` | int | `50000` | Bufor ALSA (µs) |
| `ALSA_PERIOD_US` | int | `12000` | Okres ALSA (µs) |
| `STREAM_TTS` | int | `1` | Strumieniowe TTS (0/1) |
| `STREAM_CHUNK` | int | `8192` | Rozmiar chunka strumieniowego |
| `STREAM_PITCH` | float | `0.0` | Pitch shift TTS |
| `RECORDINGS_DIR` | str | `/home/pi/robot/data/recordings` | Katalog nagrań |
| `KEEP_INPUT_WAV` | int | `0` | Zachowaj WAV wejściowy (0/1) |
| `KEEP_OUTPUT_WAV` | int | `0` | Zachowaj WAV wyjściowy (0/1) |
| `DING_PLAY_MS` | int | `200` | Czas "ding" po hotword (ms) |
| `VOICE_STANDALONE` | int | `0` | Tryb standalone (0=BUS, 1=standalone) |

### Tryby pracy

#### BUS (domyślny)

```bash
./ops/voice-run.sh bus
```

- ASR → publikuje na `audio.transcript`
- TTS subskrybuje `tts.speak`
- Wymaga osobnych procesów: `apps/chat`, `apps/nlu`

#### STANDALONE

```bash
./ops/voice-run.sh standalone
```

- ASR + Chat + TTS w jednym procesie
- Nie wymaga BUS
- Dla prostych wdrożeń bez pełnej architektury

### Ładowanie klucza API

Skrypt automatycznie ładuje `OPENAI_API_KEY` z:
1. `~/.bash_profile`
2. `~/.profile`  (w porządku priorytetu)

Jeśli klucz nie zostanie znaleziony, skrypt kończy się błędem.

### Konfiguracja ALSA

```bash
# Sprawdź dostępne urządzenia
aplay -l

# Ustaw urządzenie
export ALSA_DEVICE=hw:wm8960soundcard,0
./ops/voice-run.sh
```

### Przykłady

#### Podstawowe uruchomienie

```bash
source ~/.bash_profile  # załaduj OPENAI_API_KEY
./ops/voice-run.sh
```

#### Konfiguracja zaawansowana

```bash
export ALSA_DEVICE=hw:wm8960soundcard,0
export HOTWORD_THRESHOLD=0.65
export VAD_MODE=2
export STREAM_TTS=1
./ops/voice-run.sh standalone
```

#### Debug (zachowaj nagrania)

```bash
export KEEP_INPUT_WAV=1
export KEEP_OUTPUT_WAV=1
export RECORDINGS_DIR=/tmp/voice_debug
./ops/voice-run.sh
```

### Diagnostyka

```bash
# Sprawdź klucz API
env | grep OPENAI_API_KEY

# Test ALSA
arecord -D $ALSA_DEVICE -d 5 -f S16_LE -r 16000 test.wav
aplay test.wav

# Monitoruj logi
./ops/voice-run.sh 2>&1 | tee voice.log
```

---

## voice-once.sh

### Opis

Wykonuje **pojedyncze polecenie głosowe** — uproszczona wersja do szybkich testów.

⚠️ **Wymaga weryfikacji:** Szczegóły implementacji do uzupełnienia.

### Użycie

```bash
./ops/voice-once.sh
```

### Przykład

```bash
# Jedno polecenie PTT (push-to-talk)
./ops/voice-once.sh
# [nagranie przez X sekund]
# → transkrypcja → OpenAI → TTS → odtworzenie
```

### Różnice vs voice-run.sh

| Feature | voice-run.sh | voice-once.sh |
|---------|--------------|---------------|
| Tryb | Ciągły (loop) | Jedno wywołanie |
| Hotword | Tak | Opcjonalnie |
| Use case | Daemon/service | Testing/debug |

---

## Migracja z voice-run.sh

### Do nowoczesnego API (apps/voice/cli)

**Stary sposób:**
```bash
export VAD_MODE=3
export HOTWORD_THRESHOLD=0.65
./ops/voice-run.sh
```

**Nowy sposób:**
```bash
# Utwórz config/local/voice_dev.toml
python -m apps.voice.cli listen --config config/local/voice_dev.toml
```

**Korzyści:**
- Konfiguracja w TOML (łatwiej wersjonować)
- Lepsze logowanie (JSON structured logs)
- Zgodność z CONFIG_POLICY.md

### Zobacz także

- [docs/modules/voice.md](../modules/voice.md) — pełna dokumentacja modułu voice
- [docs/CONFIG_POLICY.md](../CONFIG_POLICY.md) — polityka konfiguracji
- [docs/config/voice.md](../config/voice.md) — parametry TOML

---

**Ostatnia aktualizacja:** 2025-01  
**Status:** voice-run.sh = legacy (ale stabilny), nowoczesne API w `apps/voice/cli`
