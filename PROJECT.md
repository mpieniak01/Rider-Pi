# Rider‑Pi — PROJECT.md (v0.4.5)

**Wersja:** v0.4.5  
**Data:** 2025‑08‑27  
**Repo:** `pppnews/Rider-Pi`  

## Co nowego w v0.4.5
- **UI Manager**: automatyczne oszczędzanie energii na ekranie producenta (SPI LCD 2")
  - Tryb `UI_DIM_MODE=xgo` z **auto‑inicjalizacją PWM** (wykrywa `BL_PIN/BL_freq` i zakłada PWM gdy biblioteka nie robi tego sama).
  - **DIM** (procent BL) i **OFF** (BL=0) po bezczynności; **ON/UNDIM** po aktywności.
  - Wstrzymanie rysowania overleya przez `ui.control {"draw": false}` podczas ruchu.
  - Hooki audio: ściszanie przy DIM, mute przy OFF, przywrócenie przy ON.
- **Overlay** respektuje `ui.control` i nie renderuje, gdy `draw=false` (niższe CPU).
- **Narzędzia**: proste `scripts/pub.py`, `scripts/sub_dump.py`, `scripts/volume.py`, `apps/ui/volume_hooks.sh`.
- **Systemd**: nowa usługa `rider-ui-manager.service` + drop‑iny z ENV.

---

## Architektura (skrót)
- **ZeroMQ broker** (XSUB↔XPUB):
  - PUB → `tcp://127.0.0.1:5555` (tematy wychodzące)
  - SUB → `tcp://127.0.0.1:5556` (tematy przychodzące)
- **Tematy**:
  - `motion` – polecenia napędu (JSON)
  - `motion.state` – telemetria pętli ruchu
  - `vision.state` – sygnały z kamery/algorytmów (np. `human`, `moving`)
  - `ui.control` – sterowanie rysowaniem overleya `{ "draw": bool }`

Usługi (systemd):
- `rider-broker.service` – broker ZMQ (XSUB/XPUB)
- `rider-motion.service` – pętla ruchu (symulacja/fizyczny robot)
- `rider-menu.service` – menu/launcher CLI (przyciski + start demo)
- `rider-ui-manager.service` – oszczędzanie ekranu/overlay/audio (NOWE)

---

## Szybki start (headless)
```bash
# Broker
sudo systemctl enable --now rider-broker.service

# Motion (symulacja):
unset MOTION_ENABLE
sudo systemctl enable --now rider-motion.service

# UI Manager (XGO LCD)
sudo cp systemd/rider-ui-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rider-ui-manager.service

# Podgląd telemetrii (opcjonalnie)
TOPIC=motion.state python3 -u scripts/sub_dump.py
```

---

## UI Manager
Plik: `apps/ui/manager.py`  
Cel: wstrzymywanie rysowania oraz DIM/OFF ekranu przy bezczynności i/lub ruchu robota.

### Tryby wygaszania (ENV `UI_DIM_MODE`)
- `xgo` – SPI LCD producenta (moduł `xgoscreen.LCD_2inch`)
  - Auto‑init PWM (wykrywa `BL_PIN/BL_freq`, tworzy PWM w RPi.GPIO, podstawia pod `lcd._pwm`).
  - `UI_XGO_BRIGHT` (domyślnie 80), `UI_XGO_DIM` (10), `UI_XGO_BLACK_DIM` (0/1 czarna klatka jako DIM fallback).
- `vcgencmd` – HDMI przez `vcgencmd display_power 1/0`.
- `fb` – framebuffer `/sys/class/graphics/fb0/blank` (wymaga roota); fallback gdy nie ma `vcgencmd`.

### Logika rysowania
- Gdy **ruch** (`motion.state.stopped=false`) → `ui.control { draw:false }` (overlay nie renderuje).
- Gdy **stoi** i jest człowiek/ruch w kadrze (`vision.state`) → `draw:true` (tryb rozmowy).

### ENV (domyślne) w `rider-ui-manager.service`
```ini
Environment=UI_DIM_MODE=xgo
Environment=UI_INACTIVITY_DIM_SEC=30
Environment=UI_INACTIVITY_OFF_SEC=120
Environment=UI_XGO_BRIGHT=80
Environment=UI_XGO_DIM=10
Environment=UI_XGO_BLACK_DIM=0
Environment=UI_AUDIO_DIM_PCT=20
Environment=UI_AUDIO_OFF_MUTE=1
```

### Drop‑in (szybkie progi testowe 5/10 s)
```bash
sudo mkdir -p /etc/systemd/system/rider-ui-manager.service.d
sudo bash -c 'cat > /etc/systemd/system/rider-ui-manager.service.d/override.conf <<EOF
[Service]
Environment=UI_INACTIVITY_DIM_SEC=5
Environment=UI_INACTIVITY_OFF_SEC=10
EOF'
sudo systemctl daemon-reload
sudo systemctl restart rider-ui-manager.service
systemctl show rider-ui-manager.service -p Environment | tr "\0" "\n"
```

### Hooki audio
- `apps/ui/volume_hooks.sh` – `dim|off|on` → woła `scripts/volume.py` (pactl/pulseaudio).
- Możliwe ostrzeżenia o D‑Bus w trybie headless – **ignorować**.

---

## Overlay (HUD)
Plik: `apps/ui/overlay.py`  
- Pygame (fullscreen, `SDL_VIDEODRIVER=kmsdrm`).
- Reaguje na `ui.control` i **przestaje renderować**, gdy `draw=false`.
- Renderuje skrót telemetrii `motion.state` i `vision.state`.

---

## Narzędzia debug
- **Publikacja:**
  ```bash
  python3 -u scripts/pub.py motion.state '{"stopped": false, "last_cmd_age_ms": 0}'
  python3 -u scripts/pub.py motion.state '{"stopped": true, "last_cmd_age_ms": 1500}'
  python3 -u scripts/pub.py vision.state  '{"moving": false, "human": true}'
  ```
- **Sniffer:**
  ```bash
  TOPIC=ui.control python3 -u scripts/sub_dump.py
  TOPIC=motion.state python3 -u scripts/sub_dump.py
  ```

---

## Procedury testowe (runbook)
1. **Status usług**
   ```bash
   sudo systemctl status --no-pager rider-broker rider-motion rider-ui-manager
   ```
2. **Symulacja ruchu → draw:false**
   ```bash
   python3 -u scripts/pub.py motion.state '{"stopped": false, "last_cmd_age_ms": 0}'
   ```
3. **Rozmowa (stoi + człowiek) → draw:true**
   ```bash
   python3 -u scripts/pub.py motion.state '{"stopped": true, "last_cmd_age_ms": 2000}'
   python3 -u scripts/pub.py vision.state  '{"moving": false, "human": true}'
   ```
4. **DIM & OFF**
   - odczekaj `UI_INACTIVITY_DIM_SEC` → wpis w journalu `DIM` i (dla xgo) `DIM -> <pct>`
   - odczekaj `UI_INACTIVITY_OFF_SEC` → `POWER -> OFF (0%)` oraz `OFF`
5. **Wybudzenie**
   ```bash
   python3 -u scripts/pub.py vision.state '{"moving": true}'
   ```
   Journal: `ON` + `UNDIM -> <pct>`.

---

## Instalacja/aktualizacja usług
```bash
sudo cp systemd/rider-broker.service /etc/systemd/system/
sudo cp systemd/rider-motion.service  /etc/systemd/system/
sudo cp systemd/rider-ui-manager.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable rider-broker rider-motion rider-ui-manager
sudo systemctl restart rider-broker rider-motion rider-ui-manager
```

---

## Rozwiązywanie problemów
- **XGO: błąd `_pwm` przy `bl_DutyCycle`**  
  Manager auto‑inicjuje PWM (RPi.GPIO) na `lcd.BL_PIN` z `lcd.BL_freq`. Sprawdź log: `GPIO PWM init (pin=..., freq=...)`.
- **Brak BL w bibliotece**  
  Ustaw `UI_XGO_BLACK_DIM=1` – DIM czarną klatką zamiast BL.
- **HDMI (vcgencmd)**  
  `sudo apt install -y libraspberrypi-bin` (potrzebny `vcgencmd`).
- **Framebuffer (fb)**  
  Wymaga roota (`User=root` w unicie) oraz `/sys/class/graphics/fb0/blank`.
- **Audio/DBus**  
  Ostrzeżenia „Unable to autolaunch a dbus-daemon …” w headless są nieszkodliwe.

---

## Plan na następny krok
- Integracja kamery: sygnały `vision.state` z realnego detektora (człowiek/ruch).
- Konfiguracja FPS i profilu renderu w overlay (np. `UI_FPS=10`).
- Porządki w starszych modułach (monolity → moduły), review CPU i latencji.

---

## Changelog
- **v0.4.5**: UI Manager (XGO dim/off, auto PWM), overlay draw‑pause, hooki audio, unit systemd.
- **v0.4.4**: menedżer/launcher + demo trajektorii, porządki repo, README/PROJECT.
- **v0.4.3**: XgoAdapter, telemetria baterii, doc: środowisko i adapter.

---
