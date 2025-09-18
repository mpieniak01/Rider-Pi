# Rider-Pi — FACE (LCD ILI9xx) – przewodnik

Dokument opisuje renderowanie „buźki” na panelu LCD (ILI9xx) – tryby, komendy, typowe problemy i szybkie procedury recovery. Sprawdzone na Raspberry Pi + SPI, w repo `Rider-Pi`.

---

## 1. TL;DR – szybki start

```sh
# w repo:
cd ~/robot

# włącz i wyczyść panel (pewne ścieżki „presenter”)
make lcd-on && make lcd-black

# testcard (pasy kontrolne) — alternatywnie bez make:
make face-testcard || python3 tools/lcd_presenter_testcard.py --rotate 270 --spi-hz 48000000

# RAW (RGB565, fast path) ~11–15 FPS @ 48–64 MHz:
make face-direct-raw EXPR=happy SECS=5
# (albo dokładnie ten sam run bez make)
sudo -E python3 tools/newface_lcd_direct.py --expr happy --rotate 270 --spi-hz 48000000 --secs 5 --stats --force push_frame:rgb565_3

# jednorazowa klatka przez API (pewna ścieżka PIL→LCD)
make face-api-lcd
```

---

## 2. Zmienne środowiskowe i domyślne ustawienia

- `FACE_LCD_ROTATE=270` — **wymagana** rotacja, żeby obraz nie był bokiem.
- `FACE_LCD_SPI_HZ=48000000` (domyślnie z Makefile i drivera).
- `FACE_SPI_SEND=writebytes2` — wymusza wysyłkę SPI optymalną metodą (bez listy intów).

Ustaw na stałe (opcjonalnie):
```sh
grep -q 'FACE_LCD_ROTATE' ~/.bashrc || {
  echo 'export FACE_LCD_ROTATE=270' >> ~/.bashrc
  echo 'export FACE_LCD_SPI_HZ=48000000' >> ~/.bashrc
  echo 'export FACE_SPI_SEND=writebytes2' >> ~/.bashrc
}
source ~/.bashrc
```

---

## 3. Cele `make` (kanoniczne)

- `make lcd-on` — wyjście ze snu (DISP_ON).
- `make lcd-off` — uśpienie (DISP_OFF + sleep).
- `make lcd-black` — czarne wypełnienie (prezenter).
- `make face-testcard` — pasy testowe (prezenter).
- `make face-direct-raw EXPR=happy SECS=5` — szybki renderer RAW (RGB565).
- `make face-api-png` — wyrenderuj PNG do `/tmp/face_api.png`.
- `make face-api-lcd` — jednorazowy push przez API na LCD.
- `make face-bench` — mini-benchmark FPS (domyślnie 32/48/64 MHz).
- `make lcd-recover` — sekwencja „twardego” przywrócenia panelu.

> Wszystkie cele respektują `FACE_LCD_ROTATE` i `FACE_LCD_SPI_HZ`.

---

## 4. Tryby renderowania

### 4.1. „Presenter” (pewny)
Najbardziej niezawodna ścieżka do podstawowych testów:
```sh
python3 tools/lcd_presenter_testcard.py --rotate 270 --spi-hz 48000000
python3 tools/lcd_presenter_clear.py
```
Daje obraz kontrolny / czarną ramkę bez zależności od reszty stosu.

### 4.2. RAW (bezpośredni push RGB565)
Szybki path z konwersją do RGB565 w C (moduł `fast565`):
```sh
sudo -E python3 tools/newface_lcd_direct.py \
  --expr happy --rotate 270 --spi-hz 48000000 --secs 5 --stats \
  --force push_frame:rgb565_3
```
- Przy 48–64 MHz typowo ~11–15 FPS (próbki z logów).
- W logu szukaj:  
  `LCD(direct): FORCED LCDRenderer.push_frame[rgb565_3]`  
  `[enc] fast565 C extension`  
  `[spi] requested_hz=48000000 actual_hz=48000000 mode=0 bpw=8`  
  `[raw] path=writebytes2`

### 4.3. API → PIL → LCD (jedna klatka)
Najprostsza ścieżka „użytkowa”, pewna pod kątem rotacji:
```sh
python3 - <<'PY'
from services.api_core import face_api
print(face_api.render(backend="lcd", expr="happy", size=240, rotate=270, spi_hz=48000000))
PY
```
W logu: `LCD(direct): using LCDRenderer.ShowImage[pil]`

---

## 5. Benchmark

