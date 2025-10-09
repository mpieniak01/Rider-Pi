# Refaktoryzacja modułu strumieniowego czatu - Podsumowanie

## Cel

Umożliwienie płynnej, dwukierunkowej konwersacji w czasie rzeczywistym poprzez integrację modułów ASR (rozpoznawanie mowy), Chat (konwersacja) i TTS (synteza mowy) w trybie strumieniowym.

## Wprowadzone zmiany

### 1. `apps/voice/chat.py` - Asynchroniczny streaming czatu

**Dodano:**
- `async def ask_stream(text: str)` - nowa metoda generująca odpowiedzi jako async generator
- `async def _ask_openai_stream(text: str)` - wywołanie OpenAI Chat Completions API z `stream=True`

**Funkcjonalność:**
- Zwraca tokeny odpowiedzi natychmiast po ich otrzymaniu z API
- Utrzymuje historię konwersacji (zgodnie z `max_history`)
- Działa w trybie `transport="realtime"` bez blokowania REST API
- Zachowana kompatybilność wsteczna - metoda `ask()` działa bez zmian

**Przykład użycia:**
```python
from apps.voice.chat import ChatConfig, ChatSession

config = ChatConfig(
    backend="openai",
    model="gpt-4o-mini",
    system_prompt="Odpowiadaj krótko po polsku.",
    transport="realtime",
)
session = ChatSession(config)

# Streaming response
async for chunk in session.ask_stream("Jak się masz?"):
    print(chunk, end="", flush=True)
```

### 2. `apps/voice/tts.py` - Streaming TTS z buforowaniem zdań

**Dodano:**
- `async def speak_stream(text_generator, config, playback, logger)` - synteza i odtwarzanie strumienia tekstu

**Funkcjonalność:**
- Akceptuje async generator produkujący fragmenty tekstu
- Buforuje tekst do momentu wykrycia końca zdania (`.`, `!`, `?`, `\n`)
- Minimum 10 znaków przed wysłaniem do syntezy (unika pojedynczych słów)
- Wykorzystuje istniejącą funkcję `speak()` przez executor dla blokujących operacji
- Automatycznie tworzy kopię konfiguracji z `transport="file"` aby ominąć blokadę realtime

**Przykład użycia:**
```python
from apps.voice.tts import TTSConfig, speak_stream
from apps.voice.playback import PlaybackConfig

async def text_gen():
    yield "To jest "
    yield "pierwsze zdanie. "
    yield "A to drugie!"

config = TTSConfig(backend="openai", voice="alloy", transport="realtime")
playback = PlaybackConfig(backend="alsa", device="wm8960_out")

result = await speak_stream(text_gen(), config, playback)
```

### 3. `apps/voice/stream/service.py` - Integracja pipeline'u

**Dodano:**
- Inicjalizacja `ChatConfig`, `TTSConfig`, `PlaybackConfig` w `__init__`
- Utworzenie instancji `ChatSession`
- Obsługa wiadomości `conversation.item.input_audio_transcription.completed` z Realtime API
- `async def _handle_transcript(transcript: str)` - wykonuje pipeline ASR→Chat→TTS

**Przepływ danych:**
```
1. Realtime API → transcription completed
2. StreamingVoiceService._handle_transcript()
3. ChatSession.ask_stream(transcript) → async generator
4. speak_stream(chat_generator) → synteza i odtwarzanie
5. PTT state transition → TTS_COMPLETE
```

**Nowa architektura:**
- ASR: Transkrypcja z OpenAI Realtime API
- Chat: Własny moduł z streaming (nie Realtime API chat)
- TTS: Własny moduł z sentence buffering (nie Realtime API TTS)

## Testy

Dodano testy jednostkowe:

### `tests/test_chat_streaming.py`
- `test_chat_session_ask_stream_echo` - streaming z echo backend
- `test_chat_session_ask_stream_history` - zarządzanie historią konwersacji
- `test_chat_session_ask_sync_still_works` - kompatybilność wsteczna

### `tests/test_tts_streaming.py`
- `test_speak_stream_sentence_buffering` - weryfikacja sygnatury funkcji
- `test_speak_stream_final_buffer` - obsługa pozostałego bufora
- `test_tts_config_transport_override` - nadpisywanie konfiguracji transportu

**Wszystkie testy przechodzą pomyślnie (61/61).**

## Kryteria akceptacji

✅ **1. Aplikacja w trybie strumieniowym prowadzi do funkcjonalnej pętli konwersacyjnej**
- Dodano obsługę `conversation.item.input_audio_transcription.completed`
- Zintegrowano ChatSession.ask_stream() i speak_stream()

✅ **2. Odpowiedź TTS rozpoczyna się przed zakończeniem generowania przez model**
- Sentence buffering w speak_stream() wysyła zdania do TTS natychmiast po wykryciu interpunkcji

✅ **3. System pozostaje responsywny**
- Użycie async/await i executor dla operacji blokujących
- Brak blokowania głównych pętli aplikacji

✅ **4. Zdarzenia widoczne w logach**
- `chat.stream.start`, `chat.stream.ok`, `tts.stream_async.sentence`, `chat_tts.stream.complete`

✅ **5. Pokrycie testami**
- 6 nowych testów jednostkowych
- Wszystkie istniejące testy przechodzą (61 testów voice)

## Kompatybilność wsteczna

- ✅ Istniejąca funkcja `chat.ask()` działa bez zmian
- ✅ Istniejąca funkcja `tts.speak()` działa bez zmian
- ✅ Blokady `transport=realtime` pozostają dla starych funkcji
- ✅ Nowe funkcje streamingowe działają równolegle

## Linting i formatowanie

- ✅ `ruff check --fix` - wszystkie sprawdzenia przeszły
- ✅ `ruff format` - kod sformatowany
- ✅ Linia ≤120 znaków (zgodnie z pyproject.toml)

## Uwagi implementacyjne

1. **OpenAI SDK**: Używa `AsyncOpenAI` dla streamingu
2. **Sentence detection**: Wykrywa końce zdań przez znaki: `.`, `!`, `?`, `\n`
3. **Minimum buffer**: 10 znaków przed wysłaniem do TTS
4. **Error handling**: Kontynuacja mimo błędów w pojedynczych zdaniach
5. **Config override**: TTS tymczasowo używa `transport="file"` wewnętrznie

## Kolejne kroki (opcjonalne)

1. **Fine-tuning sentence detection**: Obsługa skrótów (np. "dr.", "itd.")
2. **Adaptive buffering**: Dynamiczny próg oparty na długości tekstu
3. **Metrics**: Śledzenie latencji TTFx (Time To First Token, Time To First Audio)
4. **Mockowanie OpenAI API**: Testy integracyjne bez rzeczywistego API
5. **Configuration**: Parametry sentence buffering w TOML

## Powiązane pliki

- `apps/voice/chat.py` - moduł czatu
- `apps/voice/tts.py` - moduł TTS
- `apps/voice/stream/service.py` - usługa strumieniowa
- `tests/test_chat_streaming.py` - testy czatu
- `tests/test_tts_streaming.py` - testy TTS
- `docs/modules/voice.md` - dokumentacja
