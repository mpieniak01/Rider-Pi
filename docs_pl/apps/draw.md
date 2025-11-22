# Moduł Draw (`apps/draw`)

## Opis

Moduł `apps/draw` zawiera **prymitywy renderowania buźki** — niskopoziomowe funkcje rysowania oczu, ust, brwi i elementów twarzy robota.

### Główne pliki

- **`face_primitives.py`** — prymitywy geometryczne (arc, ellipse, ribbon, eyes)
- **`face_renderer.py`** — fasada API renderingu
- **`face_emotions.py`** — mapowanie emocji na parametry buźki

## Główne funkcje (face_primitives.py)

### Oczy
- **`draw_eye_arc(...)`** — oko w stylu "arc" (łuk)
- **`draw_eye_ellipse(...)`** — oko eliptyczne
- **`draw_pupils(...)`** — źrenice z driftem

### Usta
- **`draw_mouth_ribbon(...)`** — usta w stylu "wstążki" (ribbon)
- **`_ribbon_shape(...)`** — obliczanie krzywej ust

### Brwi
- **`draw_eyebrows_arc(...)`** — brwi jako łuki

### Tło i helpers
- **`clear_face(surface, color)`** — wyczyszczenie powierzchni
- **`_arc_points(...)`** — generowanie punktów łuku

## Przepływ renderingu

```
Emotion (happy/neutral/sad) + parametry (gaze, blink, mouth_open)
    ↓
face_renderer.draw_face(surface, emotion, gaze, blink, mouth_open, **params)
    ↓
face_primitives.draw_eye_arc/ellipse + draw_mouth_ribbon + draw_eyebrows_arc
    ↓
pygame.Surface (bufor) → sink_lcd → /dev/fb0 (LCD)
```

## Parametry renderingu

### Kluczowe parametry (z config/face.toml)

| Parametr | Typ | Domyślna | Opis |
|----------|-----|----------|------|
| `head_ky` | float | `1.04` | Skalowanie wysokości głowy |
| `brow_y_k` | float | `0.21` | Wysokość brwi (0–0.3) |
| `brow_h_k` | float | `0.09` | Promień pionowy łuku brwi |
| `mouth_y_k` | float | `0.215` | Pozycja Y środka ust |
| `mouth_ribbon_taper_k` | float | `0.60` | Zwężenie końców wstążki ust |
| `eyes_follow_kx` | float | `0.10` | Podążanie oczu za spojrzeniem (X) |
| `eyes_follow_ky` | float | `0.18` | Podążanie oczu za spojrzeniem (Y) |

### Parametry per emocja

#### Happy (szczęśliwy)
- `mouth_happy_lift_k = 0.045` — uniesienie kącików ust
- `mouth_happy_arch_k = 0.030` — łuk środka ust

#### Neutral (neutralny)
- `mouth_neutral_lift_k = 0.000`
- `mouth_neutral_arch_k = 0.000`

#### Sad (smutny)
- `mouth_sad_lift_k = -0.045` — opuszczenie kącików ust
- `mouth_sad_arch_k = -0.030` — odwrócony łuk

## Styl renderingu

### Arc (łuki)
Oczy i brwi renderowane jako **łuki** zamiast pełnych elips — minimalistyczny, nowoczesny styl.

### Ribbon (wstążka)
Usta renderowane jako **wstążka** z parametrycznym zwężeniem końców (`taper_k`).

### Drift źrenic
Źrenice mają subtelny **drift** (oscylacja sinusoidalna) dla efektu "żywych oczu":
```python
drift_amp = FACE_PUPIL_DRIFT_AMP_K  # 0.04
drift_freq = FACE_PUPIL_DRIFT_FREQ  # 0.8 Hz
```

## Przykład użycia

### Standalone rendering (pygame)

```python
import pygame
from apps.draw.face_primitives import draw_face

pygame.init()
surface = pygame.display.set_mode((320, 240))

# Parametry
emotion = "happy"
gaze = (0.0, 0.0)  # środek
blink = 0.0        # oczy otwarte
mouth_open = 0.3   # lekko otwarte usta

# Render
draw_face(surface, emotion, gaze, blink, mouth_open, S=120)
pygame.display.flip()
```

### Integracja z UI (face controller)

```python
from apps.ui.face_core import FaceController

controller = FaceController()
controller.set_emotion("happy")
controller.look_at(0.2, 0.1)  # spojrzenie w prawo-górę
controller.blink()            # mrugnięcie
```

## Konfiguracja

### Ładowanie z TOML

```python
import os
import tomli

with open("config/face.toml", "rb") as f:
    cfg = tomli.load(f)

# Użyj w rendererze
draw_face(surface, emotion, gaze, blink, mouth_open,
          head_ky=cfg["head_ky"],
          brow_y_k=cfg["brow_y_k"],
          mouth_y_k=cfg["mouth_y_k"])
```

### Konfiguracja przez ENV (legacy)

```bash
export FACE_MOUTH_HAPPY_LIFT_K=0.050
export FACE_PUPIL_DRIFT_AMP_K=0.05
python -m apps.ui.face
```

Zobacz: [docs/config/face.md](../config/face.md)

## Zależności

### Wewnętrzne (w repo)
- `apps.hw.sink_lcd` — output do LCD framebuffer
- `apps.ui.face_core` — kontroler wysokiego poziomu

### Zewnętrzne
- `pygame` — renderowanie 2D (Surface, draw primitives)
- `numpy` — obliczenia geometrii (opcjonalne dla zaawansowanych efektów)

## Diagnostyka

### Debug mouth rendering

```bash
export FACE_DEBUG_MOUTH=1
python -m apps.ui.face
```

Wyświetli dodatkowe linie pomocnicze dla debugowania geometrii ust.

### Benchmark renderingu

```python
import time
from apps.draw.face_primitives import draw_face

start = time.time()
for _ in range(100):
    draw_face(surface, "happy", (0, 0), 0, 0.5, S=120)
elapsed = time.time() - start
print(f"FPS: {100/elapsed:.1f}")
```

## Rozszerzenia (TODO)

- [ ] Więcej stylów oczu (circle, cat, robot)
- [ ] Animacje przejść (smooth transitions)
- [ ] Particle effects (sparkles, tears)
- [ ] Konfiguracja kolorów (obecnie hardcoded white/black)

---

**Related docs:**
- [ui.md](ui.md) — kontroler buźki (high-level API)
- [hw.md](hw.md) — sink LCD (output)
- [docs/config/face.md](../config/face.md) — parametry konfiguracji
- [face.md](./face.md) — API statycznego renderu

**Ostatnia aktualizacja:** 2025-01
