# Rider-Pi — PROJECT.md (v0.4.6)

**Wersja:** v0.4.6\
**Data:** 2025-08-27\
**Repo:** `pppnews/Rider-Pi`

---

## Co nowego w v0.4.6

- **Jednolity kontroler ekranu 2" (SPI TFT):** `scripts/lcdctl.py`
  - Jeden plik do **ON/OFF** wyświetlacza na realnym HW.
  - Panel (ST77xx/ILI9xx): komendy SPI\
    **OFF** → `DISP_OFF (0x28)` + `SLP_IN (0x10)`\
    **ON**  → `SLP_OUT (0x11)` + `DISP_ON (0x29)`
  - Podświetlenie (BL) przez **GPIO** (domyślnie **BCM0**, `active-high=1`).
  - Parametry przez **flagi/ENV**: `--bl`, `--bl-ah`, `--dc`, `--rst`, `--spi`, `--hz`.
- **Test dymny:** `scripts/smoke_test.sh`
  - Minimalny zestaw kroków: `clean → compileall → import rendererów → face(null) → (opcjonalnie) pygame`.
  - **Eleganckie zakończenie:** trap `EXIT` ubija `apps.ui.face` i wywołuje `sudo python3 scripts/lcdctl.py off`\
    → ekran fizycznie gaśnie po testach.
- **UI „face”:** uproszczony wybór backendu\
  Obecnie wspieramy **Pygame** (aliasy `lcd/tk/led/auto` mapują się na pygame) oraz **NullRenderer**.
- **Konfiguracja BL ustalona:** realny pin **BCM0**; polaryzacja **active-high=1**.

---

## Szybki start

```bash
# test dymny (na końcu auto-OFF ekranu)
chmod +x scripts/smoke_test.sh
bash scripts/smoke_test.sh

# wymuś pygame, gdy nie ma DISPLAY
RUN_PYGAME=1 bash scripts/smoke_test.sh
```

**(opcjonalnie) spójne ENV dla „face”:**

```bash
echo 'export FACE_LCD_BL_PIN=0'         >> ~/.bashrc
echo 'export FACE_LCD_BL_ACTIVE_HIGH=1' >> ~/.bashrc
. ~/.bashrc
```

---

## Sterowanie ekranem 2" (SPI)

Plik: `scripts/lcdctl.py`

```bash
# OFF: uśpij panel + zgaś podświetlenie
sudo python3 scripts/lcdctl.py off

# ON: włącz podświetlenie + wybudź panel
sudo python3 scripts/lcdctl.py on

# (opcjonalnie) jawne piny/urządzenia – domyślnie mamy BL=0, DC=25, RST=27
sudo python3 scripts/lcdctl.py off --bl 0 --bl-ah 1 --dc 25 --rst 27 --spi /dev/spidev0.0 --hz 12000000
```

**Skróty (opcjonalnie):**

```bash
sudo ln -sf "$(pwd)/scripts/lcdctl.py" /usr/local/bin/lcdctl
sudo lcdctl off
sudo lcdctl on
```

---

## „Buźka” (face)

```bash
# standardowo: pygame (aliasy lcd/tk/led/auto też trafią do pygame)
FACE_BACKEND=pygame python3 -m apps.ui.face

# z domyślnym BL=0 (jeśli chcesz jawnie)
FACE_BACKEND=pygame FACE_LCD_BL_PIN=0 FACE_LCD_BL_ACTIVE_HIGH=1 python3 -m apps.ui.face
```

---

## Procedury testowe (skrót)

1. **Smoke test**\
   `bash scripts/smoke_test.sh` → na końcu ekran **OFF** (trap EXIT → `lcdctl off`).
2. **Ręczne ON/OFF**\
   `sudo python3 scripts/lcdctl.py on | off`
3. **Sprawdzenie rendererów**\
   log z testu pokazuje listę klas: `['BaseRenderer','LCDRenderer','TKRenderer']`\
   (w praktyce używamy `PygameFaceRenderer`/`NullRenderer`).

---

## Zmiany w kodzie (v0.4.6)

- `scripts/lcdctl.py` – **NOWY**, jedyny kontroler ekranu (SPI + GPIO BL).
- `scripts/smoke_test.sh` – uproszczony, z **auto-OFF** via `lcdctl`.
- `apps/ui/face.py` – wybór backendu sprowadzony do **Pygame**/**Null** (zgodność aliasów), heartbeat/bench stabilne.

---

## Rozwiązywanie problemów

- **Biały ekran po OFF**\
  Oznaczało brak `SLP_IN/DISP_OFF`. `lcdctl.py off` wymusza sekwencję SPI → problem rozwiązany.
- **BL nie gaśnie**\
  Sprawdź pin/polaryzację (u nas: **BCM0**, **AH=1**).\
  `sudo python3 scripts/lcdctl.py off --bl 0 --bl-ah 1`
- **Brak bibliotek**\
  `sudo apt-get install -y python3-spidev python3-rpi.gpio`

---

## Changelog

- **v0.4.6**: `lcdctl.py` (ON/OFF panelu + BL), smoke test z auto-OFF, uproszczony `face`, BL=BCM0.
- **v0.4.5**: (poprzedni plan z UI Managerem i dimmingiem – odłożony; zostawiamy prosty, działający ON/OFF).
- **v0.4.4**: menedżer/launcher + demo trajektorii, porządki repo, README/PROJECT.
- **v0.4.3**: XgoAdapter, telemetria baterii, doc: środowisko i adapter.

