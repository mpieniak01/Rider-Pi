# Moduł UI (`apps/ui`)

## Opis

Moduł `apps/ui` implementuje **interfejs użytkownika** robota — obsługa przycisków fizycznych, konfiguracja UI oraz kontroler buźki (face controller).

### Główne pliki

- **`buttons.py`** — obsługa 4 przycisków fizycznych (GPIO lub symulacja klawiaturą)
- **`config.py`** — konfiguracja UI (ładowanie parametrów)
- **`face_core.py`** — kontroler wysokiego poziomu buźki
- **`face_actuators.py`** — aktuatory buźki (ruchy, emocje)
- **`face_emotions.py`** — mapowanie emocji

## Moduł buttons.py

### Przyciski fizyczne

| Przycisk | GPIO (domyślny) | ENV | Funkcja |
|----------|-----------------|-----|---------|
| LEFT | 24 | `BTN_LEFT` | Nawigacja w lewo |
| RIGHT | 23 | `BTN_RIGHT` | Nawigacja w prawo |
| OK | 17 | `BTN_OK` | Potwierdzenie |
| BACK | 22 | `BTN_BACK` | Powrót / Stop |

### Eventy przycisków

```json
{
  "id": "LEFT" | "RIGHT" | "OK" | "BACK",
  "event": "down" | "up" | "long",
  "ts": 1704067200.5
}
```

### Konfiguracja

| ENV | Typ | Domyślna | Opis |
|-----|-----|----------|------|
| `BTN_LEFT` | int | `24` | Pin GPIO przycisku LEFT |
| `BTN_RIGHT` | int | `23` | Pin GPIO przycisku RIGHT |
| `BTN_OK` | int | `17` | Pin GPIO przycisku OK |
| `BTN_BACK` | int | `22` | Pin GPIO przycisku BACK |
| `BUTTONS_SIM` | int | `0` | Tryb symulacji (1 = klawiatura) |
| `HOLD_S` | float | `1.0` | Czas długiego przytrzymania (s) |

### Tryb symulacji (klawiatura)

```bash
export BUTTONS_SIM=1
python -m apps.ui.buttons
```

Mapowanie klawiszy:
- **l** → LEFT
- **r** → RIGHT
- **Enter** → OK
- **Backspace** → BACK

## Moduł face_core.py

Kontroler wysokiego poziomu buźki — zarządza emocjami, spojrzeniem, mruganiem.

### API (przykład)

```python
from apps.ui.face_core import FaceController

controller = FaceController()

# Zmiana emocji
controller.set_emotion("happy")

# Spojrzenie
controller.look_at(x=0.2, y=-0.1)  # prawo-dół

# Mruganie
controller.blink()

# Idle loop (automatyczne ruchy)
controller.enable_idle(True)
```

## Przepływ danych

### Przyciski
```
GPIO (fizyczne przyciski)
    ↓
gpiozero.Button (debouncing, hold detection)
    ↓
PUB("ui.button") → {"id": "OK", "event": "down", "ts": ...}
    ↓
apps.launcher / apps.menu (odbiorcy)
```

### Face controller
```
API calls (set_emotion, look_at, blink)
    ↓
FaceController → FaceRenderer
    ↓
apps.draw.face_primitives (renderowanie)
    ↓
apps.hw.sink_lcd → LCD
```

## Przykład użycia

### Uruchomienie przycisków (GPIO)

```bash
# Na urządzeniu z GPIO
python -m apps.ui.buttons
```

### Uruchomienie przycisków (symulacja)

```bash
# Na PC bez GPIO
export BUTTONS_SIM=1
python -m apps.ui.buttons
```

### Testowanie face controller

```python
from apps.ui.face_core import FaceController
import time

controller = FaceController()

# Test emocji
for emotion in ["happy", "neutral", "sad"]:
    controller.set_emotion(emotion)
    time.sleep(2)

# Test spojrzenia
controller.look_at(0.5, 0.0)  # prawo
time.sleep(1)
controller.look_at(-0.5, 0.0)  # lewo
time.sleep(1)
controller.look_at(0.0, 0.0)  # środek
```

## Błędy i diagnostyka

### Przyciski

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Brak reakcji na przyciski | GPIO nie dostępne | Sprawdź `sudo raspi-gpio get <pin>` |
| Fałszywe kliknięcia | Brak/zły debouncing | Zwiększ `bounce_time` w kodzie |
| "Permission denied" GPIO | Brak uprawnień | Dodaj użytkownika do grupy `gpio` |
| Długie przytrzymanie nie działa | Za krótki `HOLD_S` | Zwiększ `HOLD_S` (np. `1.5`) |

### Face controller

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Buźka nie renderuje się | Brak pygame/LCD sink | Sprawdź zależności, uruchom `apps.hw.sink_lcd` |
| Parametry nie działają | Niewłaściwa konfiguracja | Sprawdź `config/face.toml` |

### Diagnostyka przycisków

```bash
# Monitoruj eventy przycisków
python -c "from common.bus import BusSub; s=BusSub('ui.button'); import json; \
while True: print(json.dumps(s.recv()[1]))"

# Test GPIO (sprawdź stan pinów)
sudo raspi-gpio get 24  # BTN_LEFT
sudo raspi-gpio get 23  # BTN_RIGHT
```

## Zależności

### Wewnętrzne (w repo)
- `common.bus.BusPub` — publikacja eventów przycisków
- `apps.draw.face_primitives` — renderowanie buźki
- `apps.hw.sink_lcd` — output LCD

### Zewnętrzne
- `gpiozero` — obsługa GPIO (tylko na RPi)
- `pygame` — renderowanie buźki
- `pynput` — obsługa klawiatury (tryb symulacji, opcjonalne)

## Konfiguracja buźki

### Parametry z config/face.toml

Zobacz szczegółową dokumentację: [docs/config/face.md](../config/face.md)

Kluczowe parametry:
- **Idle behavior:** `FACE_IDLE_BLINK_SEC`, `FACE_IDLE_LOOK_P`
- **Emotions:** `mouth_happy_lift_k`, `mouth_sad_lift_k`
- **Gestures:** `FACE_GESTURE_BLINK_DUR`, `FACE_GESTURE_LOOK_T`

## Rozszerzenia (TODO)

- [ ] Obsługa touchscreen (zamiast tylko przycisków)
- [ ] Więcej emocji (surprised, angry, confused)
- [ ] Animowane przejścia między emocjami
- [ ] Konfiguracja pinów GPIO przez TOML

---

**Related docs:**
- [draw.md](draw.md) — prymitywy renderowania buźki
- [hw.md](hw.md) — sink LCD
- [launcher.md](launcher.md) — odbiorcy eventów przycisków
- [docs/config/face.md](../config/face.md) — parametry konfiguracji buźki

**Ostatnia aktualizacja:** 2025-01
