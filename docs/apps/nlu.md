# Moduł NLU (`apps/nlu`)

## Opis

Moduł `apps/nlu` (Natural Language Understanding) rozpoznaje **intencje ruchu** z transkrypcji głosowych w języku polskim i przekształca je w komendy dla modułu `motion`.

### Główne funkcje

- **`decide(txt_raw: str) -> (dict|None, float)`** — analizuje tekst i zwraca komendę `motion.cmd` oraz zaktualizowaną prędkość
- **`extract_duration_s(txt_norm: str) -> float|None`** — wyciąga czas trwania (np. "na 2 sekundy")
- **`extract_speed(txt_norm: str) -> float|None`** — wyciąga prędkość (np. "60%", "na 0.8")
- **`main()`** — pętla główna: nasłuch na `audio.transcript`, publikacja na `motion.cmd`

## Przepływ danych

```
Wejście:  SUB("audio.transcript") → {"text": "jedź do przodu na 2 sekundy", "lang": "pl", "source": "voice", "is_final": true}
          ↓
Filtr:    lang=="pl" && source=="voice" && (brak is_final lub is_final==true)
          ↓
Analiza:  normalizacja tekstu → rozpoznanie intencji → ekstrakcja parametrów
          ↓
Wyjście:  PUB("motion.cmd") → {"type": "drive", "dir": "forward", "speed": 0.5, "dur": 2.0}
```

## Konfiguracja

### Zmienne środowiskowe

| Zmienna | Typ | Zakres | Domyślna | Opis |
|---------|-----|--------|----------|------|
| `NLU_DEFAULT_SPEED` | float | 0.1–1.0 | `0.5` | Domyślna prędkość ruchu |
| `NLU_DEFAULT_DUR` | float | >0 | `1.0` | Domyślny czas trwania ruchu (sekundy) |
| `NLU_SPEED_STEP` | float | >0 | `0.1` | Krok zmiany prędkości dla "szybciej"/"wolniej" |

### Rozpoznawane komendy

#### Kierunki (drive)
- **Do przodu:** _"jedź"_, _"naprzód"_, _"do przodu"_, _"rusz"_
- **Do tyłu:** _"cofnij"_, _"wycofaj"_, _"do tyłu"_, _"w tył"_

#### Obroty (spin)
- **W lewo:** _"w lewo"_, _"skręć w lewo"_, _"lewo"_
- **W prawo:** _"w prawo"_, _"skręć w prawo"_, _"prawo"_

#### Stop
- **Zatrzymaj:** _"stop"_, _"stój"_, _"zatrzymaj"_, _"halt"_

#### Modyfikatory prędkości
- **Szybciej:** _"szybciej"_, _"przyspiesz"_, _"zwiększ prędkość"_
- **Wolniej:** _"wolniej"_, _"zwolnij"_, _"zmniejsz prędkość"_

### Ekstrakcja parametrów z tekstu

#### Czas trwania
- **Wzorce:** _"na X sekund"_, _"przez X s"_, _"na 1.5 sekundy"_
- **Przykład:** "jedź do przodu **na 3 sekundy**" → `dur=3.0`

#### Prędkość
1. **Procenty:** _"60%"_, _"100%"_ → mapowane na 0.0–1.0
2. **Ułamki:** _"na 0.8"_, _"do 0.5"_ → bezpośrednio 0.0–1.0

**Przykłady:**
- "jedź **60%**" → `speed=0.6`
- "cofnij **na 0.3**" → `speed=0.3`

## Przykład użycia

### Uruchomienie ręczne

```bash
# Uruchom moduł NLU
python -m apps.nlu.main

# W osobnym terminalu: wyślij testową komendę
python -c "from common.bus import BusPub; BusPub().publish('audio.transcript', {'text': 'jedź do przodu na 2 sekundy', 'lang': 'pl', 'source': 'voice', 'is_final': True})"
```

### Integracja z voice

