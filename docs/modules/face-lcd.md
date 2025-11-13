# Rider-Pi — FACE (LCD ILI9xx)

Dokument opisuje renderowanie „buźki” na panelu LCD (ILI9xx): tryby, komendy, zmienne środowiskowe, benchmark, recovery i FAQ. Sprawdzone na Raspberry Pi + SPI w repo `Rider-Pi`.

---

## 1) TL;DR — szybki start

```bash
# w repo:
cd ~/robot

# włącz panel i wyczyść (pewne ścieżki „presenter”)
make lcd-on && make lcd-black

# testcard (pasy kontrolne)
make face-testcard \
  || python3 scripts/dev_lcd-testcard.py --rotate 270 --spi-hz 48000000

# RAW (RGB565, fast-path) ~11–15 FPS @ 48–64 MHz
make face-direct-raw EXPR=happy SECS=5
# lub dokładnie ten sam run bez make
sudo -E python3 scripts/dev_face-lcd-direct.py \
  --expr happy --rotate 270 --spi-hz 48000000 \
  --secs 5 --stats --force push_frame:rgb565_3

# jednorazowa klatka przez API (PIL → LCD)
make face-api-lcd
```

---

## 2) Zmienne środowiskowe (kluczowe)

- `FACE_LCD_ROTATE=270` — **wymagane**, aby obraz nie był bokiem.
- `FACE_LCD_SPI_HZ=48000000` — domyślna prędkość (48 MHz).
- `FACE_SPI_SEND=writebytes2` — wymusza szybki tryb wysyłki SPI.
- (Face UX/tuning)
  - `FACE_IDLE_ENABLE=1` — włącz idle mikro-gesty.
  - `FACE_IDLE_BLINK_SEC=3.0` — częstotliwość mrugnięć.
  - `FACE_IDLE_LOOK_P=0.22` / `FACE_IDLE_LOOK_SEC=3.4` — spontaniczne spojrzenia.
  - `FACE_GESTURE_LOOK_AMP=0.32` — amplituda gesta look.
  - `FACE_EYES_FOLLOW_KX=0.12` `FACE_EYES_FOLLOW_KY=0.22` — tłumienie ruchów oczu.
  - `FACE_BROW_FOLLOW_KX=0.06` `FACE_BROW_FOLLOW_KY=0.10` — tłumienie brwi.
  - `FACE_PUPIL_DRIFT_AMP_K=0.02` `FACE_PUPIL_DRIFT_FREQ=0.8` — mikrodryf źrenic.

Ustaw na stałe (opcjonalnie):

```bash
grep -q 'FACE_LCD_ROTATE' ~/.bashrc || {
  echo 'export FACE_LCD_ROTATE=270' >> ~/.bashrc
  echo 'export FACE_LCD_SPI_HZ=48000000' >> ~/.bashrc
  echo 'export FACE_SPI_SEND=writebytes2' >> ~/.bashrc
}
source ~/.bashrc
```

---

## 3) Cele `make` (kanoniczne)

- `make lcd-on` — wyjście ze snu (DISP_ON).
- `make lcd-off` — uśpienie (DISP_OFF + sleep).
- `make lcd-black` — czarne wypełnienie (presenter).
- `make face-testcard` — pasy testowe (presenter).
- `make face-direct-raw EXPR=happy SECS=5` — szybki renderer RAW (RGB565).
- `make face-api-png` — wyrenderuj PNG do `/tmp/face_api.png`.
- `make face-api-lcd` — jednorazowy push przez API na LCD.
- `make face-bench` — mini‑benchmark FPS (32/48/64 MHz).
- `make lcd-recover` — twarde przywrócenie panelu.

> Wszystkie cele respektują `FACE_LCD_ROTATE` i `FACE_LCD_SPI_HZ`.

---

## 4) Tryby renderowania

### 4.1) Presenter (pewny)
Najprostsza, niezależna od reszty stosu.

```bash
python3 scripts/dev_lcd-testcard.py --rotate 270 --spi-hz 48000000
python3 scripts/dev_lcd-clear.py
```

### 4.2) RAW (RGB565, bezpośredni push)
Szybka ścieżka z konwersją w C (`fast565`).

```bash
sudo -E python3 scripts/dev_face-lcd-direct.py \
  --expr happy --rotate 270 --spi-hz 48000000 \
  --secs 5 --stats --force push_frame:rgb565_3
```
W logu szukaj:

```
LCD(direct): FORCED LCDRenderer.push_frame[rgb565_3]
[enc] fast565 C extension
[spi] requested_hz=48000000 actual_hz=48000000 mode=0 bpw=8
[raw] path=writebytes2
```

### 4.3) API → PIL → LCD (pojedyncza klatka)

```bash
python3 - <<'PY'
from services.api_core import face_api
print(face_api.render(backend="lcd", expr="happy", size=240, rotate=270, spi_hz=48000000))
PY
```
W logach: `LCD(direct): using LCDRenderer.ShowImage[pil]`.

