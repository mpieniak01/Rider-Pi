# Skrypty głosowe

> Dokumentacja skryptów do obsługi modułu głosowego: `sys_voice-*.sh`, `talk_*.sh`

## voice-run.sh

### Opis

**Legacy script** do uruchamiania aplikacji głosowej z konfiguracją przez zmienne środowiskowe.

⚠️ **Uwaga:** Dla nowych wdrożeń rozważ nowoczesne podejście z plikami konfiguracyjnymi TOML (patrz `apps/voice/cli.py`).

### Użycie

```bash
./scripts/sys_voice-run.sh             # domyślnie tryb BUS (VOICE_STANDALONE=0)
./scripts/sys_voice-run.sh bus         # wymuś tryb BUS
./scripts/sys_voice-run.sh standalone  # wymuś tryb STANDALONE (mowa + chat w voice)

# Nadpisywanie parametrów
HOTWORD_THRESHOLD=0.62 ./scripts/sys_voice-run.sh standalone
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
./scripts/sys_voice-run.sh bus
```

- ASR → publikuje na `audio.transcript`
- TTS subskrybuje `tts.speak`
- Wymaga osobnych procesów: `apps/chat`, `apps/nlu`

#### STANDALONE

```bash
./scripts/sys_voice-run.sh standalone
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
./scripts/sys_voice-run.sh
```

### Przykłady

#### Podstawowe uruchomienie

```bash
source ~/.bash_profile  # załaduj OPENAI_API_KEY
./scripts/sys_voice-run.sh
```

#### Konfiguracja zaawansowana

```bash
export ALSA_DEVICE=hw:wm8960soundcard,0
export HOTWORD_THRESHOLD=0.65
export VAD_MODE=2
export STREAM_TTS=1
./scripts/sys_voice-run.sh standalone
```

#### Debug (zachowaj nagrania)

```bash
export KEEP_INPUT_WAV=1
export KEEP_OUTPUT_WAV=1
export RECORDINGS_DIR=/tmp/voice_debug
./scripts/sys_voice-run.sh
```

### Diagnostyka

```bash
# Sprawdź klucz API
env | grep OPENAI_API_KEY

# Test ALSA
arecord -D $ALSA_DEVICE -d 5 -f S16_LE -r 16000 test.wav
aplay test.wav

# Monitoruj logi
./scripts/sys_voice-run.sh 2>&1 | tee voice.log
```

---

## voice-once.sh

### Opis

Wykonuje **pojedyncze polecenie głosowe** — uproszczona wersja do szybkich testów.

⚠️ **Wymaga weryfikacji:** Szczegóły implementacji do uzupełnienia.

### Użycie

```bash
./scripts/sys_voice-once.sh
```

### Przykład

```bash
# Jedno polecenie PTT (push-to-talk)
./scripts/sys_voice-once.sh
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
./scripts/sys_voice-run.sh
```

**Nowy sposób:**
```bash
# Utwórz config/local/voice_dev.toml
python -m apps.voice.cli listen --config config/local/voice_dev.toml
```

**Korzyści:**
- Konfiguracja w TOML (łatwiej wersjonować)
- Lepsze logowanie (JSON structured logs)
- Zgodność z config/POLICY.md

### Zobacz także

- [docs/modules/voice.md](../modules/voice.md) — pełna dokumentacja modułu voice
- [docs/config/POLICY.md](../config/POLICY.md) — polityka konfiguracji
- [docs/config/voice.md](../config/voice.md) — parametry TOML

---

**Ostatnia aktualizacja:** 2025-01  
**Status:** voice-run.sh = legacy (ale stabilny), nowoczesne API w `apps/voice/cli`

---

## talk_local.sh

### Opis

Proste demo lokalne TTS/ASR wykorzystujące HTTP API na porcie 8092 (`rider-voice-web.service`). Nagrywa dźwięk z mikrofonu, rozpoznaje mowę przez lokalny Vosk, a następnie odtwarza rozpoznany tekst przez lokalny Piper TTS.

**Typ:** Demo / proof-of-concept dla lokalnych backendów bez kluczy API

### Użycie

```bash
./scripts/talk_local.sh [czas_nagrania_w_sekundach]

# Przykłady
./scripts/talk_local.sh      # Domyślnie 3 sekundy nagrania
./scripts/talk_local.sh 5    # 5 sekund nagrania
./scripts/talk_local.sh 10   # 10 sekund nagrania
```

### Przepływ danych

```
1. Mikrofon → arecord (plughw:0,0, 16kHz, mono) → /tmp/in.wav
2. /tmp/in.wav → POST http://127.0.0.1:8092/api/asr → JSON {text: "..."}
3. Wyświetlenie rozpoznanego tekstu na konsoli
4. Tekst → POST http://127.0.0.1:8092/api/tts → /tmp/out.wav
5. /tmp/out.wav → aplay → głośnik
```

### Parametry

| Parametr | Typ | Domyślna | Opis |
|----------|-----|----------|------|
| `$1` | int | `3` | Długość nagrania w sekundach |

**Hardcoded w skrypcie:**
- Urządzenie ALSA: `plughw:0,0`
- Format audio: S16_LE, 16000 Hz, 1 kanał
- Głos Piper: `pl_PL-gosia-medium.onnx`
- Backend TTS: `piper`

### Wymagania

