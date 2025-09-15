# Rider‑Pi — UI/Face Architecture (v3.3 — 5 plików: model / renderer / gestures / animator / controller)

*Data owner:* Maciej P.
*Updated:* 2025‑09‑14

---

## Cel

Dodać warstwę **obiektów twarzy (model)**: głowa/owal, oczy, brwi, usta.
Gest = **co** ma się stać (cel/kluczowe klatki), Animator = **jak** przejść w czasie (interpolacja, cross‑fade), Controller = **kiedy** i **dlaczego** (kolejki, polityki: idle/speaking/drowsy), Renderer = rysuje jedną klatkę ze stanu.

---

## Struktura (docelowa)

```
apps/
  ui/
    face/
      __init__.py       # publiczny interfejs
      model.py          # FaceState + obiekty: Head, Eyes, Brows, Mouth
      renderer.py       # rysowanie 1 klatki (STATE → PNG)
      gestures.py       # definicje gestów: keyframes/targets, kanały (eyes/brows/mouth/head)
      animator.py       # silnik czasu: interpolacja, fade in/out, blend/override/queue → STATE
      controller.py     # orkiestracja + POLITYKI (idle/speaking/drowsy), pętla FPS, wywołanie renderera

services/
  api_core/
    face_api.py         # /face/render, /face/gesture, /face/stop, /face/loop, /face/policy

tools/
  face_cli2.py           # PNG/LCD + animacja/gesty/polityki
```

### Jednozdaniowo

* **model.py** – opisuje z czego składa się twarz (Head/Eyes/Brows/Mouth) i agreguje to w `FaceState`.
* **renderer.py** – bierze `FaceState` i rysuje (PIL). Nie zna czasu ani gestów.
* **gestures.py** – zwraca `GestureSpec` (keyframes + kanał). Bez pętli czasu i bez rysowania.
* **animator.py** – trzyma aktywne `GestureSpec` per **kanał** (`eyes`, `brows`, `mouth`, `head`), interpoluje i miksuje → aktualizuje `FaceState`.
* **controller.py** – API i **polityki zachowań** (idle jitter, speaking mouth, drowsy). W każdym ticku pyta animator o stan, aplikuje polityki i woła renderer.

---

## Model obiektów (model.py)

```python
from dataclasses import dataclass

@dataclass
class Head:   tilt: float = 0.0   # -1..+1 (pochylenie) ; opcj. "nod"/"shake" steruje animator
a
@dataclass
class Eyes:   dx: float = 0.0; dy: float = 0.0; blink: float = 0.0  # 0..1
@dataclass
class Brows:  lift: float = 0.0; tilt: float = 0.0                  # -1..+1
@dataclass
class Mouth:  shape: str = "auto"; open: float = 0.0               # 0..1

@dataclass
class FaceState:
    expr: str = "happy"
    head:  Head  = Head()
    eyes:  Eyes  = Eyes()
    brows: Brows = Brows()
    mouth: Mouth = Mouth()
```

> Renderer może też wspierać płaski dostęp (aliasy), ale **źródłem prawdy** jest `FaceState` z obiektami.

**Mapowanie kanałów → obiekty**

* `eyes`  → `FaceState.eyes.{dx,dy,blink}`
* `brows` → `FaceState.brows.{lift,tilt}`
* `mouth` → `FaceState.mouth.{shape,open}`
* `head`  → `FaceState.head.{tilt}` (+ ew. pochodne pod nod/shake)

---

## Gesty (gestures.py)

```python
from .animator import Keyframe, GestureSpec

def blink(duration=0.14) -> GestureSpec:
    return GestureSpec(
        name="blink", channel="eyes",
        frames=[Keyframe(0,{"eyes.blink":0.0}), Keyframe(duration/2,{"eyes.blink":1.0}), Keyframe(duration,{"eyes.blink":0.0})]
    )

def look(dx=0.5, dy=0.0, t=0.25) -> GestureSpec:
    return GestureSpec(
        name="look", channel="eyes",
        frames=[Keyframe(0,{"eyes.dx":0.0,"eyes.dy":0.0}), Keyframe(t,{"eyes.dx":dx,"eyes.dy":dy})],
        fade_in=0.04, fade_out=0.04,
    )

def nod(t=0.6) -> GestureSpec:
    return GestureSpec(
        name="nod", channel="head",
        frames=[Keyframe(0,{"head.tilt":0.0}), Keyframe(t/2,{"head.tilt":0.6}), Keyframe(t,{"head.tilt":0.0})]
    )

GESTURES = {"blink": blink, "look": look, "nod": nod}
```

