# Moduł Choreographer (`apps/choreographer`)

## Opis

Moduł `apps/choreographer` (Choreograf) pełni rolę orkiestratora, koordynując akcje pomiędzy istniejącymi modułami: `voice`, `ui/face` i `motion`. Pozwala na tworzenie złożonych, spójnych zachowań robota, łączących mowę, mimikę twarzy i ruch.

### Główne funkcje

- **Subskrypcja zdarzeń** — nasłuchuje na wybrane tematy w magistrali zdarzeń (np. `events.sentiment`, `events.nlu.emotion`)
- **Mapowanie zdarzeń na akcje** — na podstawie konfiguracji tworzy zsynchronizowane sekwencje komend
- **Publikacja komend** — wysyła komendy do modułów wykonawczych (face, motion) przez magistralę ZMQ
- **Konfigurowalne choreografie** — łatwa modyfikacja zachowań przez edycję pliku TOML

## Przepływ danych

```
Wejście:  SUB("events.sentiment") → {"sentiment": "joy", "confidence": 0.9, "ts": 1234567890.1}
          ↓
Mapowanie: config/choreography.toml → trigger match: sentiment=="joy"
          ↓
Akcje:    PUB("command.face.expression") → {"expression": "happy", "duration": 3.0}
          PUB("motion") → {"type": "drive", "lx": 0.3, "az": 0.0}
```

## Przykład pożądanego zachowania

Gdy moduł `voice` (a konkretnie NLU lub chat) wykryje w rozmowie sentyment `joy` (radość), Choreograf:
1. Wysyła komendę do modułu `ui/face`, aby wyświetlił animację uśmiechu (`expression: "happy"`)
2. Wysyła komendę do modułu `motion`, aby wykonał ruch do przodu (`type: "drive", "lx": 0.3`)

## Konfiguracja

### Zmienne środowiskowe

| Zmienna | Typ | Domyślna | Opis |
|---------|-----|----------|------|
| `CHOREOGRAPHER_CONFIG` | string | `config/choreography.toml` | Ścieżka do pliku konfiguracji |
| `CHOREOGRAPHER_LOG_LEVEL` | string | `INFO` | Poziom logowania (DEBUG, INFO, WARNING, ERROR) |
| `CHOREOGRAPHER_WARMUP_MS` | int | `10` | Czas rozgrzewki ZMQ PUB w milisekundach |
| `BUS_XPUB` | string | `tcp://127.0.0.1:5556` | Endpoint XPUB brokera (SUB łączy się tu) |
| `BUS_XSUB` | string | `tcp://127.0.0.1:5555` | Endpoint XSUB brokera (PUB łączy się tu) |

### Plik konfiguracji (`config/choreography.toml`)

Plik definiuje mapowania zdarzeń na akcje. Struktura:

```toml
[[mappings]]
name = "joy_response"
description = "Respond to joyful sentiment with happy expression and movement"

[mappings.trigger]
topic = "events.sentiment"
[mappings.trigger.match]
sentiment = "joy"

[[mappings.actions]]
topic = "command.face.expression"
[mappings.actions.payload]
expression = "happy"
duration = 3.0

[[mappings.actions]]
topic = "motion"
[mappings.actions.payload]
type = "drive"
lx = 0.3
az = 0.0
```

#### Struktura mapowania

**Trigger (wyzwalacz):**
- `topic` — temat na magistrali do nasłuchiwania (obsługuje wildcards: `events.*`)
- `match` — kryteria dopasowania (wszystkie pola muszą się zgadzać)
  - Wartość pojedyncza: `sentiment = "joy"`
  - Wartości multiple: `sentiment = ["joy", "happy"]`
  - Wildcard: `*` (dowolna wartość)

**Actions (akcje):**
- `topic` — temat do publikacji komendy
- `payload` — dane do wysłania (format zależy od modułu docelowego)

### Dodawanie nowej choreografii

Aby dodać nową choreografię, wystarczy dopisać nowy blok `[[mappings]]` w pliku `config/choreography.toml`:

```toml
[[mappings]]
name = "surprise_response"
description = "Respond to surprise with blink and slight jump"

[mappings.trigger]
topic = "events.sentiment"
[mappings.trigger.match]
sentiment = "surprise"

[[mappings.actions]]
topic = "command.face.gesture"
[mappings.actions.payload]
gesture = "blink"

[[mappings.actions]]
topic = "motion"
[mappings.actions.payload]
type = "drive"
lx = 0.2
az = 0.3  # slight turn
```

**Nie wymaga to zmiany kodu** — moduł automatycznie załaduje nową konfigurację po restarcie.

## Uruchomienie

### Ręczne uruchomienie (deweloperskie)

```bash
# Uruchom choreografa w foreground
python3 -m apps.choreographer

# Z custom config
CHOREOGRAPHER_CONFIG=/path/to/custom.toml python3 -m apps.choreographer

# Z debug logami
CHOREOGRAPHER_LOG_LEVEL=DEBUG python3 -m apps.choreographer
```

### Uruchomienie jako usługa systemd

```bash
# Sync konfiguracji systemd
bash scripts/systemd-sync.sh

# Start usługi
sudo systemctl start rider-choreographer

# Status
sudo systemctl status rider-choreographer

# Logi
sudo journalctl -u rider-choreographer -f

# Enable na starcie systemu
sudo systemctl enable rider-choreographer
```

## Testowanie

### Test ręczny (przez bus)

```bash
# Terminal 1: uruchom choreografa
python3 -m apps.choreographer

# Terminal 2: wyślij testowe zdarzenie
python3 -c "
from common.bus import BusPub
pub = BusPub()
pub.publish('events.sentiment', {'sentiment': 'joy', 'confidence': 0.9})
pub.close()
"

# Powinny zostać opublikowane komendy do face i motion
```