Szybki sweep dla wybranych częstotliwości:
```sh
make face-bench                      # 32/48/64 MHz
HZ_LIST="48000000" SECS=6 make face-bench
```
Przykładowe wyniki (ROT=270):
- 32 MHz: ~8–9 FPS
- 48 MHz: ~9–11 FPS
- 64 MHz: ~12–13 FPS  
W RAW bez ograniczeń dodatkowych uzyskaliśmy do ~15 FPS (zależnie od sceny).

---

## 6. Recovery (gdy ekran „wariuje” / czarny / śmieci)

1) Zatrzymaj wszystko, co dotyka LCD/SPI:
```sh
make vendor-kill || true
make preview-off || true
make vision-off  || true
make stop-all    || true
```

2) Twardy reset panelu + czyszczenie:
```sh
sudo -E python3 tools/lcdctl.py off    || true; sleep 0.2
sudo -E python3 tools/lcdctl.py reset  || true; sleep 0.2
sudo -E python3 tools/lcdctl.py on     || true
python3 tools/lcd_presenter_clear.py   || true
```
(Albo wygodnie: `make lcd-recover`)

3) Testy pewną ścieżką:
```sh
python3 tools/lcd_presenter_testcard.py --rotate 270 --spi-hz 48000000
python3 - <<'PY'
from services.api_core import face_api
print(face_api.render(backend="lcd", expr="happy", size=240, rotate=270, spi_hz=48000000))
PY
```

---

## 7. Typowe objawy i rozwiązania

- **Buźka bokiem**  
  Ustaw `FACE_LCD_ROTATE=270` (globalnie w `~/.bashrc` albo przy wywołaniu make/py).

- **Czarny ekran / śmieci po chwili**  
  Zrób `make lcd-recover`, potem przetestuj **presenterem** (testcard/clear).  
  Upewnij się, że żaden inny proces nie trzyma SPI (vendor, preview, vision).

- **„Message too long” / błąd fdwrite**  
  Wymuś ścieżkę wysyłki: `FACE_SPI_SEND=writebytes2` (jest domyślnie preferowana).

- **Wydajność słaba przy RAW**  
  Sprawdź, że w logu jest `[enc] fast565 C extension`. Jeśli nie — zbuduj moduł (jest już w repo; przy aktualnym stanie masz `fast565` aktywny).

- **Różnice FPS dla 32/48/64 MHz**  
  To normalne – przepustowość SPI i decoder sceny wpływają na wynik.

---

## 8. Notatki implementacyjne

- Sterownik: `apps/ui/face/driver_ili9xx.py` – domyślny HZ = **48 MHz**:
  ```py
  _DEF_HZ = int(os.getenv("FACE_LCD_SPI_HZ", "48000000") or 0) or 48000000
  ```
- Logger SPI pokazuje realny `max_speed_hz` np.:
  ```
  [spi] requested_hz=48000000 actual_hz=48000000 mode=0 bpw=8
  ```
- RAW używa konwersji RGB24→RGB565 w C (`fast565`), co redukuje czas enkodowania klatki do ~3 ms (zamiast ~230 ms w Python/NumPy na Pi).

---

## 9. Checklist „działa / nie działa”

- [x] `make lcd-on && make lcd-black` działa i nie wywala błędów.  
- [x] `make face-testcard` pokazuje pasy.  
- [x] `make face-api-lcd` rysuje poprawną buźkę (PIL path).  
- [x] `make face-direct-raw EXPR=happy SECS=5` trzyma ~11–15 FPS (w logu `fast565` + `writebytes2`).  
- [x] Wszędzie używasz `rotate=270`.  

---

## 10. Ignorowanie artefaktów buildu (już w repo)

`.gitignore` zawiera m.in.:
```
*.so
build/
dist/
*.egg-info/
__pycache__/
.pytest_cache/
*.pyc
*.pyo
```

---

## 11. FAQ

**P: Czy 64 MHz zawsze da więcej FPS?**  
O: Zwykle tak, ale przy niektórych scenach/ścieżkach różnice mogą się spłaszczać.

**P: Czemu PIL-path bywa wolniejszy niż RAW?**  
O: PIL rysuje pewnie i uniwersalnie, ale RAW idzie bezpośrednio w RGB565 + SPI.

**P: Skąd wiem, która ścieżka się użyła?**  
O: Z logów: `LCDRenderer.ShowImage[pil]` (PIL) vs `LCDRenderer.push_frame[rgb565_3]` (RAW).

---

_Stan na dziś: stabilne ścieżki presenter + PIL; RAW osiąga ~11–15 FPS @ 48–64 MHz. Domyślnie wymuszamy `rotate=270`, domyślny HZ=48 MHz, transport