---

## 5) Benchmark

Szybkie porównanie częstotliwości SPI:

```bash
make face-bench                      # 32/48/64 MHz
HZ_LIST="48000000" SECS=6 make face-bench
```

**Przykładowe wyniki (ROT=270):**

- 32 MHz: ~8–9 FPS
- 48 MHz: ~9–11 FPS
- 64 MHz: ~12–13 FPS

W RAW bez dodatkowych obciążeń osiągaliśmy do ~15 FPS (zależnie od sceny).

---

## 6) Recovery (gdy ekran „wariuje” / czarny / śmieci)

1. Zatrzymaj wszystko, co dotyka LCD/SPI:

```bash
make vendor-kill || true
make preview-off || true
make vision-off  || true
make stop-all    || true
```

2. Twardy reset + czyszczenie:

```bash
sudo -E python3 scripts/sys_lcd-control.py off    || true; sleep 0.2
sudo -E python3 scripts/sys_lcd-control.py reset  || true; sleep 0.2
sudo -E python3 scripts/sys_lcd-control.py on     || true
python3 scripts/dev_lcd-clear.py   || true
```

> Albo: `make lcd-recover`

3. Test ścieżką pewną, potem API:

```bash
python3 scripts/dev_lcd-testcard.py --rotate 270 --spi-hz 48000000
python3 - <<'PY'
from services.api_core import face_api
print(face_api.render(backend="lcd", expr="happy", size=240, rotate=270, spi_hz=48000000))
PY
```

---

## 7) Typowe objawy i szybkie fixy

- **Buźka bokiem** → ustaw `FACE_LCD_ROTATE=270`.
- **Czarny/śmieci po chwili** → `make lcd-recover`; sprawdź, czy nic innego nie trzyma SPI.
- **„Message too long” / fdwrite** → `FACE_SPI_SEND=writebytes2`.
- **RAW wolny** → upewnij się, że log ma `[enc] fast565 C extension`.
- **FPS nie rośnie przy 64 MHz** → to bywa normalne dla danej sceny/ścieżki.

---

## 8) Notatki implementacyjne

- Sterownik: `apps/ui/face/driver_ili9xx.py`.
- Domyślny HZ:

```py
_DEF_HZ = int(os.getenv("FACE_LCD_SPI_HZ", "48000000") or 0) or 48000000
```

- RAW używa konwersji RGB24→RGB565 w C (`fast565`), co redukuje czas enkodowania klatki do ~3 ms (vs ~230 ms w Python/NumPy na Pi).
- Renderer twarzy:
  - Brwi (arc) i usta (wstążka) przywrócone do klasycznego wyglądu.
  - Źrenice: drift + clamp, sprzęgło blink→look.
  - Pokrętła follow (oczy/brwi) przez ENV wg sekcji **2**.

---

## 9) Checklist „działa / nie działa”

- [x] `make lcd-on && make lcd-black` nie zgłasza błędów
- [x] `make face-testcard` pokazuje pasy
- [x] `make face-api-lcd` rysuje poprawną buźkę (PIL‑path)
- [x] `make face-direct-raw EXPR=happy SECS=5` trzyma ~11–15 FPS (log: `fast565` + `writebytes2`)
- [x] Wszędzie `rotate=270`

---



## 10) FAQ

**Czy 64 MHz zawsze da więcej FPS?**  
Zwykle tak, ale przy niektórych scenach/ścieżkach różnice mogą się spłaszczać.

**Dlaczego PIL‑path bywa wolniejszy niż RAW?**  
PIL rysuje pewnie i uniwersalnie, RAW idzie bezpośrednio w RGB565 + SPI.

**Skąd wiem, która ścieżka poszła?**  
Z logów: `LCDRenderer.ShowImage[pil]` (PIL) vs `LCDRenderer.push_frame[rgb565_3]` (RAW).

---

### Załącznik: szybki demo‑run z tuningiem mimiki

```bash
sudo -E env -u FACE_MOUTH_SHAPE -u FACE_MOUTH_OPEN \
  FACE_IDLE_ENABLE=1 FACE_IDLE_BLINK_SEC=3.4 FACE_IDLE_LOOK_P=0.22 FACE_IDLE_LOOK_SEC=3.4 \
  FACE_GESTURE_LOOK_AMP=0.32 \
  FACE_EYES_FOLLOW_KX=0.12 FACE_EYES_FOLLOW_KY=0.22 \
  FACE_BROW_FOLLOW_KX=0.06 FACE_BROW_FOLLOW_KY=0.10 \
  FACE_PUPIL_DRIFT_AMP_K=0.02 FACE_PUPIL_DRIFT_FREQ=0.8 \
  python3 scripts/dev_face-lcd-direct.py \
    --expr neutral --fps 20 --rotate 270 --spi-hz 32000000 \
    --secs 8 --stats
```
