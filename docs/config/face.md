# Konfiguracja Face (`face.toml`)

## Opis

Plik `config/face.toml` zawiera **parametry renderowania buźki** robota — geometria, emocje, animacje, idle behavior.

## Struktura pliku

### Sekcje

1. **Idle / mikro-gesty** — automatyczne ruchy (mrugnięcia, spojrzenia)
2. **Blink choreografia** — parametry mrugnięć
3. **Look parametry** — ruch oczu/spojrzenia
4. **Przejścia nastrojów** — animacje między emocjami
5. **Renderer** — parametry geometrii (oczy, usta, brwi)
6. **Legacy aliasy** — kompatybilność wsteczna (ENV)

---

## Parametry

### Idle / mikro-gesty

Parametry używane przez kontroler buźki dla automatycznych ruchów.

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `FACE_IDLE_BLINK_SEC` | float | `3.0` | Interwał mrugania (s) |
| `FACE_IDLE_SOFT_BLINK_SEC` | float | `0.0` | Interwał "miękkiego" mrugania (0 = wyłączone) |
| `FACE_IDLE_LOOK_P` | float | `0.35` | Prawdopodobieństwo "spojrzenia" (0–1) |
| `FACE_IDLE_LOOK_SEC` | float | `3.0` | Interwał sprawdzania spojrzenia (s) |
| `FACE_IDLE_JITTER` | float | `0.15` | Amplituda jitter (subtelne ruchy) |

**Przykład:**
- Co 3s robot mru­gnie
- Co 3s z 35% szansą zmieni kierunek spojrzenia
- Jitter 0.15 → subtelny "drift" źrenic

### Blink choreografia

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `FACE_GESTURE_BLINK_DUR` | float | `0.16` | Czas trwania mrugnięcia (s) |
| `FACE_GESTURE_BLINK_HOLD` | float | `0.02` | Czas zamknięcia oka (s) |

### Look parametry

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `FACE_GESTURE_LOOK_T` | float | `0.55` | Czas przejścia spojrzenia (s) |
| `FACE_GESTURE_LOOK_AMP` | float | `0.42` | Amplituda spojrzenia (0–1) |

### Przejścia nastrojów

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `FACE_TRANS_STEP_S` | float | `0.30` | Krok animacji przejścia (s) |
| `FACE_TRANS_DWELL_S` | float | `0.14` | Czas zatrzymania w klatce (s) |

---

## Renderer (klucze lowercase)

Parametry geometrii używane **bezpośrednio** przez `draw_face()`.

### Głowa / układ

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `head_ky` | float | `1.04` | Skalowanie wysokości głowy |

### Brwi

| Klucz | Typ | Zakres | Domyślna | Opis |
|-------|-----|--------|----------|------|
| `brow_y_k` | float | 0–0.3 | `0.21` | Wysokość brwi (ułamek S) |
| `brow_h_k` | float | — | `0.09` | Promień pionowy łuku brwi |

### Usta — profil "wstążki"

| Klucz | Typ | Zakres | Domyślna | Opis |
|-------|-----|--------|----------|------|
| `mouth_ribbon_taper_k` | float | 0–1 | `0.60` | Zwężenie końców wstążki |
| `mouth_small_th_k_base` | float | — | `0.050` | Bazowa grubość przy małym otwarciu |

### Pozycja ust

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `mouth_y_k` | float | `0.215` | Pozycja Y środka ust (ułamek S) |

### Parametry per emocja

#### Happy (szczęśliwy)

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `mouth_happy_lift_k` | float | `0.045` | Uniesienie kącików ust |
| `mouth_happy_arch_k` | float | `0.030` | Łuk środka ust (do góry) |

#### Neutral (neutralny)

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `mouth_neutral_lift_k` | float | `0.000` | Brak uniesienia |
| `mouth_neutral_arch_k` | float | `0.000` | Brak łuku |

#### Sad (smutny)

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `mouth_sad_lift_k` | float | `-0.045` | Opuszczenie kącików |
| `mouth_sad_arch_k` | float | `-0.030` | Łuk do dołu |

### Oczy

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `eyes_follow_kx` | float | `0.10` | Podążanie białka za spojrzeniem (X) |
| `eyes_follow_ky` | float | `0.18` | Podążanie białka za spojrzeniem (Y) |

### Brwi podążanie

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `brow_follow_kx` | float | `0.10` | Podążanie brwi za spojrzeniem (X) |
| `brow_follow_ky` | float | `0.10` | Podążanie brwi za spojrzeniem (Y) |

### Źrenice (drift)

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `FACE_PUPIL_DRIFT_AMP_K` | float | `0.04` | Amplituda drift źrenic |
| `FACE_PUPIL_DRIFT_FREQ` | float | `0.8` | Częstotliwość oscylacji (Hz) |
| `FACE_PUPIL_CLAMP_RATIO` | float | `0.78` | Clamp źrenic (proporcja do oka) |