### Test z użyciem skryptu dev_bus-pub.py

```bash
# Terminal 1: choreograf
python3 -m apps.choreographer

# Terminal 2: nasłuch na command.face.*
python3 scripts/dev_bus-sub.py "command.face"

# Terminal 3: nasłuch na command.motion.*
python3 scripts/dev_bus-sub.py "command.motion"

# Terminal 4: wyślij event
python3 scripts/dev_bus-pub.py events.sentiment '{"sentiment": "joy", "confidence": 0.9}'
```

### Testy jednostkowe

```bash
# Uruchom wszystkie testy choreografa
pytest tests/test_choreographer*.py -v

# Uruchom tylko test konfiguracji
pytest tests/test_choreographer_config.py -v

# Uruchom tylko test mapowania
pytest tests/test_choreographer_mapping.py -v
```

## Integracja z innymi modułami

### Źródła zdarzeń (Publishers)

Moduły, które mogą publikować zdarzenia dla choreografa:

- **NLU** (`apps/nlu`) — analiza sentymentu w tekście (temat: `events.sentiment`)
- **Chat** — analiza emocji w odpowiedziach AI (temat: `events.nlu.emotion`)
- **Voice** — stany głosowe (temat: `voice.state`)
- **Vision** — detekcja osób/twarzy (temat: `vision.person`, `vision.face`)

### Moduły wykonawcze (Subscribers)

Moduły, które mogą odbierać komendy z choreografa:

- **Face** (`apps/ui/face`) — sterowanie ekspresją twarzy
  - Temat: `command.face.expression`
  - Payload: `{"expression": "happy|sad|neutral", "duration": 3.0}`
  - **Uwaga:** W obecnej implementacji moduł face nie subskrybuje tego tematu automatycznie. Wymagana jest integracja w przyszłej wersji.
  
- **Motion** (`apps/motion`) — sterowanie ruchem
  - Temat: `motion`
  - Payload dla ruchu: `{"type": "drive", "lx": 0.3, "az": 0.0}`
  - Payload dla stop: `{"type": "stop"}`
  - Parametry:
    - `lx` — prędkość liniowa (forward/backward, -1.0 do 1.0)
    - `az` — prędkość obrotowa (angular z, -1.0 do 1.0)

## Struktura kodu

```
apps/choreographer/
├── __init__.py          # Inicjalizacja modułu
├── __main__.py          # Entry point dla python -m
├── main.py              # Główna logika serwisu
└── config.py            # Ładowanie i walidacja konfiguracji
```

## Zależności
- **Python 3.11+** (stdlib `tomllib` dla parsowania TOML)
  lub **Python 3.9–3.10** z zewnętrznym pakietem [`tomli`](https://pypi.org/project/tomli/) — wymagany fallback w kodzie
### Wewnętrzne (w repo)
- `common.bus.BusPub` — publikacja komend
- `common.bus.BusSub` — subskrypcja zdarzeń

### Zewnętrzne
- **Python 3.9+** (stdlib `tomllib` dla parsowania TOML)
- **ZMQ** (PyZMQ) — komunikacja przez magistralę

## Logowanie

Moduł loguje do `stdout`/`journal` z formatem:

```
[12:34:56] [choreographer] INFO: Loaded 5 choreography mapping(s)
[12:34:56] [choreographer] INFO: Subscribing to topics: events.nlu.emotion, events.sentiment
[12:34:56] [choreographer] INFO: Choreographer started
[12:35:02] [choreographer] INFO: Choreography triggered by events.sentiment: executing 2 action(s)
[12:35:02] [choreographer] DEBUG: Published to command.face.expression: {'expression': 'happy', 'duration': 3.0}
[12:35:02] [choreographer] DEBUG: Published to command.motion.action: {'action': 'wag', 'speed': 0.5, 'duration': 2.0}
```

## Diagnostyka

### Typowe problemy

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Brak reakcji na zdarzenia | Temat nie pasuje do konfiguracji | Sprawdź `topic` w `choreography.toml` |
| Niepoprawna choreografia | Błąd w TOML | Sprawdź składnię z `tomllib` lub edytorem TOML |
| Moduły nie odbierają komend | Tematy nie są subskrybowane | Sprawdź implementację modułów docelowych |
| Choreograf się nie uruchamia | Broker nie działa | Uruchom `rider-broker.service` |

### Debug

```bash
# Sprawdź załadowane mapowania
CHOREOGRAPHER_LOG_LEVEL=DEBUG python3 -m apps.choreographer

# Sprawdź poprawność TOML (Python)
python3 -c "
import tomllib
with open('config/choreography.toml', 'rb') as f:
    print(tomllib.load(f))
"

# Nasłuchuj wszystkich zdarzeń na busie
python3 scripts/dev_bus-sub.py ""

# Nasłuchuj wszystkich komend choreografa
python3 scripts/dev_bus-sub.py "command"
```

## Rozszerzenia (TODO)

- [ ] Wsparcie dla opóźnień między akcjami (sequential choreography)
- [ ] Wsparcie dla warunkowych akcji (if/else logic)
- [ ] Wsparcie dla priorytetu choreografii (co w przypadku konfliktów)
- [ ] Integracja z timeline (wykresy Gantta dla złożonych sekwencji)
- [ ] Web UI do wizualizacji i edycji choreografii

---

**Related docs:**
- [motion.md](motion.md) — moduł ruchu (odbiera `command.motion.*`)
- [ui.md](ui.md) — moduł UI/face (odbiera `command.face.*`)
- [nlu.md](nlu.md) — analiza języka naturalnego (publikuje `events.sentiment`)
- [../ARCHITECTURE.md](../ARCHITECTURE.md) — architektura systemu

**Ostatnia aktualizacja:** 2025-01