- ✅ Uruchomiona usługa `rider-voice-web.service` na porcie 8092
- ✅ Mikrofon i głośnik podłączone i skonfigurowane w ALSA
- ✅ Zainstalowane narzędzia: `arecord`, `aplay`, `curl`, `jq`
- ✅ Modele lokalne: Piper (`pl_PL-gosia-medium.onnx`) i Vosk (`vosk-model-small-pl-0.22`)

### Uruchomienie usługi voice-web

```bash
# Sprawdź status
sudo systemctl status rider-voice-web.service

# Uruchom (jeśli nie działa)
sudo systemctl start rider-voice-web.service

# Lub bezpośrednio (development)
python3 -m apps.voice.web --bind 0.0.0.0:8092
```

### Przykład sesji

```bash
$ ./scripts/talk_local.sh 3
[REC] Mów przez 3 s…
[ASR] Rozpoznaję…
[ASR] >> cześć jak się masz
[TTS] Odpowiadam…
Playing WAVE '/tmp/out.wav' : Signed 16 bit Little Endian, Rate 48000 Hz, Stereo
```

### Troubleshooting

**Problem:** `curl: (7) Failed to connect to 127.0.0.1 port 8092`
- **Rozwiązanie:** Uruchom `rider-voice-web.service` (patrz wyżej)

**Problem:** `arecord: main:830: audio open error: No such file or directory`
- **Rozwiązanie:** Sprawdź urządzenie ALSA: `arecord -l`, dostosuj `plughw:X,Y` w skrypcie

**Problem:** `jq: parse error: Invalid numeric literal`
- **Rozwiązanie:** API zwrócił błąd, sprawdź logi: `journalctl -u rider-voice-web -n 50`

---

## talk_assistant.sh

### Opis

Interaktywny asystent głosowy w pętli wykorzystujący lokalne backendy Piper/Vosk. Rozpoznaje proste komendy (godzina, echo, stop) i reaguje syntezą mowy.

**Typ:** Demo interaktywne / przykład implementacji prostego asystenta

### Użycie

```bash
./scripts/talk_assistant.sh

# W pętli mówisz komendy, asystent odpowiada
# Zakończ mówiąc: "stop", "koniec" lub "zakończ"
```

### Obsługiwane komendy

| Komenda głosowa | Akcja | Przykład odpowiedzi |
|-----------------|-------|---------------------|
| "która jest godzina" | Podaje aktualną godzinę | "Jest 14:35" |
| "powtórz [tekst]" | Powtarza usłyszany tekst | "Powtarzam: dzień dobry" |
| "echo [tekst]" | Powtarza usłyszany tekst | "Powtarzam: test mikrofonu" |
| "stop" / "koniec" / "zakończ" | Kończy pętlę | "Kończę pętlę nasłuchu." |
| (inne) | Domyślna odpowiedź | "Usłyszałem: [tekst]" |

### Przepływ danych

```
PĘTLA NIESKOŃCZONA:
  1. Mikrofon → arecord (3s) → /tmp/in.wav
  2. /tmp/in.wav → POST /api/asr → tekst rozpoznany
  3. Analiza tekstu (normalizacja lowercase, grep pattern matching)
  4. Wybór akcji na podstawie wykrytej komendy
  5. Generowanie odpowiedzi (funkcja say_wav)
  6. POST /api/tts → /tmp/out.wav → aplay
  7. Powrót do kroku 1 (lub wyjście przy "stop")
```

### Konfiguracja

**Hardcoded:**
- Urządzenie ALSA: `plughw:0,0`
- Format audio: S16_LE, 16000 Hz, mono
- Długość nagrania: 3 sekundy (fixed)
- Głos Piper: `pl_PL-gosia-medium.onnx`

### Wymagania

Identyczne jak dla `talk_local.sh`:
- Uruchomiona usługa `rider-voice-web.service` (port 8092)
- Mikrofon i głośnik w ALSA
- Narzędzia: `arecord`, `aplay`, `curl`, `jq`

### Przykład sesji

```bash
$ ./scripts/talk_assistant.sh
[REC] Mów (3 s)…
[ASR] >> która jest godzina
Playing WAVE '/tmp/out.wav' : ...  # "Jest 14:37"

[REC] Mów (3 s)…
[ASR] >> powtórz dzień dobry
Playing WAVE '/tmp/out.wav' : ...  # "Powtarzam: dzień dobry"

[REC] Mów (3 s)…
[ASR] >> stop
Playing WAVE '/tmp/out.wav' : ...  # "Kończę pętlę nasłuchu."
$
```

### Rozszerzanie funkcjonalności

Dodaj własne komendy edytując sekcję `if/elif` w skrypcie (linie 25-36):

```bash
elif echo "$L" | grep -qE 'pogoda'; then
  say_wav "Sprawdzam pogodę... Dziś słonecznie, 18 stopni."
elif echo "$L" | grep -qE 'muzyka|graj'; then
  say_wav "Włączam muzykę."
  # mpg123 /home/pi/music/song.mp3 &
```

### Troubleshooting

Patrz sekcja Troubleshooting w `talk_local.sh` — identyczne problemy i rozwiązania.

### Zobacz także

- [talk_local.sh](#talk_localsh) — prostszy wariant (jednorazowe echo)
- [docs/modules/voice.md](../modules/voice.md) — pełna dokumentacja API
- [docs/config/voice.md](../config/voice.md) — konfiguracja lokalnych backendów
- [systemd/rider-voice-web.service](../systemd/rider-voice-web.service) — definicja usługi

---

**Ostatnia aktualizacja:** 2025-10-24  
**Dodano:** Dokumentacja skryptów `talk_local.sh` i `talk_assistant.sh`
