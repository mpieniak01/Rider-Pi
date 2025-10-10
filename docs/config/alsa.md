# Konfiguracja ALSA (`config/alsa/`)

## Pliki

- **`asoundrc.wm8960`** — szablon konfiguracji ALSA dla WM8960
- **`wm8960-apply.sh`** — skrypt konfiguracji miksera WM8960
- **`preflight.sh`** — pre-flight checks dla audio

---

## asoundrc.wm8960

### Opis

Szablon `.asoundrc` dla karty dźwiękowej **WM8960** — definiuje aliasy `wm8960_in` i `wm8960_out` dla łatwiejszego użycia.

### Instalacja

```bash
# 1. Skopiuj szablon
cp config/alsa/asoundrc.wm8960 ~/.asoundrc

# 2. Sprawdź urządzenia ALSA
aplay -l
arecord -l

# 3. Dostosuj (jeśli karta ma inny numer)
nano ~/.asoundrc
# Zmień "hw:wm8960soundcard,0" na właściwe urządzenie
```

### Zawartość (przykład)

```conf
# WM8960 Input (Capture)
pcm.wm8960_in {
    type hw
    card wm8960soundcard
    device 0
}

# WM8960 Output (Playback)
pcm.wm8960_out {
    type hw
    card wm8960soundcard
    device 0
}

# Domyślne urządzenie (opcjonalnie)
pcm.!default {
    type asym
    playback.pcm "wm8960_out"
    capture.pcm "wm8960_in"
}
```

### Użycie

```bash
# Capture
arecord -D wm8960_in -d 5 -f S16_LE -r 16000 test.wav

# Playback
aplay -D wm8960_out test.wav

# W aplikacji voice
python -m apps.voice.cli listen --config config/voice_file.toml
# (voice_file.toml używa device = "wm8960_in" i "wm8960_out")
```

---

## wm8960-apply.sh

### Opis

Skrypt konfiguracji **miksera WM8960** — ustawia wzmocnienie, routing, volume.

⚠️ **Wymaga weryfikacji:** Szczegóły komend do uzupełnienia po analizie kodu.

### Użycie

```bash
./config/alsa/wm8960-apply.sh
```

### Funkcje (prawdopodobne)

1. **Set volume levels:**
   - Playback volume
   - Capture gain
   - Speaker volume

2. **Routing:**
   - Input source (MIC, LINE IN)
   - Output destination (Speaker, Headphone)

3. **Filters:**
   - High-pass filter (HPF)
   - De-emphasis

### Przykład komend (amixer)

```bash
# Playback volume (0–255)
amixer -c wm8960soundcard set 'Playback' 200

# Capture gain (0–63)
amixer -c wm8960soundcard set 'Capture' 40

# Mikrofon boost (0/1)
amixer -c wm8960soundcard set 'Mic Boost' 1

# Speaker output
amixer -c wm8960soundcard set 'Speaker' 80%
```

### Diagnostyka

```bash
# Lista kontrolek miksera
amixer -c wm8960soundcard controls

# Stan wszystkich kontrolek
amixer -c wm8960soundcard contents

# Edytuj interaktywnie
alsamixer -c wm8960soundcard
```

---

## preflight.sh

### Opis

**Pre-flight checks** dla audio przed uruchomieniem aplikacji voice.

⚠️ **Wymaga weryfikacji:** Szczegóły do uzupełnienia.

### Użycie

```bash
./config/alsa/preflight.sh
```

### Sprawdzenia (prawdopodobne)

1. **Dostępność urządzeń:**
   - Sprawdź czy `/dev/snd/*` istnieją
   - Sprawdź czy karta WM8960 jest załadowana

2. **Procesy blokujące:**
   - `fuser /dev/snd/pcmC*`
   - Wykryj aplikacje używające audio

3. **Konfiguracja:**
   - Sprawdź istnienie `~/.asoundrc`
   - Walidacja aliasów (wm8960_in, wm8960_out)

4. **Test capture/playback:**
   - Krótki test nagrania (1s)
   - Test odtwarzania (beep)

### Kody wyjścia

