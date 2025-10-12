# Polityka konfiguracji Rider-Pi

> **Zasada nadrzędna:** *Jedno miejsce prawdy dla konfiguracji oprogramowania i sprzętu → `config/`*

## 1. Źródło konfiguracji

### Hierarchia katalogów

Wszystkie pliki konfiguracyjne rezydują w `config/` lub jego podkatalogach:

```
config/
├── voice_openai_file.toml          # Konfiguracja voice (tryb plikowy)
├── voice_openai_streaming.toml     # Konfiguracja voice (tryb strumieniowy)
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
# config/voice_openai_streaming.toml
[stream]
auth = "env:OPENAI_API_KEY"
```

**Skrypty automatycznie ładują profil:**
```bash
# scripts/sys_voice-run.sh już robi:
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
# config/voice_openai_streaming.toml
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

### Źródło prawdy: `config/alsa/asoundrc.wm8960`

Konfiguracja ALSA dla WM8960 jest **szablonem** w repo:
```bash
cp config/alsa/asoundrc.wm8960 ~/.asoundrc
```

**Struktura aliasów:**
- `wm8960_in` — capture (dsnoop, 16kHz mono)
- `wm8960_out` — playback (dmix, 48kHz stereo)
- `wm8960` — control interface

### Pre-flight checks (nowe w PR-3)

Przed uruchomieniem aplikacji audio, należy sprawdzić dostępność urządzeń:

```bash
# Sprawdzenie bez zabijania procesów
config/alsa/preflight.sh --capture wm8960_in --playback wm8960_out

# Sprawdzenie z wymuszonym czyszczeniem
config/alsa/preflight.sh --force --capture wm8960_in --playback wm8960_out
```

**Zachowanie skryptu pre-flight:**

1. **Sprawdzenie urządzenia** — próba otwarcia dla test capture/playback (0.1s)
2. **Wykrycie procesów** — użycie `lsof /dev/snd/*` (pomijane w CI/testach)
3. **Bezpieczne zabijanie** (tylko z `--force` i tylko znane procesy):
   - Wysyła `SIGTERM` do `arecord`, `aplay`, `python.*voice`
   - Czeka do 1s na graceful shutdown
   - Jeśli proces nadal istnieje, wysyła `SIGKILL`
   - Loguje wszystkie akcje z PID i nazwą komendy
4. **Ponowne sprawdzenie** — po czyszczeniu ponownie testuje urządzenia
5. **Raport** — zwraca exit code 0 jeśli OK, 1 jeśli błąd

**Integracja w skryptach:**
```bash
# W scripts/sys_voice-once.sh:
"$RIDER_CONFIG_DIR/config/alsa/preflight.sh" \
  --force \
  --capture wm8960_in \
  --playback wm8960_out || {
  echo "WARNING: Pre-flight failed, continuing anyway" >&2
}
```

**Bezpieczeństwo:**
- NIE zabija procesów systemowych
- Wymaga jawnego `--force` do zabicia czegokolwiek
- Loguje wszystkie PID i komendy przed zabiciem
- Używa SIGTERM przed SIGKILL
- Pomija `lsof` w środowiskach testowych (ENV: `ALSA_SKIP_LSOF=1`)

### Skrypty operacyjne

Skrypty w `scripts/` **czytają** konfigurację z `config/`, nie **tworzą** jej:
```bash
# scripts/sys_voice-run.sh eksportuje ENV z domyślnymi wartościami,
# ale można je nadpisać:
ALSA_DEVICE=wm8960_in scripts/sys_voice-run.sh
```

### Pre-flight checks (planowane w PR-3)

Przed uruchomieniem audio:
1. Sprawdź dostępność urządzeń (`fuser`, `lsof`)
2. Zidentyfikuj blokujące procesy
3. Bezpieczne zamknięcie (SIGTERM → czekaj → SIGKILL jeśli trzeba)
4. Logowanie wszystkich akcji

---

## 4. Standardy skryptów ops

### Helper dla skryptów: `scripts/util_load-config.sh`

Zamiast duplikować logikę wykrywania ścieżek i ładowania konfiguracji, skrypty mogą użyć:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Załaduj pomocnicze funkcje
source "$(dirname "$0")/../scripts/util_load-config.sh"

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
source scripts/util_load-config.sh && exec_with_config python -m apps.voice.cli ptt
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

**Q: Czy skrypty operacyjne nadpisują konfigurację?**
A: Nie. Skrypty w `scripts/` **czytają** z `config/` i **uzupełniają** brakujące ENV, ale nie nadpisują istniejących wartości.

---

**Ostatnia aktualizacja:** 2025-01 (PR-1)
**Kontakt:** Issues w repozytorium GitHub

---

## 8. Podsumowanie zmian (seria PR-ów config unification)

### PR-1: Usunięcie bashenv (SECURITY CRITICAL) ✅
- Usunięto schemat `bashenv:` z `svc_stream.py` (ryzyko odczytu z `.bash_history`)
- Migracja: `bashenv:~/.bash_profile:VAR` → `env:VAR`
- Utworzono `docs/CONFIG_POLICY.md`

### PR-2: Centralizacja dostępu do konfiguracji ✅
- Utworzono `scripts/util_load-config.sh` (helper dla skryptów)
- Zaktualizowano `scripts/sys_voice-once.sh` (nowoczesny wzorzec)
- Oznaczono `scripts/sys_voice-run.sh` jako LEGACY

### PR-3: Pre-flight checks ALSA ✅
- Utworzono `config/alsa/preflight.sh` (bezpieczne zabijanie procesów)
- Reorganizacja: `config/alsa/` dla ALSA-specyficznych plików
- Przeniesiono `asoundrc.wm8960` i `wm8960-apply.sh`

---

## 9. Checklist dla nowych deweloperów

**Setup środowiska:**
```bash
# 1. Clone i install
git clone https://github.com/mpieniak01/Rider-Pi.git
cd Rider-Pi
pip install -r requirements-dev.txt

# 2. ALSA config
cp config/alsa/asoundrc.wm8960 ~/.asoundrc

# 3. API key
echo 'export OPENAI_API_KEY="sk-..."' >> ~/.bash_profile
source ~/.bash_profile

# 4. Pre-flight check
config/alsa/preflight.sh --capture wm8960_in --playback wm8960_out

# 5. Test
python -m apps.voice.cli diag
```

**Tworzenie nowego skryptu ops:**
```bash
#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../scripts/util_load-config.sh"
setup_voice_env
# Twój kod tutaj
```

**Przed commitem:**
```bash
ruff check apps/ tests/ --fix
ruff format apps/ tests/
pytest -q
git diff --cached | grep -i "sk-"  # sprawdź sekrety
```

---

**Ostatnia aktualizacja:** 2025-01 (PR-3 complete)  
**Wersja:** 1.0  
**Related docs:** [voice.md](modules/voice.md), [wm8960.md](audio/wm8960.md), [AGENT.md](../AGENT.md)