### Sprzęgło blink↔gaze

| Klucz | Typ | Domyślna | Opis |
|-------|-----|----------|------|
| `FACE_BLINK_SHIFT_PROB` | float | `0.12` | Prawdopodobieństwo zmiany spojrzenia przy mrugnięciu |

---

## Legacy / aliasy (ENV)

Dla kompatybilności wstecznej — można nadal używać jako ENV.

### Usta — wstążka

```toml
FACE_MOUTH_RIBBON_TAPER_K   = 0.60
FACE_MOUTH_RIBBON_SAMPLES   = 48  # liczba punktów krzywej
```

### Grubość ust per emocja

```toml
FACE_MOUTH_SMALL_TH_K_BASE    = 0.050
FACE_MOUTH_SMALL_TH_K_HAPPY   = 0.95
FACE_MOUTH_SMALL_TH_K_NEUTRAL = 0.85
FACE_MOUTH_SMALL_TH_K_SAD     = 1.05
```

### Pozycje Y per emocja

```toml
FACE_MOUTH_Y_OFFSET_K_HAPPY   = 0.040
FACE_MOUTH_Y_OFFSET_K_NEUTRAL = 0.050
FACE_MOUTH_Y_OFFSET_K_SAD     = 0.050
```

### Debug

```toml
FACE_DEBUG_MOUTH = 0  # 1 = pokaż linie pomocnicze
```

---

## Przykłady konfiguracji

### Minimalna (tylko kluczowe)

```toml
[renderer]
mouth_happy_lift_k = 0.045
mouth_sad_lift_k = -0.045
brow_y_k = 0.21
```

### Większy uśmiech

```toml
mouth_happy_lift_k = 0.060    # +33% vs. domyślne
mouth_happy_arch_k = 0.040    # +33%
```

### Wyższe brwi (zdziwienie)

```toml
brow_y_k = 0.25  # wyżej vs. 0.21
```

### Szybsze mrugnięcia

```toml
FACE_IDLE_BLINK_SEC = 2.0      # co 2s vs. 3s
FACE_GESTURE_BLINK_DUR = 0.12  # szybsze mrugnięcie
```

### Debug renderingu

```toml
FACE_DEBUG_MOUTH = 1  # pokaż geometrię pomocniczą
```

---

## Używanie konfiguracji

### Przez ENV (legacy)

```bash
export FACE_MOUTH_HAPPY_LIFT_K=0.060
python -m apps.ui.face
```

### Przez TOML (nowoczesne)

```python
import tomli

with open("config/face.toml", "rb") as f:
    cfg = tomli.load(f)

# Użyj w rendererze
from apps.draw.face_primitives import draw_face

draw_face(surface, emotion="happy",
          mouth_happy_lift_k=cfg["mouth_happy_lift_k"],
          brow_y_k=cfg["brow_y_k"])
```

### Przez kontroler

```python
from apps.ui.face_core import FaceController

controller = FaceController(config_path="config/face.toml")
controller.set_emotion("happy")
```

---

## Dostrajanie parametrów

### Workflow

1. **Backup:** Skopiuj `config/face.toml` do `config/local/face_dev.toml`
2. **Edytuj:** Zmień parametry w `face_dev.toml`
3. **Testuj:** Uruchom renderer z nową konfiguracją
4. **Iteruj:** Dostosuj wartości, obserwuj wynik
5. **Commit:** Jeśli OK, przenieś do głównego `face.toml`

### Szybki test

```bash
# Terminal 1: uruchom face z custom config
python -c "
from apps.ui.face_core import FaceController
controller = FaceController(config_path='config/local/face_dev.toml')
controller.set_emotion('happy')
input('Press Enter to exit...')
"

# Terminal 2: edytuj config
nano config/local/face_dev.toml
# (zapisz, wróć do Terminal 1, restart)
```

---

## Diagnostyka

### Problem: Usta nie renderują się poprawnie

**Sprawdź:**
- `mouth_y_k` — czy w zakresie 0.1–0.3?
- `mouth_ribbon_taper_k` — czy w zakresie 0.5–0.8?
- `FACE_DEBUG_MOUTH = 1` — włącz debug

### Problem: Brwi zbyt nisko/wysoko

**Dostosuj:**
- `brow_y_k`: zwiększ (wyżej) lub zmniejsz (niżej)

### Problem: Źrenice "uciekają" poza oko

**Dostosuj:**
- `FACE_PUPIL_CLAMP_RATIO`: zwiększ (0.8–0.9 = mocniejszy clamp)

---

**Related docs:**
- [docs/apps/draw.md](../apps/draw.md) — prymitywy renderowania
- [docs/apps/ui.md](../apps/ui.md) — kontroler buźki
- [docs/modules/face.md](../apps/face.md) — API buźki

**Ostatnia aktualizacja:** 2025-01
