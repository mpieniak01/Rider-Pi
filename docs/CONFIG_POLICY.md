# Polityka konfiguracji Rider-Pi

> **Zasada nadrzędna:** *Jedno miejsce prawdy dla konfiguracji oprogramowania i sprzętu → `config/`*

## 1. Źródło konfiguracji

### Hierarchia katalogów

Wszystkie pliki konfiguracyjne rezydują w `config/` lub jego podkatalogach:

```
config/
├── voice_file.toml          # Konfiguracja voice (tryb plikowy)
├── voice_streaming.toml     # Konfiguracja voice (tryb strumieniowy)
├── face.toml                # Konfiguracja renderingu twarzy
├── asoundrc.wm8960          # Szablon ALSA dla WM8960
├── wm8960-apply.sh          # Skrypt konfiguracji miksera WM8960
└── local/                   # Lokalne nadpisania (git-ignored)
    └── secrets.env          # Lokalne sekrety (nie w repo)
```

### Precedencja konfiguracji (dla aplikacji voice)

1. **Domyślne wartości** — wbudowane w kod (`apps/voice/config.py`)
2. **Plik TOML** — w kolejności:
   - `$VOICE_CONFIG` (jeśli ustawione)
   - `$RIDER_CONFIG_DIR/voice.toml`
   - `./config/voice.toml` (preferowane)
   - `./configs/voice.yaml` (legacy, deprecated)
3. **Zmienne środowiskowe** — prefiks `VOICE_*`
4. **CLI overrides** — argumenty linii poleceń

**Przykład:**
```bash
# Domyślnie używa config/voice.toml
python -m apps.voice.cli listen

# Override konkretnych ustawień przez CLI
python -m apps.voice.cli listen --asr backend=vosk --tts voice=pl

# Override przez ENV
export VOICE_ASR_BACKEND=vosk
python -m apps.voice.cli listen
```

---

## 2. Polityka sekretów (API keys)

### ⚠️ Zabronione metody

**NIE używaj:**
- `~/.bash_history` — historia poleceń może zawierać sekrety przez przypadek
- Automatyczne nadpisywanie `~/.bash_profile` przez skrypty
- Commitowanie sekretów do repo
- Przekazywanie sekretów przez argumenty CLI (widoczne w `ps`)

### ✅ Zalecane metody

#### Metoda 1: Zmienna środowiskowa (najlepsze dla automatyzacji)

**Dla użytkownika:**
```bash
# W ~/.bash_profile lub ~/.profile
export OPENAI_API_KEY="sk-..."

# Zreładuj profil
source ~/.bash_profile
```

**W aplikacji:**
```toml
# config/voice_streaming.toml
[stream]
auth = "env:OPENAI_API_KEY"
```

**Skrypty automatycznie ładują profil:**
```bash
# ops/voice-run.sh już robi:
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  OPENAI_API_KEY="$(bash -lc 'source ~/.bash_profile >/dev/null 2>&1; printf "%s" "$OPENAI_API_KEY"')"
  export OPENAI_API_KEY
fi
```

#### Metoda 2: Plik z kluczem (najlepsze dla development)

**Utwórz plik sekretów:**
```bash
# Utwórz katalog dla lokalnych sekretów
mkdir -p config/local

# Dodaj klucz do pliku (git-ignored)
echo "sk-..." > config/local/openai.key
chmod 600 config/local/openai.key
```

**W aplikacji:**
```toml
# config/voice_streaming.toml
[stream]
auth = "file:config/local/openai.key"
```

#### Metoda 3: Literal w configu (tylko dla testów)

```toml
# config/local/voice_test.toml (git-ignored)
[stream]
auth = "sk-test-key-not-for-production"
```

**UWAGA:** Nigdy nie commituj tego do repo!

### Zmiana z bashenv (deprecated)

**Stara konfiguracja (USUNIĘTA):**
```toml
# ❌ NIE DZIAŁA OD WERSJI X.Y.Z
[stream]
auth = "bashenv:~/.bash_profile:OPENAI_API_KEY"
```

**Nowa konfiguracja:**
```toml
# ✅ UŻYJ TEGO
[stream]
auth = "env:OPENAI_API_KEY"
```

**Powód usunięcia:** Schemat `bashenv:` mógł odczytywać zmienne z `~/.bash_history`, co stanowiło ryzyko bezpieczeństwa.

---

## 3. Konfiguracja sprzętu (ALSA)

### Źródło prawdy: `config/asoundrc.wm8960`

Konfiguracja ALSA dla WM8960 jest **szablonem** w repo:
```bash
cp config/asoundrc.wm8960 ~/.asoundrc
```

**Struktura aliasów:**
- `wm8960_in` — capture (dsnoop, 16kHz mono)
- `wm8960_out` — playback (dmix, 48kHz stereo)
- `wm8960` — control interface

### Skrypty operacyjne

Skrypty w `ops/` **czytają** konfigurację z `config/`, nie **tworzą** jej:
```bash
# ops/voice-run.sh eksportuje ENV z domyślnymi wartościami,
# ale można je nadpisać:
ALSA_DEVICE=wm8960_in ops/voice-run.sh
```

### Pre-flight checks (planowane w PR-3)

