# Moduł Launcher (`apps/main.py`)

## Opis

Moduł `apps/main.py` implementuje **proste menu startowe** (CLI) dla Rider-Pi. Umożliwia wybór trybu pracy robota: demo trajectory, testy drive/stop, E-Stop ON/OFF.

### Główne funkcje

- **`on_ok()`** — obsługa przycisku OK (wybór pozycji menu)
- **`on_back()`** — obsługa przycisku BACK (emergency stop)
- **`on_left()` / `on_right()`** — nawigacja po menu (zmiana kursora)
- **`pub_menu_state()`** — publikacja stanu menu na `system.menu.state`
- **`low_batt_blocked()`** — blokada trybów ruchu przy niskim poziomie baterii

## Przepływ danych

```
Wejście:  SUB("ui.button") → {"key": "OK"|"BACK"|"LEFT"|"RIGHT", ...}
          SUB("motion.state") → {"battery": 0.85, ...}
          ↓
Akcja:    zmiana kursora / wybór trybu / emergency stop
          ↓
Wyjście:  PUB("system.mode") → {"mode": "demos"|"autonomy"|"teleop", ...}
          PUB("motion.cmd") → {"type": "stop"}  (przy BACK)
          PUB("system.menu.state") → stan menu dla potencjalnego wyświetlacza
```

## Konfiguracja

### Hardcoded w kodzie

| Parametr | Wartość | Opis |
|----------|---------|------|
| `HOME_ITEMS` | `["Dema", "Autonomia", "Teleop", "Ustawienia", "Logi"]` | Pozycje menu głównego |
| `LOW_BATTERY_LIMIT` | `0.15` (15%) | Próg baterii blokujący tryby ruchu |
| `PROJ_ROOT` | `/home/pi/robot` | Ścieżka projektu dla importów |

⚠️ **Uwaga:** Parametry są hardcoded — do rozszerzenia przez ENV lub TOML.

## Pozycje menu

### 1. Dema
- **Akcja:** Publish `system.mode = "demos"` z `demo: "trajectory"`
- **Blokada:** Wymagany poziom baterii >15%
- **Przed startem:** Wysyła `motion.cmd = stop`

### 2. Autonomia
- **Akcja:** Publish `system.mode = "autonomy"`
- **Blokada:** Wymagany poziom baterii >15%
- **Przed startem:** Wysyła `motion.cmd = stop`

### 3. Teleop
- **Akcja:** Publish `system.mode = "teleop"`
- **Blokada:** Brak (działa nawet przy niskiej baterii)
- **Przed startem:** Wysyła `motion.cmd = stop`

### 4. Ustawienia
- **Akcja:** (placeholder — obecnie nic nie robi)
- **Planowane:** Konfiguracja głośności, jasności LCD, etc.

### 5. Logi
- **Akcja:** (placeholder — obecnie nic nie robi)
- **Planowane:** Zmiana poziomu logów, eksport logów

## Przyciski

| Przycisk | Akcja |
|----------|-------|
| **OK** | Wybór aktualnej pozycji menu → uruchomienie trybu |
| **BACK** | Emergency stop (`motion.cmd = stop`) — działa zawsze |
| **LEFT** | Przesunięcie kursora w lewo (wrap around) |
| **RIGHT** | Przesunięcie kursora w prawo (wrap around) |

## Przykład użycia

### Uruchomienie ręczne

```bash
python -m apps.launcher.main
```

### Symulacja przycisków (testowanie)

```bash
# Terminal 1: uruchom launcher
python -m apps.launcher.main

# Terminal 2: symuluj naciśnięcie przycisku RIGHT
python -c "from common.bus import BusPub; BusPub().publish('ui.button', {'key': 'RIGHT'})"

# Terminal 3: symuluj naciśnięcie przycisku OK
python -c "from common.bus import BusPub; BusPub().publish('ui.button', {'key': 'OK'})"
```

### Sprawdzenie stanu menu

```bash
# Subskrybuj topik system.menu.state
python -c "from common.bus import BusSub; import json; s=BusSub('system.menu.state'); print(json.dumps(s.recv()[1], indent=2))"
```

## Logowanie

Moduł używa prostej funkcji `log()` → `stdout`:

```
Menu: start
Menu: RIGHT → cursor=1
Menu: OK → mode=autonomy
Menu: BACK → STOP
Menu: bye
```

## Błędy i diagnostyka

### Typowe problemy

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Brak reakcji na przyciski | BUS nie działa lub brak `ui.button` | Sprawdź czy `apps/ui/buttons` publikuje eventy |
| Blokada trybów Dema/Autonomia | Niski poziom baterii (<15%) | Naładuj baterię lub użyj Teleop |
| Brak informacji o baterii | `motion.state` nie publikuje `battery` | Sprawdź moduł `apps/motion` |

### Diagnostyka

```bash
# Sprawdź czy przyciski publikują eventy
python -c "from common.bus import BusSub; s=BusSub('ui.button'); print(s.recv())"

# Sprawdź poziom baterii
python -c "from common.bus import BusSub; import json; s=BusSub('motion.state'); print(json.dumps(s.recv()[1], indent=2))"
```

## Stan wewnętrzny

```python
state = {
    "screen": "home",      # aktualny ekran (obecnie tylko "home")
    "cursor": 0,           # indeks w HOME_ITEMS (0–4)
    "battery": None,       # ostatni odczyt poziomu baterii (0.0–1.0)
}
```

## Payload topików

### `system.mode` (publish)
```json
{
  "mode": "demos" | "autonomy" | "teleop",
  "demo": "trajectory",  // tylko dla mode="demos"
  "ts": 1704067200.123
}
```

### `system.menu.state` (publish)
```json
{
  "screen": "home",
  "cursor": 2,
  "items": ["Dema", "Autonomia", "Teleop", "Ustawienia", "Logi"],
  "ts": 1704067200.456,
  "battery": 0.85
}
```

### `motion.cmd` (publish przy BACK)
```json
{
  "type": "stop"
}
```

## Zależności

### Wewnętrzne (w repo)
- `common.bus.BusPub` — publikacja komend
- `common.bus.BusSub` — subskrypcja przycisków i stanu ruchu

### Zewnętrzne
- **Brak** — moduł używa tylko biblioteki standardowej Python

## Rozszerzenia (TODO)

- [ ] Konfiguracja pozycji menu przez ENV/TOML
- [ ] Implementacja ekranu "Ustawienia" (volume, brightness)
- [ ] Implementacja ekranu "Logi" (log level, tail, export)
- [ ] Obsługa dodatkowych ekranów (submenu)
- [ ] Integracja z LCD dla wizualizacji menu

---

**Related docs:**
- [menu.md](menu.md) — alternatywny moduł menu (bardziej rozbudowany?)
- [ui.md](ui.md) — moduł UI (przyciski, konfiguracja)
- [motion.md](motion.md) — odbiera komendy `motion.cmd`

**Ostatnia aktualizacja:** 2025-01
