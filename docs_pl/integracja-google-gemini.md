# Integracja Google Gemini

> **📖 Nowa dokumentacja**: Pełna dokumentacja ekosystemu Google Gemini (ASR + Chat + TTS) dostępna w [docs/ecosystem-google.md](ecosystem-google.md)

## Opis

Rider-Pi obsługuje Google Gemini jako alternatywny backend dla funkcji czatu. Integracja umożliwia:

- **Tryb REST (plikowy)** — synchroniczne zapytania do API Gemini
- **Tryb quasi-streaming (realtime)** — asynchroniczne streamowanie odpowiedzi

## Wymagania

### Zależności

Dodaj do `requirements-dev.txt`:

```
google-generativeai>=0.8.0
```

Instalacja:

```bash
pip install google-generativeai
```

### Klucz API

1. Uzyskaj klucz API Google Gemini z [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Ustaw zmienną środowiskową:

```bash
export GOOGLE_API_KEY="twój-klucz-api"
```

Lub dodaj do `~/.bash_profile`:

```bash
echo 'export GOOGLE_API_KEY="twój-klucz-api"' >> ~/.bash_profile
source ~/.bash_profile
```

## Konfiguracja

### Konwencja nazewnicza plików konfiguracyjnych

Od wersji 2025-01, pliki konfiguracyjne voice używają jednoznacznej konwencji nazewniczej:
`voice_<provider>_<mode>.toml`

Gdzie:
- `<provider>` — dostawca usług: `openai`, `gemini`
- `<mode>` — tryb komunikacji: `file` (REST API), `streaming` (WebSocket)

**Dostępne pliki:**
- `voice_openai_file.toml` — OpenAI w trybie plikowym (REST)
- `voice_openai_streaming.toml` — OpenAI w trybie strumieniowym (WebSocket)
- `voice_gemini_file.toml` — Google Gemini w trybie plikowym (REST)
- `voice_gemini_example.toml` — Przykładowa konfiguracja Gemini

### Tryb plikowy (REST API)

Plik: `config/voice_gemini_file.toml`

```toml
[chat]
backend = "google"
model = "gemini-pro"
system_prompt = "Jesteś asystentem głosowym Rider-Pi. Odpowiadaj krótko po polsku."
max_history = 4
transport = "rest"
```

### Tryb strumieniowy (Realtime)

**Uwaga:** Google Gemini obecnie nie ma dedykowanego trybu strumieniowego WebSocket. 
Dla streamingu używaj `voice_gemini_file.toml` z parametrem `transport = "realtime"` 
dla quasi-streamingu przez REST API.

Plik: `config/voice_gemini_file.toml` (z modyfikacją)

```toml
[chat]
backend = "google"
model = "gemini-pro"
system_prompt = "Jesteś asystentem głosowym Rider-Pi. Odpowiadaj krótko po polsku."
max_history = 4
transport = "realtime"
```

## Dostępne modele

Google Gemini oferuje różne modele:

- **`gemini-pro`** — model ogólnego przeznaczenia, zalecany dla większości zastosowań
- **`gemini-pro-vision`** — model z obsługą obrazów (obecnie nieobsługiwany w Rider-Pi)
- **`gemini-1.5-pro`** — najnowszy model z rozszerzonym kontekstem
- **`gemini-1.5-flash`** — szybszy model dla prostszych zadań

**Uwaga:** Sprawdź [dokumentację Google AI](https://ai.google.dev/models/gemini) dla aktualnej listy dostępnych modeli.

## Różnice między OpenAI a Google Gemini

| Cecha | OpenAI | Google Gemini |
|-------|--------|---------------|
| Zmienna środowiskowa | `OPENAI_API_KEY` | `GOOGLE_API_KEY` |
| Modele | `gpt-4o`, `gpt-4o-mini` | `gemini-pro`, `gemini-1.5-pro` |
| Format historii | `role: assistant` | `role: model` |
| Streaming | Natywny | Quasi-streaming |
| Limit kontekstu | Do 128k tokenów | Do 1M tokenów (gemini-1.5-pro) |

## Użycie

### Tryb plikowy (PTT)

```bash
# Uruchom z konfiguracją Google Gemini
make voice-file-ptt  # używa domyślnie voice_openai_file.toml

# Lub bezpośrednio z Gemini:
python -m apps.voice.cli --config ./config/voice_gemini_file.toml ptt
```

### Tryb strumieniowy

```bash
# Uwaga: dla Gemini używaj pliku voice_gemini_file.toml
python -m apps.voice.cli --config ./config/voice_gemini_file.toml listen
```

### Programatyczne użycie

```python
from apps.voice.chat import ChatConfig, ChatSession

# Konfiguracja
config = ChatConfig(
    backend="google",
    model="gemini-pro",
    system_prompt="Jesteś pomocnym asystentem.",
    max_history=4,
    transport="file",  # lub "realtime"
)

# Sesja czatu
session = ChatSession(config)

# Synchroniczne zapytanie (REST)
reply, history = session.ask("Co to jest sztuczna inteligencja?")
print(reply)

# Asynchroniczne streamowanie
import asyncio

async def stream_example():
    async for chunk in session.ask_stream("Opowiedz mi o AI"):
        print(chunk, end="", flush=True)

asyncio.run(stream_example())
```

## Obsługa błędów

Integracja z Google Gemini zawiera walidację i obsługę błędów:

### Brak klucza API

```python
ChatError: GOOGLE_API_KEY is not set
```

**Rozwiązanie:** Ustaw zmienną środowiskową `GOOGLE_API_KEY`.

### Brak SDK

```python
ChatError: Google Generative AI SDK unavailable: No module named 'google'
```

**Rozwiązanie:** Zainstaluj `google-generativeai`:

```bash
pip install google-generativeai
```

### Nieprawidłowy model

```python
ChatError: Google Gemini chat completion failed: ...
```

**Rozwiązanie:** Sprawdź nazwę modelu w konfiguracji. Użyj `gemini-pro` lub innego dostępnego modelu.

### Tryb REST w konfiguracji realtime

```python
ChatError: Chat REST disabled when transport=realtime
```

**Rozwiązanie:** Użyj metody `ask_stream()` zamiast `ask()` lub zmień `transport` na `"file"`.

## Historia konwersacji

Google Gemini używa formatu historii kompatybilnego z OpenAI, ale z automatycznym mapowaniem ról:

- `user` → `user` (bez zmian)
- `assistant` → `model` (mapowanie wewnętrzne)

System automatycznie zarządza historią konwersacji, zachowując ostatnie `max_history` par user/assistant.

## Limity i koszty

### Limity API

Google Gemini ma następujące limity (stan na 2025-01):

- **Darmowy tier:**
  - 60 zapytań/minutę
  - 1500 zapytań/dzień
  - Brak kosztów

- **Tier płatny:**
  - Sprawdź [cennik Google AI](https://ai.google.dev/pricing)

### Optymalizacja kosztów

1. **Ogranicz historię:** Użyj `max_history = 2-4` zamiast większych wartości
2. **Użyj krótszych promptów:** Krótki `system_prompt` zmniejsza zużycie tokenów
3. **Wybierz odpowiedni model:** `gemini-1.5-flash` jest tańszy niż `gemini-1.5-pro`

## Testowanie

### Testy jednostkowe

```bash
# Uruchom testy Google Gemini
python -m pytest tests/test_chat_gemini.py -v

# Wszystkie testy czatu
python -m pytest tests/test_chat_*.py -v
```

### Testy ręczne

```bash
# Test z echo backend (bez API)
cat > /tmp/test_config.toml << EOF
[chat]
backend = "echo"
model = "test"
system_prompt = "Test"
EOF

python -m apps.voice.cli --config /tmp/test_config.toml once

# Test z Google Gemini (wymaga GOOGLE_API_KEY)
export GOOGLE_API_KEY="twój-klucz"
python -m apps.voice.cli --config ./config/voice_openai_file.toml once
```

## Rozwiązywanie problemów

### Problem: Brak odpowiedzi od Gemini

**Objawy:** Timeout lub brak odpowiedzi

**Rozwiązanie:**
1. Sprawdź połączenie internetowe
2. Zweryfikuj poprawność klucza API
3. Sprawdź limity API (zbyt wiele zapytań)

### Problem: Odpowiedź w niewłaściwym języku

**Objawy:** Gemini odpowiada po angielsku zamiast po polsku

**Rozwiązanie:**
Zaktualizuj `system_prompt`:

```toml
[chat]
system_prompt = "Jesteś asystentem głosowym. ZAWSZE odpowiadaj PO POLSKU. Bądź zwięzły."
```

### Problem: Zbyt długie odpowiedzi

**Objawy:** Gemini generuje bardzo długie odpowiedzi

**Rozwiązanie:**
Dodaj do `system_prompt`:

```toml
[chat]
system_prompt = "Odpowiadaj BARDZO KRÓTKO - maksymalnie 2-3 zdania."
max_tokens = 150  # Opcjonalnie ogranicz długość
```

## Bezpieczeństwo

### Najlepsze praktyki

1. **Nie commituj kluczy API do repozytorium:**
   ```bash
   # Dodaj do .gitignore
   echo "*.env" >> .gitignore
   echo ".api_keys" >> .gitignore
   ```

2. **Używaj zmiennych środowiskowych:**
   ```bash
   # W ~/.bash_profile zamiast bezpośrednio w kodzie
   export GOOGLE_API_KEY="$(cat ~/.secrets/google_api_key)"
   ```

3. **Rotuj klucze regularnie:**
   - Generuj nowy klucz co 90 dni
   - Unieważnij stare klucze w Google AI Studio

4. **Monitoruj użycie:**
   - Sprawdzaj statystyki w [Google AI Studio](https://makersuite.google.com/)
   - Ustawiaj alerty dla nietypowej aktywności

## Kompatybilność wsteczna

Integracja Google Gemini **nie wpływa** na istniejące funkcjonalności:

- ✅ Backend OpenAI działa bez zmian
- ✅ Echo backend działa bez zmian
- ✅ Wszystkie istniejące konfiguracje są wspierane
- ✅ Domyślny backend pozostaje `openai` (jeśli nie określono inaczej)

### Migracja z OpenAI

Aby przejść z OpenAI na Google Gemini:

1. Zainstaluj SDK: `pip install google-generativeai`
2. Uzyskaj klucz API Google
3. Użyj dedykowanego pliku konfiguracyjnego:
   - Skopiuj `config/voice_gemini_example.toml` do `config/voice_gemini_file.toml`
   - Lub ręcznie zmień w pliku `.toml`:
   ```toml
   [chat]
   backend = "google"  # było: "openai"
   model = "gemini-pro"  # było: "gpt-4o-mini"
   ```
4. Ustaw `GOOGLE_API_KEY` zamiast `OPENAI_API_KEY`
5. Uruchom: `python -m apps.voice.cli --config ./config/voice_gemini_file.toml ptt`

## Przykłady użycia

### Przykład 1: Asystent wielojęzyczny

```toml
[chat]
backend = "google"
model = "gemini-1.5-pro"
system_prompt = "Jesteś asystentem wielojęzycznym. Odpowiadaj w języku pytania użytkownika."
max_history = 6
```

### Przykład 2: Asystent techniczny

```toml
[chat]
backend = "google"
model = "gemini-pro"
system_prompt = "Jesteś ekspertem od Raspberry Pi i systemów wbudowanych. Udzielaj konkretnych, technicznych odpowiedzi."
max_history = 8
```

### Przykład 3: Szybkie odpowiedzi

```toml
[chat]
backend = "google"
model = "gemini-1.5-flash"
system_prompt = "Odpowiadaj maksymalnie jednym zdaniem."
max_history = 2
max_tokens = 50
```

## Wsparcie i rozwój

### Zgłaszanie problemów

W przypadku problemów z integracją Google Gemini:

1. Sprawdź logi: `make logs-all`
2. Uruchom testy: `python -m pytest tests/test_chat_gemini.py -v`
3. Zgłoś issue na GitHub z:
   - Wersją Python
   - Wersją `google-generativeai`
   - Fragmentem konfiguracji (bez klucza API!)
   - Komunikatem błędu

### Planowane funkcje

- [ ] Obsługa `gemini-pro-vision` dla multimodalności
- [ ] Streaming z audio input/output
- [ ] Fine-tuning modeli Gemini
- [ ] Cachowanie odpowiedzi dla optymalizacji kosztów

## Bibliografia

- [Google AI Studio](https://makersuite.google.com/)
- [Dokumentacja Google Gemini API](https://ai.google.dev/docs)
- [Python SDK dla Gemini](https://github.com/google/generative-ai-python)
- [Cennik Google AI](https://ai.google.dev/pricing)

---

**Ostatnia aktualizacja:** 2025-01
**Autor:** Copilot + @mpieniak01
