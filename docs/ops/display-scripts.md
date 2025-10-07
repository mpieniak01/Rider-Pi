# Skrypty wyświetlacza (`ops/lcd*.py`, `fbgrab.py`, `splash*.py`)

## lcdctl.py

### Opis

Kontrola wyświetlacza LCD — jasność, zasilanie, czyszczenie ekranu.

### Użycie

```bash
./ops/lcdctl.py [command] [args]
```

### Komendy

⚠️ **Wymaga weryfikacji:** Szczegóły komend do uzupełnienia po analizie kodu.

Prawdopodobne komendy:
- `brightness <0-100>` — ustaw jasność
- `on` — włącz wyświetlacz
- `off` — wyłącz wyświetlacz
- `clear [color]` — wyczyść ekran
- `info` — informacje o urządzeniu

### Przykłady

```bash
# Ustaw jasność na 80%
./ops/lcdctl.py brightness 80

# Wyłącz ekran (oszczędzanie energii)
./ops/lcdctl.py off

# Wyczyść na czarno
./ops/lcdctl.py clear black
```

---

## ledctl.py

### Opis

Kontrola diod LED — miganie, kolory, wzorce.

### Użycie

```bash
./ops/ledctl.py [command] [args]
```

### Komendy

⚠️ **Wymaga weryfikacji:** Szczegóły do uzupełnienia.

Prawdopodobne komendy:
- `on [led_id]` — włącz LED
- `off [led_id]` — wyłącz LED
- `blink [led_id] [rate]` — miganie
- `color [led_id] <r> <g> <b>` — ustaw kolor RGB
- `pattern <name>` — wzorzec (np. `rainbow`, `pulse`)

### Przykłady

```bash
# Włącz LED 0
./ops/ledctl.py on 0

# Miganie z częstotliwością 2 Hz
./ops/ledctl.py blink 0 2

# Czerwony kolor
./ops/ledctl.py color 0 255 0 0
```

---

## fbgrab.py

### Opis

Zrzut ekranu z framebuffera `/dev/fb*` do pliku PNG/JPEG.

### Użycie

```bash
./ops/fbgrab.py [options]
```

### Parametry

⚠️ **Wymaga weryfikacji:** Szczegóły do uzupełnienia.

Prawdopodobne opcje:
- `-o, --output <file>` — ścieżka wyjściowa
- `-d, --device <fb>` — urządzenie framebuffer (domyślnie `/dev/fb0`)
- `-f, --format <png|jpeg>` — format wyjściowy

### Przykłady

```bash
# Zrzut ekranu do PNG
./ops/fbgrab.py -o screenshot.png

# Z konkretnego framebuffera
./ops/fbgrab.py -d /dev/fb1 -o lcd_snapshot.png

# Format JPEG
./ops/fbgrab.py -o screen.jpg -f jpeg
```

### Use cases

- Debug renderingu buźki
- Dokumentacja interfejsu
- Diagnostyka problemów wyświetlacza

---

## splash_device_info.py

### Opis

Wyświetla **ekran powitalny** z informacjami o urządzeniu: IP, hostname, wersja systemu, status usług.

### Użycie

```bash
./ops/splash_device_info.py
```

### Wyświetlane informacje

- Hostname
- Adres IP (WiFi, Ethernet)
- Wersja systemu (OS, kernel)
- Czas działania (uptime)
- Status usług Rider-Pi
- Poziom baterii (jeśli dostępny)

### Integracja z systemd

```bash
# Uruchom splash przy starcie (jeśli skonfigurowane)
sudo systemctl start rider-splash.service
```

### Przykład ekranu

```
╔════════════════════════════════════════╗
║         Rider-Pi v0.6                  ║
╠════════════════════════════════════════╣
║ Hostname: rider-pi-01                  ║
║ IP (wlan0): 192.168.1.100              ║
║ Uptime: 2 days, 5:30                   ║
║                                        ║
║ Services:                              ║
║  ✓ rider-api.service                   ║
║  ✓ rider-broker.service                ║
║  ✗ rider-voice.service                 ║
║                                        ║
║ Battery: 85% ▓▓▓▓▓▓▓▓░░               ║
╚════════════════════════════════════════╝
```

---

## splash_device_info.sh

### Opis

Wrapper bash dla `splash_device_info.py` — ustawia ENV i uruchamia Python script.

### Użycie

```bash
./ops/splash_device_info.sh
```

---

## vendor_splash.py

### Opis

Ekran powitalny **producenta** — logo, branding, informacje o produkcie.

⚠️ **Wymaga weryfikacji:** Szczegóły do uzupełnienia.

### Użycie

```bash
./ops/vendor_splash.py
```

### Różnice vs splash_device_info

| Feature | splash_device_info | vendor_splash |
|---------|-------------------|---------------|
| Cel | Status systemu | Branding |
| Treść | IP, uptime, services | Logo, wersja produktu |
| Use case | Debug, diagnostyka | Pierwszy start, prezentacja |

---

## Diagnostyka wyświetlacza

### Sprawdzenie framebuffera

```bash
# Lista urządzeń
ls -la /dev/fb*

# Informacje
fbset -i

# Test zapisu
dd if=/dev/zero of=/dev/fb0 bs=1024 count=100
```

### Debugowanie jasności

```bash
# Sprawdź backlight
ls /sys/class/backlight/

# Odczytaj aktualną jasność
cat /sys/class/backlight/*/brightness

# Ustaw jasność (wymaga uprawnień)
echo 128 | sudo tee /sys/class/backlight/*/brightness
```

---

**Related docs:**
- [docs/apps/hw.md](../apps/hw.md) — sink LCD (low-level)
- [docs/modules/face-lcd.md](../modules/face-lcd.md) — rendering na LCD

**Ostatnia aktualizacja:** 2025-01  
**Status:** ⚠️ Większość szczegółów wymaga weryfikacji kodu źródłowego
