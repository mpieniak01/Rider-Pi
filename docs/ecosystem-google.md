# Google Gemini Voice Ecosystem

## Przegląd

Rider-Pi oferuje pełne wsparcie dla ekosystemu Google Gemini jako alternatywy dla OpenAI. System pozwala na używanie usług Google dla rozpoznawania mowy (ASR) i konwersacji (Chat), przy zachowaniu pełnej kompatybilności z istniejącymi funkcjami.

## Obecny Stan Wsparcia

### ✅ W Pełni Wspierane

- **ASR (Speech-to-Text)**: Google Gemini z modelami multimodalnymi (np. `gemini-1.5-flash`)
- **Chat**: Google Gemini z modelami konwersacyjnymi (np. `gemini-2.0-flash-exp`, `gemini-pro`)
- **Streaming Chat**: Asynchroniczne streamowanie odpowiedzi z Gemini

### ⚠️ Ograniczenia

- **TTS (Text-to-Speech)**: Gemini API obecnie **nie wspiera** TTS
  - Rekomendacja: Używaj OpenAI jako backend dla TTS
  - Status będzie aktualizowany gdy Google doda wsparcie TTS do Gemini API

## Konfiguracja

### 1. Instalacja Zależności

```bash
pip install google-generativeai>=0.8.0
```

Biblioteka `google-generativeai` jest jedyną wymaganą zależnością dla ekosystemu Google.

### 2. Klucz API