```bash
# Terminal 1: uruchom NLU
python -m apps.nlu.main

# Terminal 2: uruchom motion bridge (odbiera motion.cmd)
python -m apps.motion.main

# Terminal 3: wyślij komendę głosową przez voice
python -m apps.voice.cli ptt --text "skręć w lewo"
```

### Testowanie bez BUS (standalone)

```python
from apps.nlu.main import decide

cmd, speed = decide("jedź do przodu na 3 sekundy 80%")
print(cmd)  # {'type': 'drive', 'dir': 'forward', 'speed': 0.8, 'dur': 3.0}
```

## Błędy i diagnostyka

### Logowanie

Moduł loguje do `stdout` z timestampem `[HH:MM:S]`:

```
[12:34:56] NLU v0.1: start (sub audio.transcript → pub motion.cmd)
[12:34:58] NLU: speed up → 0.60
[12:35:02] NLU → motion.cmd: {'type': 'drive', 'dir': 'forward', 'speed': 0.5, 'dur': 1.0}
[12:35:10] NLU: bye
```

### Typowe problemy

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Brak reakcji na komendy | Lang != "pl" lub source != "voice" | Sprawdź payload `audio.transcript` |
| Ignorowane komendy z ASR | `is_final: false` | ASR musi wysyłać `is_final: true` dla finałowych transkryptów |
| Niewłaściwa prędkość | Niepoprawna ekstrakcja z tekstu | Użyj formatów: "60%", "na 0.8", "przez 2 s" |

### Diagnostyka

```bash
# Sprawdź domyślne wartości ENV
echo $NLU_DEFAULT_SPEED  # powinno być 0.5 (lub puste → fallback)
echo $NLU_DEFAULT_DUR    # powinno być 1.0

# Testuj regex ekstrakcji (Python REPL)
python3
>>> from apps.nlu.main import extract_duration_s, extract_speed, norm
>>> txt = "jedź na 2 sekundy 80%"
>>> extract_duration_s(norm(txt))  # 2.0
>>> extract_speed(norm(txt))       # 0.8
```

## Struktura komend motion.cmd

### Drive (jazda)
```json
{
  "type": "drive",
  "dir": "forward" | "backward",
  "speed": 0.5,  // 0.1–1.0
  "dur": 2.0     // sekundy
}
```

### Spin (obrót)
```json
{
  "type": "spin",
  "dir": "left" | "right",
  "speed": 0.5,
  "dur": 1.5
}
```

### Stop
```json
{
  "type": "stop"
}
```

## Zależności

### Wewnętrzne (w repo)
- `common.bus.BusPub` — publikacja komend ruchu
- `common.bus.BusSub` — subskrypcja transkryptów

### Zewnętrzne
- **Brak** — moduł używa tylko biblioteki standardowej Python

## Stan sesji

Moduł pamięta **bieżącą prędkość** (`cur_speed`) między komendami:
- Domyślnie: `NLU_DEFAULT_SPEED` (0.5)
- "szybciej" → `cur_speed += 0.1` (clamp 0.1–1.0)
- "wolniej" → `cur_speed -= 0.1` (clamp 0.1–1.0)
- Jawna prędkość (np. "60%") → nadpisuje `cur_speed` dla **tej** komendy

## Rozszerzenia (TODO)

- [ ] Wsparcie dla angielskiego (`lang=="en"`)
- [ ] Rozpoznawanie dodatkowych intencji (demo modes, settings)
- [ ] Konfiguracja wzorców przez TOML zamiast hardcoded
- [ ] Integracja z OpenAI dla bardziej złożonych zapytań (fallback)

---

**Related docs:**
- [chat.md](chat.md) — moduł chat (odpowiedzi konwersacyjne)
- [motion.md](motion.md) — bridge ruchu (odbiera `motion.cmd`)
- [docs/modules/voice.md](../modules/voice.md) — źródło `audio.transcript`

**Ostatnia aktualizacja:** 2025-01
