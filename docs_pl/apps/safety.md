# Moduł Safety (`apps/safety`)

## Opis

Moduł `apps/safety` implementuje **emergency stop (E-STOP)** dla robota — natychmiastowe zatrzymanie ruchu w sytuacjach awaryjnych.

### Główny plik

- **`estop.py`** — implementacja E-STOP

### Główne funkcje

⚠️ **Wymaga weryfikacji:** Szczegóły implementacji `estop.py` wymagają odczytu kodu źródłowego.

## Przepływ danych

```
Wejście:  Trigger E-STOP (przycisk, sygnał, komenda)
          ↓
Akcja:    Natychmiastowe zatrzymanie silników
          ↓
Wyjście:  PUB("motion.cmd") → {"type": "stop"}
          Bezpośrednie wywołanie hardware stop (jeśli dostępne)
```

## Konfiguracja

⚠️ **Wymaga weryfikacji:** Parametry do uzupełnienia po analizie kodu.

### Możliwe źródła E-STOP

- Fizyczny przycisk E-STOP (GPIO)
- Komenda z BUS (`safety.estop`)
- Detekcja przechylenia (IMU)
- Timeout watchdog
- Niski poziom baterii

## Przykład użycia

### Uruchomienie ręczne

```bash
python -m apps.safety.estop
```

### Wyzwolenie E-STOP przez BUS

```bash
# Wyślij komendę E-STOP
python -c "from common.bus import BusPub; BusPub().publish('safety.estop', {'source': 'manual'})"
```

## Błędy i diagnostyka

### Logowanie

⚠️ **Wymaga weryfikacji:** Format logów do uzupełnienia.

### Typowe problemy

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| E-STOP nie działa | Moduł nie uruchomiony | Sprawdź status usługi systemd |
| Fałszywe alarmy | Czuły threshold IMU/baterii | Dostosuj parametry w konfiguracji |

## Zależności

### Wewnętrzne (w repo)
- `common.bus` — komunikacja przez BUS
- `apps.motion` — wysyłanie komend stop

### Zewnętrzne
- ⚠️ **Wymaga weryfikacji:** GPIO, sensors, etc.

## Priorytet bezpieczeństwa

E-STOP ma **najwyższy priorytet** w systemie:
- Przerywa wszystkie komendy ruchu
- Nie jest blokowany przez inne moduły
- Działa niezależnie od stanu baterii

---

**Related docs:**
- [motion.md](motion.md) — odbiorca komend `motion.cmd`
- [launcher.md](launcher.md) — przycisk BACK jako miękki stop

**Ostatnia aktualizacja:** 2025-01  
**Status:** ⚠️ Wymaga uzupełnienia szczegółów implementacji
