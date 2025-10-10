# Dokumentacja konfiguracji (`config/*`)

> Indeks parametrów konfiguracji dla wszystkich modułów Rider-Pi

## Spis dokumentów

### Konfiguracja aplikacji

- [**voice.md**](voice.md) — parametry voice (ASR, TTS, Chat) — `voice_file.toml`, `voice_streaming.toml`
- [**validation.md**](validation.md) — **NEW**: walidacja konfiguracji, schema enforcement, fail-fast/lenient modes
- [**face.md**](face.md) — parametry renderingu buźki — `face.toml`
- [**alsa.md**](alsa.md) — konfiguracja ALSA (asoundrc, wm8960)

## Pliki konfiguracyjne

### Katalog `config/`

```
config/
├── voice_file.toml          # Voice: tryb plikowy (REST ASR/TTS)
├── voice_streaming.toml     # Voice: tryb strumieniowy (Realtime WebSocket)
├── face.toml                # Renderowanie buźki (parametry geometrii, emocje)
├── alsa/                    # Konfiguracja ALSA
│   ├── asoundrc.wm8960      # Szablon asoundrc dla WM8960
│   ├── wm8960-apply.sh      # Skrypt konfiguracji miksera
│   └── preflight.sh         # Pre-flight checks audio
└── local/                   # Lokalne nadpisania (git-ignored)
    └── secrets.env          # Lokalne sekrety
```

## Hierarchia konfiguracji

### Precedencja (dla aplikacji voice)

1. **CLI args** (najwyższy priorytet)
2. **Zmienne środowiskowe** (ENV)
3. **Plik TOML** (wskazany przez `--config` lub `VOICE_CONFIG`)
4. **Domyślny TOML** (`config/voice_file.toml` lub `voice_streaming.toml`)
5. **Hardcoded defaults** (najniższy priorytet)

### Przykład

```bash
# 1. Załaduj z TOML
python -m apps.voice.cli listen --config config/voice_file.toml

# 2. Nadpisz przez ENV
export VOICE_ASR_BACKEND=vosk
python -m apps.voice.cli listen --config config/voice_file.toml

# 3. Nadpisz przez CLI (najwyższy priorytet)
python -m apps.voice.cli listen --config config/voice_file.toml --asr backend=whisper
```

## Polityka sekretów

### ✅ Zalecane metody

#### Metoda 1: Zmienna środowiskowa

```bash
export OPENAI_API_KEY=sk-...
python -m apps.voice.cli listen
```

#### Metoda 2: Plik z kluczem

```bash
# ~/.bash_profile
export OPENAI_API_KEY=sk-...
```

```bash
source ~/.bash_profile
python -m apps.voice.cli listen
```

#### Metoda 3: W TOML (tylko dla testów)

```toml
[stream]
auth = "env:OPENAI_API_KEY"  # ✅ Dobre (czyta z ENV)
# auth = "sk-..."            # ❌ ZŁE (hardcoded w repo)
```

### ❌ Niebezpieczne praktyki

- **NIE** commituj kluczy API do repo
- **NIE** trzymaj sekretów w `config/*.toml` (chyba że w `config/local/` — git-ignored)
- **NIE** loguj kluczy API do stdout/plików

Zobacz: [docs/CONFIG_POLICY.md](../CONFIG_POLICY.md)

## Konfiguracja lokalna (development)

### Struktura `config/local/`

```bash
# Katalog git-ignored dla lokalnych overrides
mkdir -p config/local

# Przykład: konfiguracja dev
cp config/voice_file.toml config/local/voice_dev.toml
# edytuj: zmień backendy, modele, urządzenia

# Użyj w aplikacji
export VOICE_CONFIG=config/local/voice_dev.toml
python -m apps.voice.cli listen
```

## Szybki start

### Konfiguracja voice (plikowy)

```bash
# 1. Skopiuj sample
cp config/voice_file.toml config/local/voice.toml

# 2. Edytuj urządzenia ALSA
nano config/local/voice.toml
# capture.device = "wm8960_in"
# playback.device = "wm8960_out"

# 3. Ustaw klucz API
export OPENAI_API_KEY=sk-...

# 4. Uruchom
python -m apps.voice.cli ptt --config config/local/voice.toml
```

### Konfiguracja face

```bash
# 1. Skopiuj sample (jeśli nie ma)
cp config/face.toml config/local/face.toml

# 2. Edytuj parametry
nano config/local/face.toml
# mouth_happy_lift_k = 0.050  # większy uśmiech
# brow_y_k = 0.25             # wyższe brwi

# 3. Użyj (przez ENV lub bezpośrednio w kodzie)
export FACE_CONFIG=config/local/face.toml
python -m apps.ui.face
```

## Walidacja konfiguracji

### Voice

```bash
# Diagnostyka konfiguracji
python -m apps.voice.cli diag --config config/voice_file.toml

# Sprawdź załadowane parametry
python -m apps.voice.cli listen --config config/voice_file.toml --dry-run
```

### Face

```bash
# Test renderingu z parametrami
python -c "
import tomli
with open('config/face.toml', 'rb') as f:
    cfg = tomli.load(f)
print(cfg)
"
```

## Migracja z poprzednich wersji

### Z ENV do TOML

**Stary sposób:**
```bash
export VAD_MODE=3
export HOTWORD_THRESHOLD=0.65
./ops/voice-run.sh
```

**Nowy sposób:**
```toml
# config/local/voice.toml
[asr.vad]
aggressiveness = 3

[hotword]
threshold = 0.65
```

```bash
python -m apps.voice.cli listen --config config/local/voice.toml
```

### Z YAML do TOML

⚠️ **Wymaga weryfikacji:** Jeśli istnieją stare pliki YAML.

Narzędzie do konwersji:
```bash
# (jeśli planowane)
python tools/yaml_to_toml.py config/legacy/voice.yaml > config/voice.toml
```

## FAQ

**Q: Gdzie mogę nadpisać konfigurację lokalnie?**  
A: Użyj `config/local/` (git-ignored) lub zmiennych ENV.

**Q: Czy mogę mieć wiele plików voice.toml?**  
A: Tak, użyj `--config` lub `VOICE_CONFIG`.

**Q: Jak przetestować bez klucza API?**  
A: Użyj trybu PTT z lokalnym ASR (Vosk) i TTS (Piper).

**Q: Co jeśli potrzebuję różnych kluczy dla różnych środowisk?**  
A: Użyj osobnych plików w `config/local/`:
```bash
# Development
export VOICE_CONFIG=config/local/voice_dev.toml
export OPENAI_API_KEY=sk-dev-...

# Production
export VOICE_CONFIG=config/local/voice_prod.toml
export OPENAI_API_KEY=sk-prod-...
```

---

**Related docs:**
- [CONFIG_POLICY.md](../CONFIG_POLICY.md) — pełna polityka konfiguracji
- [docs/apps/](../apps/) — moduły aplikacyjne
- [docs/ops/](../ops/) — skrypty operacyjne

**Ostatnia aktualizacja:** 2025-01