| Kod | Znaczenie |
|-----|-----------|
| 0 | OK — można uruchomić aplikację |
| 1 | Błąd — brak urządzenia lub konfiguracji |
| 2 | Ostrzeżenie — urządzenie zajęte |

### Integracja

```bash
#!/usr/bin/env bash
# ops/voice-run-safe.sh

# Pre-flight check
./config/alsa/preflight.sh || {
  echo "Audio preflight failed, aborting"
  exit 1
}

# Uruchom voice
./scripts/sys_voice-run.sh
```

---

## Typowe problemy

### 1. Brak dźwięku (capture/playback)

**Diagnoza:**
```bash
# Sprawdź karty
aplay -l
arecord -l

# Test playback
speaker-test -D wm8960_out -c 2

# Test capture
arecord -D wm8960_in -d 3 -f S16_LE -r 16000 test.wav
aplay test.wav
```

**Rozwiązania:**
- Sprawdź `~/.asoundrc` (czy aliasy istnieją)
- Sprawdź volume (`alsamixer`)
- Sprawdź routing (`amixer contents`)

### 2. Urządzenie zajęte (busy)

**Diagnoza:**
```bash
# Kto używa audio?
fuser -v /dev/snd/pcmC*
lsof /dev/snd/*
```

**Rozwiązania:**
```bash
# Zabij procesy
sudo pkill -9 pulseaudio  # jeśli PulseAudio blokuje
sudo fuser -k /dev/snd/pcmC0D0p  # zabij playback
```

### 3. Niska jakość audio (szum, zniekształcenia)

**Diagnoza:**
```bash
# Sprawdź sample rate
cat /proc/asound/card*/pcm*/sub*/hw_params
```

**Rozwiązania:**
- Ustaw sample rate = 16000 (dla voice)
- Zwiększ bufor (zmniejsz xruns)
- Zmniejsz wzmocnienie capture (jeśli przesterowanie)

### 4. Latencja (opóźnienie)

**Optymalizacja:**
```bash
# Zmniejsz buffer/period w ALSA
# W aplikacji voice:
export ALSA_BUFFER_US=30000  # mniejszy bufor
export ALSA_PERIOD_US=8000   # krótszy okres
```

---

## Konfiguracja WM8960 (sprzęt)

### Jumpers / DIP switches

⚠️ **Sprawdź dokumentację karty:** Niektóre karty WM8960 mają jumpers dla:
- Input source (MIC/LINE)
- Voltage (3.3V/5V)
- I2S/PCM mode

### Konfiguracja GPIO (Raspberry Pi)

```bash
# W /boot/config.txt (dla niektórych kart)
dtoverlay=wm8960-soundcard

# Restart
sudo reboot
```

### Weryfikacja załadowania

```bash
# Sprawdź moduły kernel
lsmod | grep snd

# Sprawdź Device Tree
ls /proc/device-tree/soc/sound/
```

---

## Debugowanie ALSA

### Verbose logging

```bash
# ENV dla szczegółowych logów ALSA
export ALSA_DEBUG=1
arecord -D wm8960_in -d 1 -f S16_LE -r 16000 test.wav
```

### Dump konfiguracji

```bash
# Pokaż aktualną konfigurację ALSA
cat ~/.asoundrc

# Lub systemową
cat /etc/asound.conf
```

### Monitoring w czasie rzeczywistym

```bash
# alsamixer (TUI)
alsamixer -c wm8960soundcard

# Continuous monitoring
watch -n 1 'amixer -c wm8960soundcard contents | grep -A2 "Capture\|Playback"'
```

---

## Zobacz także

- [docs/audio/wm8960.md](../audio/wm8960.md) — szczegółowa dokumentacja WM8960
- [docs/config/voice.md](voice.md) — parametry voice (capture/playback)
- [docs/CONFIG_POLICY.md](../CONFIG_POLICY.md) — polityka konfiguracji

**Ostatnia aktualizacja:** 2025-01  
**Status:** ⚠️ Szczegóły wm8960-apply.sh i preflight.sh wymagają weryfikacji
