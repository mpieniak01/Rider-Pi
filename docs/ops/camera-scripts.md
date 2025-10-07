# Skrypty kamery (`ops/camera_*.sh`, `vision_ctl.sh`)

## camera_preview.sh

### Opis

Uruchamia preview z kamery na LCD — wrapper dla `apps.camera`.

### Użycie

```bash
./ops/camera_preview.sh [args]
```

### Parametry

Przekazuje argumenty do `python -m apps.camera`:

```bash
# Preview z detekcją twarzy
./ops/camera_preview.sh --human 1 --every 3

# Preview z rotacją
./ops/camera_preview.sh --rot 180

# Zobacz pełną listę parametrów
python -m apps.camera --help
```

Zobacz: [docs/apps/camera.md](../apps/camera.md)

---

## camera_takeover_kill.sh

### Opis

**Wymusza dostęp do kamery** przez zabicie procesów używających `/dev/video*`.

⚠️ **Bezpieczeństwo:** Używa whitelist procesów które można bezpiecznie zabić.

### Użycie

```bash
./ops/camera_takeover_kill.sh
```

### Działanie

1. Wykrywa procesy używające `/dev/video0` (lub `/dev/video1`)
2. Sprawdza whitelist (dozwolone do zabicia)
3. Wysyła `SIGTERM` → czeka 2s → `SIGKILL` jeśli nadal działa
4. Loguje wszystkie akcje

### Whitelist

⚠️ **Wymaga weryfikacji:** Lista procesów do uzupełnienia po analizie kodu.

Prawdopodobnie:
- `python` (własne preview)
- `ffmpeg` (streaming)
- `gstreamer` (pipeline)

**NIE zabija:**
- Systemowych demonów
- Nieznanych procesów (wymaga manualnej interwencji)

### Przykład

```bash
# Kamera zajęta
lsof /dev/video0
# → python  1234 pi   3u   CHR   81,0   /dev/video0

# Przejmij kamerę
./ops/camera_takeover_kill.sh
# [camera_takeover_kill] Found process: python (1234)
# [camera_takeover_kill] Sending SIGTERM to 1234
# [camera_takeover_kill] Process 1234 terminated

# Kamera wolna
lsof /dev/video0
# (pusty output)
```

### Diagnostyka

```bash
# Sprawdź kto używa kamery
lsof /dev/video0
fuser -v /dev/video0

# Kill ręcznie (bez skryptu)
sudo pkill -9 -f "python.*camera"
```

---

## kill_cam.sh

### Opis

**Szybkie zabicie** procesów kamery — uproszczona wersja `camera_takeover_kill.sh`.

### Użycie

```bash
./ops/kill_cam.sh
```

### Różnice

| Feature | camera_takeover_kill.sh | kill_cam.sh |
|---------|------------------------|-------------|
| Whitelist | Tak | Nie (lub prosta) |
| Graceful shutdown | SIGTERM → SIGKILL | Od razu SIGKILL |
| Logowanie | Szczegółowe | Minimalne |
| Use case | Produkcja | Quick debug |

---

## vision_ctl.sh

### Opis

Kontrola usług wizyjnych (vision, edge-preview, obstacle).

### Użycie

```bash
./ops/vision_ctl.sh <action>
```

### Akcje

⚠️ **Wymaga weryfikacji:** Szczegóły do uzupełnienia.

Prawdopodobne akcje:
- `start` — uruchom wszystkie usługi wizyjne
- `stop` — zatrzymaj wszystkie
- `restart` — restart
- `status` — sprawdź status
- `enable` / `disable` — autostart

### Przykład

```bash
# Start wizji
./ops/vision_ctl.sh start

# Status
./ops/vision_ctl.sh status
# rider-vision.service:        active (running)
# rider-edge-preview.service:  inactive (dead)
# rider-obstacle.service:      active (running)

# Stop wszystkich
./ops/vision_ctl.sh stop
```

### Alternatywa

Użyj bezpośrednio `service_ctl.sh`:

```bash
./ops/service_ctl.sh rider-vision.service start
./ops/service_ctl.sh rider-edge-preview.service start
./ops/service_ctl.sh rider-obstacle.service start
```

---

## Workflow: przejmowanie kamery

### Problem

Inny proces blokuje kamerę.

### Rozwiązanie

```bash
# 1. Sprawdź kto używa
lsof /dev/video0

# 2. Bezpieczne przejęcie
./ops/camera_takeover_kill.sh

# 3. Uruchom własny preview
./ops/camera_preview.sh --human 1

# (alternatywnie) Start przez systemd
./ops/service_ctl.sh rider-cam-preview.service start
```

### Pre-flight check (rekomendowane)

Dodaj do skryptu startowego:

```bash
#!/usr/bin/env bash

# Check camera availability
if lsof /dev/video0 >/dev/null 2>&1; then
  echo "Camera busy, taking over..."
  ./ops/camera_takeover_kill.sh
fi

# Start preview
./ops/camera_preview.sh
```

---

**Related docs:**
- [docs/apps/camera.md](../apps/camera.md) — moduł preview
- [docs/apps/vision.md](../apps/vision.md) — detektory
- [docs/ops/systemd-scripts.md](systemd-scripts.md) — zarządzanie usługami

**Ostatnia aktualizacja:** 2025-01
