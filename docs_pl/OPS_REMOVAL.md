# Usunięcie katalogu `ops/`

## Podsumowanie migracji

Katalog `ops/` został całkowicie usunięty z repozytorium. Wszystkie pliki zostały przeniesione do odpowiednich lokalizacji zgodnie z deterministyczną mapą migracji.

## Migracja głównego skryptu

**Skrypt systemd-sync.sh:**
- **Źródło:** `ops/systemd-sync.sh`
- **Cel:** `scripts/systemd-sync.sh`
- **Uwagi:** Nazwa bez zmian — zachowano oryginalną nazwę dla łatwego wyszukiwania

## Mapa migracji konfiguracji

Wszystkie pliki konfiguracyjne i pomocnicze zostały przeniesione do `config/<domena>/` według poniższej mapy:

| Źródło | Cel | Domena |
|--------|-----|--------|
| `ops/agent/requirements-test.txt` | `config/agent/requirements-test.txt` | Agent/Dev |
| `ops/agent/constraints.txt` | `config/agent/constraints.txt` | Agent/Dev |
| `ops/agent/run_tests.sh` | `config/agent/run_tests.sh` | Agent/Dev |
| `ops/audio/mpg123.sh` | `config/alsa/mpg123.sh` | Audio/ALSA |
| `ops/audio/wm8960-mixer.sh` | `config/alsa/wm8960-mixer.sh` | Audio/ALSA |

## Aktualizacje referencji

### Kod aplikacji
- `services/api_core/services_api.py`: `ops/service_ctl.sh` → `scripts/sys_control.sh`

### Makefile
- Usunięto include: `ops/agent/Makefile.agent` → `config/agent/Makefile.agent`
- Dodano nowy target: `make systemd-sync` → wywołuje `scripts/systemd-sync.sh`

### Dokumentacja
- `docs/_inventory.md`: zaktualizowano ścieżkę do `scripts/systemd-sync.sh`
- `docs/ops/README.md`: zaktualizowano ścieżkę do `scripts/systemd-sync.sh`

## Użycie po migracji

### Synchronizacja systemd
```bash
# Bezpośrednio
bash scripts/systemd-sync.sh

# Przez Makefile (nowy target)
make systemd-sync
```

### Konfiguracja audio
Skrypty audio znajdują się teraz w `config/alsa/`:
```bash
# Zastosuj konfigurację miksera WM8960
bash config/alsa/wm8960-mixer.sh

# Odtwarzanie przez mpg123
bash config/alsa/mpg123.sh /path/to/file.mp3
```

### Testy agenta
```bash
# Uruchom testy agenta
bash config/agent/run_tests.sh
```

## Reguły mapowania (dla przyszłych migracji)

Jeśli w przyszłości pojawią się nowe pliki konfiguracyjne, należy stosować następującą deterministyczną mapę:

- **Audio/ALSA/mixery** → `config/alsa/` (np. `asoundrc.*`, `wm8960*.{toml,ini,conf}`, `*alsa*`, `*audio*`)
- **Voice/TTS/ASR** → `config/voice/` (np. `voice*.toml`, `tts*.toml`, `asr*`, `stt*`, `speech*`)
- **UI/Face** → `config/ui/` (np. `face*.toml`, `ui*.toml`, `display*`, `lcd*`)
- **Simulator** → `config/sim/` (np. `sim*.toml`, `simulator*.toml`, `world*.toml`)
- **Agent/Dev** → `config/agent/` (np. `agent*.{toml,yaml,yml,ini}`, `dev*`, `ci*`)
- **Inne** → `config/misc/` (fallback dla nieokreślonych domen)

## Weryfikacja

Po migracji przeprowadzono następujące kontrole:
- ✅ Katalog `ops/` nie istnieje w repozytorium
- ✅ Skrypt `scripts/systemd-sync.sh` istnieje i ma prawa wykonywalne
- ✅ Wszystkie referencje do `ops/` zostały zaktualizowane
- ✅ `ruff check` i `ruff format` przechodzą bez błędów
- ✅ `pytest` przechodzi pomyślnie
- ✅ `grep -R "ops/"` nie zwraca wyników (poza tym dokumentem)

---

**Data migracji:** 2025-10-11  
**Status:** Zakończono ✅