> **Adresowanie parametru** jako "ścieżka" (`eyes.blink`) pozwala animatorowi aktualizować właściwy obiekt bez dłubania w rendererze.

---

## Animator (animator.py) – przejścia w czasie

* Utrzymuje aktywne gesty per kanał (`eyes`, `brows`, `mouth`, `head`).
* Interpoluje keyframe’y, stosuje `fade_in/fade_out`, **blend/override/queue**.
* Zmiany aplikuje do **właściwych obiektów** w `FaceState` zgodnie ze ścieżkami (`eyes.dx`, `mouth.open`, ...).

Szkic aktualizacji ścieżki:

```python
# wewnątrz Animator.tick():
for path, value in params.items():       # np. 'eyes.dx' = 0.3
    obj, field = path.split('.')         # 'eyes', 'dx'
    setattr(getattr(self.state, obj), field, value)
```

---

## Controller (controller.py) – orkiestracja + POLITYKI

**Odpowiada za:**

* API: `do(name, **kw)`, `stop(channel)`, `set_expr(expr)`, `loop(secs)`.
* **Polityki** (prosta warstwa zachowań):

  * `idle`: losowe mikro‑saccady oczu i sporadyczny blink (tempo z zakresu),
  * `speaking(level)`: otwieranie ust proporcjonalnie do głośności (`mouth.open`),
  * `drowsy(level)`: spowolnione, częstsze blinki, lekkie opadanie powiek (`eyes.blink` bias).
* Kolejność: `state ← animator.tick()` → `apply_policies(state)` → `renderer.render_face(state)`.

**API polityk (propozycja):**

* `set_policy(name: str, on: bool, **kw)` – włącza/wyłącza daną politykę.
* `feed(level: float, kind: str="voice")` – szybkie dane (np. RMS audio → `speaking`).

**Endpointy**

* `POST /face/policy` → `{ name, on, args? }`
* `POST /face/feed`   → `{ kind: "voice", level: 0..1 }`

---

## Renderer (renderer.py)

* Jedyny odpowiedzialny za rysowanie (PIL). Czyta **obiekty** z `FaceState`:

  * Head → obrót/przesunięcie (opcjonalnie),
  * Eyes → białka, źrenice, powieki (z `blink`),
  * Brows → łuki nad oczami (`lift/tilt`),
  * Mouth → kształt (`shape`) i otwarcie (`open`).
* Wejście: `render_face(state: FaceState, size: int) -> bytes` (można zostawić też wariant płaski dla zgodności).

---

## Dlaczego tak?

* **Czytelność**: konkretne obiekty twarzy + jasne kanały zmniejszają sprzężenia.
* **Rozszerzalność**: łatwo dodać `wink_left/right`, `brow_squeeze`, `mouth_smile_amount` bez naruszania innych warstw.
* **Testowalność**: gesty i polityki testujemy jako czyste funkcje/specyfikacje; renderer testujemy pikselowo.

---

## DoD

* Dodanie gestu wymaga tylko edycji **gestures.py**.
* Nowa polityka (np. `listening`) wymaga tylko edycji **controller.py**.
* Renderer działa wyłącznie na `FaceState`/obiektach i nie zawiera logiki czasu.
* Płynne przejścia A→B (fade/blend/override) per kanał, zgodnie z obiektami.

---

## Następne kroki

1. Utworzyć szkielety `model.py`, `gestures.py`, `animator.py`, `controller.py`, `renderer.py` pod powyższe API.
2. W `renderer.py` narysować buźkę 1:1 (parametry zaczerpnąć z legacy).
3. Dodać gesty: `blink`, `look`, `nod`.
4. W `controller.py` zaimplementować polityki `idle`, `speaking(level)`, `drowsy(level)`.
5. Wystawić `/face/policy` i `/face/feed` w `face_api.py`.
6. Dodać testy golden‑master dla renderera oraz proste testy regresji gestów (spójność ścieżek).