Przed uruchomieniem audio:
1. Sprawdź dostępność urządzeń (`fuser`, `lsof`)
2. Zidentyfikuj blokujące procesy
3. Bezpieczne zamknięcie (SIGTERM → czekaj → SIGKILL jeśli trzeba)
4. Logowanie wszystkich akcji

---

## 4. Standardy skryptów ops

### Helper dla skryptów: `tools/load_config.sh`

Zamiast duplikować logikę wykrywania ścieżek i ładowania konfiguracji, skrypty mogą użyć:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Załaduj pomocnicze funkcje
source "$(dirname "$0")/../tools/load_config.sh"

# Skonfiguruj środowisko automatycznie
setup_voice_env

# Uruchom aplikację (RIDER_CONFIG_DIR i API key już ustawione)
python -m apps.voice.cli listen
```

**Dostępne funkcje:**

- `get_rider_root` — wykryj katalog główny projektu
- `get_config_dir` — zwróć katalog config (respektuje `RIDER_CONFIG_DIR`)
- `load_api_key [VARNAME]` — załaduj klucz API z `~/.bash_profile`
- `setup_voice_env` — skonfiguruj pełne środowisko (locale, PYTHONPATH, API key)
- `exec_with_config CMD...` — setup + exec w jednej linii

**Przykład użycia w jednej linii:**
```bash
source tools/load_config.sh && exec_with_config python -m apps.voice.cli ptt
```

### Nagłówek skryptu
```bash
#!/usr/bin/env bash
# nazwa-skryptu.sh — krótki opis
# Użycie:
#   ./nazwa-skryptu.sh [argumenty]

set -euo pipefail  # fail fast
```

### Ścieżki
```bash
# ❌ Nie hardcoduj
ROBOT_ROOT="/home/pi/robot"

# ✅ Użyj zmiennej lub wykryj automatycznie
ROBOT_ROOT="${RIDER_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
```

### Logowanie
```bash
# Standardowy prefix
echo "[script-name] Starting..." >&2
echo "[script-name] Config loaded from: $CONFIG_FILE" >&2

# Błędy
echo "[script-name] ERROR: Device not found" >&2
exit 1
```

### Idempotencja
```bash
# Skrypt można uruchomić wielokrotnie bezpiecznie
if [[ -f ~/.asoundrc ]]; then
  echo "[alsa-setup] ~/.asoundrc already exists, skipping" >&2
  exit 0
fi

cp config/asoundrc.wm8960 ~/.asoundrc
```

---

## 5. Migracja z poprzednich wersji

### Jeśli używałeś `bashenv:`

**Przed (przestarzałe):**
```toml
[stream]
auth = "bashenv:~/.bash_profile:OPENAI_API_KEY"
```

**Po (aktualne):**
```toml
[stream]
auth = "env:OPENAI_API_KEY"
```

**Upewnij się, że zmienna jest eksportowana:**
```bash
# ~/.bash_profile lub ~/.profile
export OPENAI_API_KEY="sk-..."

# Sprawdź
echo $OPENAI_API_KEY
```

### Jeśli masz konfigurację w wielu miejscach

**Skonsoliduj do `config/`:**
```bash
# Przenieś konfigurację do standardowej lokalizacji
mv ~/robot/configs/voice.yaml config/local/voice_legacy.yaml

# Użyj TOML zamiast YAML
python -m apps.voice.cli diag --config config/local/voice_legacy.yaml
# (sprawdź co działa, potem przenieś ustawienia do config/voice.toml)
```

---

## 6. CI i walidacja

### Sprawdzanie przed commitem

```bash
# Sprawdź format
ruff check apps/ tests/ --fix
ruff format apps/ tests/

# Sprawdź czy nie ma sekretów
git diff --cached | grep -i "sk-" && echo "WARNING: Possible secret in commit"

# Waliduj TOML
python -c "import tomllib; tomllib.load(open('config/voice.toml', 'rb'))"
```

### CI checks (PR-6)

- Brak `bashenv` w kodzie
- Brak hardcoded `/home/pi/robot`
- Wszystkie `.toml` są poprawne składniowo
- Brak sekretów w commitach

---

## 7. FAQ

**Q: Gdzie mogę nadpisać konfigurację lokalnie?**
A: Użyj `config/local/` (git-ignored) lub zmiennych ENV.

**Q: Czy mogę mieć wiele plików voice.toml?**
A: Tak, użyj `--config` lub `VOICE_CONFIG`:
```bash
python -m apps.voice.cli listen --config config/local/voice_dev.toml
```

**Q: Jak przetestować bez klucza API?**
A: Użyj trybu PTT z lokalnym ASR (Vosk) i TTS (Piper):
```bash
python -m apps.voice.cli ptt --asr backend=vosk --tts backend=piper
```

**Q: Co jeśli potrzebuję różnych kluczy dla różnych środowisk?**
A: Użyj osobnych plików w `config/local/`:
```bash
# Development
export VOICE_CONFIG=config/local/voice_dev.toml

# Production
export VOICE_CONFIG=config/local/voice_prod.toml
```

**Q: Czy skrypty w `ops/` nadpisują konfigurację?**
A: Nie. Skrypty **czytają** z `config/` i **uzupełniają** brakujące ENV, ale nie nadpisują istniejących wartości.

---

**Ostatnia aktualizacja:** 2025-01 (PR-1)
**Kontakt:** Issues w repozytorium GitHub
