# Moduł HW (`apps/hw`)

## Opis

Moduł `apps/hw` zawiera **sink LCD** — niskopoziomowy driver do wyświetlania pygame Surface na fizycznym wyświetlaczu LCD przez framebuffer.

### Główny plik

- **`sink_lcd.py`** — sink do `/dev/fb*` framebuffer

## Główne funkcje

### `sink_lcd.LCDSink`

Klasa do wyświetlania pygame Surface na LCD.

#### Metody

- **`__init__(device='/dev/fb0', rotation=0)`** — inicjalizacja sink
- **`blit(surface)`** — wyświetlenie Surface na LCD
- **`clear(color=(0, 0, 0))`** — wyczyszczenie ekranu
- **`close()`** — zamknięcie urządzenia

## Przepływ danych

```
pygame.Surface (320×240, RGB)
    ↓
LCDSink.blit(surface)
    ↓
Konwersja RGB → format framebuffera (RGB565/RGB888)
    ↓
Zapis do /dev/fb0 (lub /dev/fb1)
    ↓
Fizyczny wyświetlacz LCD
```

## Konfiguracja

### Zmienne środowiskowe

| ENV | Typ | Domyślna | Opis |
|-----|-----|----------|------|
| `LCD_DEVICE` | str | `/dev/fb0` | Ścieżka do urządzenia framebuffer |
| `LCD_ROTATION` | int | `0` | Rotacja wyświetlacza (0, 90, 180, 270) |
| `LCD_WIDTH` | int | `320` | Szerokość LCD (px) |
| `LCD_HEIGHT` | int | `240` | Wysokość LCD (px) |

⚠️ **Uwaga:** Część parametrów może być hardcoded — wymaga weryfikacji kodu źródłowego.

## Przykład użycia

### Podstawowe wyświetlanie

```python
import pygame
from apps.hw.sink_lcd import LCDSink

pygame.init()
surface = pygame.Surface((320, 240))
surface.fill((255, 0, 0))  # czerwony ekran

sink = LCDSink(device='/dev/fb0')
sink.blit(surface)
sink.close()
```

### Integracja z face renderer

```python
from apps.draw.face_primitives import draw_face
from apps.hw.sink_lcd import LCDSink
import pygame

pygame.init()
surface = pygame.Surface((320, 240))
sink = LCDSink()

while True:
    draw_face(surface, emotion="happy", gaze=(0, 0), blink=0, mouth_open=0.5)
    sink.blit(surface)
    pygame.time.wait(33)  # ~30 FPS
```

### Rotacja wyświetlacza

```python
# Wyświetlacz montowany do góry nogami
sink = LCDSink(device='/dev/fb0', rotation=180)
```

## Obsługiwane urządzenia

### Framebuffer devices
- `/dev/fb0` — główny framebuffer (HDMI/DSI)
- `/dev/fb1` — wtórny framebuffer (SPI LCD, np. ILI9341)

### Formaty pikseli
- **RGB565** — 16-bit (5R, 6G, 5B) — typowe dla SPI LCD
- **RGB888** — 24-bit (8R, 8G, 8B) — HDMI/DSI
- **BGR888** — 24-bit odwrócony (niektóre panele)

## Diagnostyka

### Sprawdzenie framebuffera

```bash
# Lista urządzeń framebuffer
ls -la /dev/fb*

# Informacje o framebufferze
fbset -i

# Test zapisu (noise)
cat /dev/urandom | head -c $((320*240*2)) > /dev/fb1
```

### Typowe problemy

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Brak obrazu | Złe urządzenie (`/dev/fb0` vs `/dev/fb1`) | Sprawdź `fbset -i`, użyj właściwego fb |
| Zniekształcone kolory | Niewłaściwy format pikseli | Konwertuj RGB→RGB565 lub BGR |
| Obraz do góry nogami | Brak rotacji | Ustaw `rotation=180` |
| Błąd "Permission denied" | Brak uprawnień | Uruchom jako `sudo` lub dodaj użytkownika do grupy `video` |

### Debugowanie

```python
# Sprawdź format framebuffera
import os
with open('/dev/fb0', 'rb') as f:
    # Odczytaj header (wymaga znajomości struktury fb)
    pass

# Test prostego wypełnienia
with open('/dev/fb1', 'wb') as f:
    # Czerwony ekran (RGB565: 0xF800)
    f.write(b'\x00\xF8' * (320 * 240))
```

## Alternatywy

### Pygame display (HDMI)
Jeśli używasz HDMI, możesz użyć standardowego `pygame.display`:

```python
screen = pygame.display.set_mode((320, 240))
# Brak potrzeby LCDSink — pygame obsługuje framebuffer automatycznie
```

### SDL_FBDEV
Ustaw ENV dla pygame aby używał framebuffer device:

```bash
export SDL_FBDEV=/dev/fb1
export SDL_VIDEODRIVER=fbcon
python my_app.py
```

## Wydajność

### Benchmark

Typowa wydajność na Raspberry Pi 4:
- **RGB565 (320×240):** ~60 FPS
- **RGB888 (320×240):** ~50 FPS
- **RGB888 (640×480):** ~25 FPS

### Optymalizacja

- Użyj RGB565 dla SPI LCD (mniejsze bufory)
- Ogranicz częstotliwość odświeżania (30 FPS wystarczy dla buźki)
- Renderuj tylko zmienione obszary (dirty rect)

## Zależności

### Wewnętrzne (w repo)
- `apps.draw.face_primitives` — źródło Surface do wyświetlenia

### Zewnętrzne
- `pygame` — renderowanie Surface
- `/dev/fb*` — Linux framebuffer device (kernel)

## Rozszerzenia (TODO)

- [ ] Automatyczna detekcja formatu framebuffera
- [ ] Partial updates (dirty regions) dla wydajności
- [ ] Podwójne buforowanie (double buffering)
- [ ] Wsparcie dla DRM/KMS (zamiast /dev/fb)

---

**Related docs:**
- [draw.md](draw.md) — prymitywy renderowania
- [ui.md](ui.md) — kontroler buźki
- [face-lcd.md](./face-lcd.md) — rendering na LCD

**Ostatnia aktualizacja:** 2025-01