Uzyskaj klucz API Google Gemini:
1. Odwiedź [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Utwórz nowy klucz API
3. Ustaw zmienną środowiskową:

```bash
export GOOGLE_API_KEY="twoj-klucz-api"
```

**Uwaga**: NIE jest potrzebne uwierzytelnianie przez konto usługi (`GOOGLE_APPLICATION_CREDENTIALS`). Wystarczy klucz API.

### 3. Konfiguracja TOML

Użyj dedykowanego pliku konfiguracyjnego `voice_gemini_file.toml`:

```toml
# ASR - Google Gemini
[asr]
backend  = "google"
model    = "gemini-1.5-flash"
language = "pl"

# Chat - Google Gemini
[chat]
backend       = "google"
model         = "gemini-2.0-flash-exp"
system_prompt = "Jesteś asystentem głosowym. Odpowiadaj krótko."

# TTS - OpenAI (fallback, Gemini nie wspiera TTS)
[tts]
backend = "openai"
format  = "mp3"
voice   = "ash"
```

## Użycie

### Tryb Plikowy (PTT - Push-to-Talk)

```bash
# Użyj konfiguracji Gemini
python -m apps.voice.cli --config ./config/voice_gemini_file.toml ptt
```

Lub z Makefile:

```bash
# Domyślnie używa OpenAI
make voice-file-ptt

# Dla Gemini, użyj bezpośrednio CLI:
python -m apps.voice.cli --config ./config/voice_gemini_file.toml ptt
```

### Tryb Strumieniowy

```bash
python -m apps.voice.cli --config ./config/voice_gemini_file.toml listen
```

## Modele

### ASR (Rozpoznawanie Mowy)

- `gemini-1.5-flash` (zalecany) - szybki, wydajny model multimodalny
- `gemini-1.5-pro` - bardziej zaawansowany, wolniejszy

**Jak to działa**: Gemini przyjmuje audio jako część multimodalnego contentu i transkrybuje je na tekst.

### Chat (Konwersacja)

- `gemini-2.0-flash-exp` (najnowszy) - eksperymentalny, najszybszy
- `gemini-pro` (stabilny) - sprawdzony model produkcyjny
- `gemini-1.5-flash` - dobra równowaga szybkości i jakości

## Przełączanie między Ekosystemami

### Z OpenAI na Google Gemini

1. Skopiuj/edytuj plik konfiguracyjny:
```bash
cp config/voice_openai_file.toml config/my_gemini_config.toml
```

2. Zmień backendy w pliku:
```toml
[asr]
backend = "google"  # było: "openai"
model = "gemini-1.5-flash"  # było: "whisper-1"

[chat]
backend = "google"  # było: "openai"
model = "gemini-2.0-flash-exp"  # było: "gpt-4o-mini"
```

3. Uruchom z nową konfiguracją:
```bash
python -m apps.voice.cli --config ./config/my_gemini_config.toml ptt
```

### Z Google Gemini na OpenAI

Analogicznie, zmień `backend = "openai"` i odpowiednie modele.

## Zmienne Środowiskowe

| Zmienna | Wymagane dla | Opis |
|---------|--------------|------|
| `GOOGLE_API_KEY` | Google Gemini (ASR, Chat) | Klucz API z Google AI Studio |
| `OPENAI_API_KEY` | OpenAI (TTS fallback) | Klucz API OpenAI |

## Architektura

```
┌─────────────────────────────────────────────────────────────┐
│                     Rider-Pi Voice Pipeline                  │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Mikrofon → ASR (Gemini) → Chat (Gemini) → TTS (OpenAI)     │
│              ↓                 ↓               ↓             │
│           Text             Response          Audio           │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## Porównanie: OpenAI vs Google Gemini

| Funkcja | OpenAI | Google Gemini |
|---------|--------|---------------|
| ASR | ✅ Whisper (bardzo dobry) | ✅ Multimodal (dobry) |
| Chat | ✅ GPT-4o (doskonały) | ✅ Gemini 2.0 (doskonały) |
| TTS | ✅ Pełne wsparcie | ❌ Brak wsparcia |
| Streaming Chat | ✅ | ✅ |
| Koszty | $$$ | $$ (tańszy) |
| Latencja | Bardzo niska | Niska |

## Rozwiązywanie Problemów

### Błąd: "GOOGLE_API_KEY not configured"

**Rozwiązanie**: Ustaw zmienną środowiskową:
```bash
export GOOGLE_API_KEY="twoj-klucz"
```

### Błąd: "Google Generative AI SDK unavailable"

**Rozwiązanie**: Zainstaluj bibliotekę:
```bash
pip install google-generativeai>=0.8.0
```

### Błąd: "Gemini TTS is not yet supported"

**Rozwiązanie**: To oczekiwane. Użyj OpenAI dla TTS:
```toml
[tts]
backend = "openai"
```

### Niska jakość transkrypcji

**Rozwiązanie**: 
1. Sprawdź jakość audio (poziom szumu)
2. Spróbuj modelu `gemini-1.5-pro` zamiast `gemini-1.5-flash`
3. Ustaw konkretny język w konfiguracji: `language = "pl"`

## Testowanie

### Testy Jednostkowe

```bash
# Wszystkie testy Gemini
pytest tests/test_gemini_asr_tts.py -v

# Tylko ASR
pytest tests/test_gemini_asr_tts.py::TestGeminiASR -v

# Tylko Chat
pytest tests/test_chat_gemini.py -v
```

### Test Manualny

```bash
# 1. Ustaw klucz API
export GOOGLE_API_KEY="twoj-klucz"

# 2. Uruchom PTT
python -m apps.voice.cli --config ./config/voice_gemini_file.toml ptt

# 3. Naciśnij Enter, powiedz coś, naciśnij ponownie Enter
# 4. Sprawdź transkrypcję i odpowiedź
```

## Roadmap

- [x] ✅ Wsparcie dla Gemini Chat (REST)
- [x] ✅ Wsparcie dla Gemini Chat (Streaming)
- [x] ✅ Wsparcie dla Gemini ASR (Multimodal)
- [ ] ⏳ Wsparcie dla Gemini TTS (oczekujemy na API)
- [ ] 🔜 Optymalizacja latencji dla ASR
- [ ] 🔜 Wsparcie dla innych języków w ASR

## Referencje

- [Google Gemini API Documentation](https://ai.google.dev/docs)
- [google-generativeai Python SDK](https://github.com/google/generative-ai-python)
- [Multimodal Capabilities](https://ai.google.dev/docs/multimodal_concepts)

## Wsparcie

W przypadku problemów:
1. Sprawdź logi: `tail -f /tmp/voice-recs/*.log`
2. Sprawdź issue na GitHub
3. Upewnij się, że używasz najnowszej wersji `google-generativeai`

## Licencja

Zgodna z główną licencją projektu Rider-Pi.
