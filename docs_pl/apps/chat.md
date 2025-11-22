# Moduł Chat (`apps/chat`)

## Opis

Moduł `apps/chat` realizuje konwersację z OpenAI — odbiera transkrypcje audio i odpowiada przez syntezę mowy.

### Główne funkcje

- **`chat_answer(user_text: str) -> str`** — wysyła zapytanie do OpenAI GPT-4o-mini, zwraca odpowiedź
- **`main()`** — pętla główna: nasłuch na `audio.transcript`, publikacja na `tts.speak`

### Filtrowanie komend ruchu

Moduł **pomija** komendy ruchu (rozpoznaje je przez `common.nlu_shared.is_motion_command()`), przekazując je do modułu NLU.

## Przepływ danych

```
Wejście:  SUB("audio.transcript") → {"text": "...", "lang": "pl", "source": "voice"}
          ↓
Filtr:    if is_motion_command(text) → SKIP (pozostaw dla NLU)
          ↓
Chat:     OpenAI GPT-4o-mini (system prompt: asystent robota XGO, PL, zwięzły)
          ↓
Wyjście:  PUB("tts.speak") → {"text": "<odpowiedź>", "ts": ..., "source": "chat"}
```

## Konfiguracja

### Wymagane zmienne środowiskowe

| Zmienna | Opis | Wymagana | Domyślna |
|---------|------|----------|----------|
| `OPENAI_API_KEY` | Klucz API OpenAI | **tak** | — |

### Ładowanie klucza API

Moduł automatycznie próbuje załadować `OPENAI_API_KEY` z profili powłoki:
1. `~/.bash_profile`
2. `~/.profile`
3. `~/.bashrc`

Jeśli klucz nie zostanie znaleziony, moduł kończy działanie z błędem.

**Zobacz także:** [docs/config/POLICY.md](../config/POLICY.md) — polityka sekretów

### Model i parametry

Hardcoded w kodzie (można rozszerzyć o ENV):
- **Model:** `gpt-4o-mini`
- **Temperature:** `0.3`
- **Max tokens:** `80`
- **System prompt:** _"Jesteś zwięzłym asystentem robota XGO. Odpowiadaj po polsku, jednym krótkim zdaniem."_

## Przykład użycia

### Uruchomienie ręczne

```bash
# Z kluczem w ENV
export OPENAI_API_KEY=sk-...
python -m apps.chat.main

# Lub po source'owaniu profilu
source ~/.bash_profile
python -m apps.chat.main
```

### Integracja z systemd

```bash
# Jeśli skonfigurowano usługę (przykład):
sudo systemctl start rider-chat.service
sudo systemctl status rider-chat.service
```

### Testowanie przez BUS

```bash
# Terminal 1: uruchom chat
python -m apps.chat.main

# Terminal 2: wyślij testowy transcript
python -c "from common.bus import BusPub; BusPub().publish('audio.transcript', {'text': 'Jaka jest pogoda?', 'lang': 'pl', 'source': 'voice'})"
```

## Błędy i diagnostyka

### Typowe błędy

| Błąd | Przyczyna | Rozwiązanie |
|------|-----------|-------------|
| `BLAD: brak pakietu openai` | Brak biblioteki `openai` | `pip install openai` |
| `OPENAI_API_KEY nie jest ustawiony` | Brak klucza API w ENV | Dodaj do `~/.bash_profile` lub ustaw `export OPENAI_API_KEY=...` |
| `CHAT: błąd: <exception>` | Błąd komunikacji z API | Sprawdź klucz API, połączenie sieciowe, limity OpenAI |

### Logowanie

Moduł loguje do `stdout` z timestampem `[HH:MM:SS]`:

```
[12:34:56] CHAT: start (sub audio.transcript -> pub tts.speak)
[12:34:58] CHAT: rozpoznano komendę ruchu, pomijam: 'jedź do przodu'
[12:35:02] CHAT -> TTS: Pogoda jest dziś słoneczna.
[12:35:10] CHAT: bye
```

### Diagnostyka

```bash
# Sprawdź czy klucz API jest załadowany
env | grep OPENAI_API_KEY

# Sprawdź wersję pakietu openai
pip show openai

# Test komunikacji z API (poza modułem)
python -c "from openai import OpenAI; print(OpenAI(api_key='$OPENAI_API_KEY').models.list().data[0])"
```

## Zależności

### Wewnętrzne (w repo)
- `common.bus.BusPub` — publikacja na topiki
- `common.bus.BusSub` — subskrypcja topiców
- `common.bus.now_ts` — timestamp do payloadów
- `common.nlu_shared.is_motion_command` — filtrowanie komend ruchu

### Zewnętrzne (PyPI)
- `openai` — klient OpenAI API

## Notatki

- Moduł zakłada, że BUS (Redis/ZeroMQ) jest już uruchomiony
- Komendy ruchu są przekazywane do `apps/nlu` zamiast do chatu
- Odpowiedzi są zwięzłe (max 80 tokenów) dla szybkości i niskich kosztów
- Moduł działa w trybie **ciągłego nasłuchu** (pętla `while True`)

---

**Related docs:**
- [nlu.md](nlu.md) — moduł NLU (rozpoznawanie komend ruchu)
- [do./voice.md](./voice.md) — źródło `audio.transcript`
- [config/POLICY.md](../config/POLICY.md) — polityka konfiguracji i sekretów

**Ostatnia aktualizacja:** 2025-01
