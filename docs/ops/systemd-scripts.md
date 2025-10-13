# Skrypty systemd (`ops/systemd-*.sh`, `service_ctl.sh`)

## service_ctl.sh

### Opis

Bezpieczna kontrola usług systemd z **whitelist** dozwolonych jednostek. Zapobiega przypadkowemu zatrzymaniu krytycznych usług systemowych.

### Użycie

```bash
./scripts/sys_control.sh <unit> <action>
./scripts/sys_control.sh <action> <unit>  # kolejność dowolna
```

### Parametry

| Parametr | Typ | Opis |
|----------|-----|------|
| `unit` | str | Nazwa jednostki systemd (np. `rider-api.service`) |
| `action` | enum | `start`, `stop`, `restart`, `enable`, `disable` |

### Whitelist

Dozwolone jednostki (hardcoded w skrypcie):

```bash
ALLOW_UNITS=(
  rider-api.service
  rider-broker.service
  rider-motion-bridge.service
  rider-vision.service
  rider-web-bridge.service
  rider-cam-preview.service
  rider-edge-preview.service
  rider-ssd-preview.service
  rider-obstacle.service
)
```

### Przykłady

```bash
# Start usługi API
./scripts/sys_control.sh rider-api.service start

# Stop usługi vision
./scripts/sys_control.sh stop rider-vision.service  # kolejność dowolna

# Restart brokera
./scripts/sys_control.sh rider-broker.service restart

# Enable na starcie systemu
./scripts/sys_control.sh rider-api.service enable
```

### Diagnostyka

#### Próba user vs system

Skrypt automatycznie próbuje:
1. **System:** `systemctl --system <action> <unit>`
2. **User:** `systemctl --user <action> <unit>` (jeśli system fail)

Logika wykrywania:
- Jeśli jednostka jest system-level → użyj system
- Jeśli jednostka jest user-level → użyj user
- Wybiera lepszy komunikat błędu jeśli oba failują

#### Kody wyjścia

| Kod | Znaczenie |
|-----|-----------|
| 0 | Sukces |
| 2 | Błędne argumenty |
| 3 | Jednostka nie w whitelist |
| 5 | Błąd systemctl (oba: system i user) |

### Bezpieczeństwo

**Whitelist chroni przed:**
- Zatrzymaniem `ssh.service` → utrata dostępu zdalnego
- Zatrzymaniem `systemd-logind` → crash systemu
- Operacjami na nieznanych usługach

**Dodawanie nowych usług do whitelist:**

Edytuj `scripts/sys_control.sh`:
```bash
ALLOW_UNITS=(
  # ... istniejące ...
  rider-my-new-service.service  # dodaj nową
)
```

---

## systemd_sync.sh

### Opis

Synchronizuje definicje usług systemd z repozytorium do `/etc/systemd/system`. Implementuje **repo-first** approach — repo jest źródłem prawdy.

### Użycie

```bash
./scripts/systemd-sync.sh
```

⚠️ **Wymaga sudo** — modyfikuje `/etc/systemd/system`

### Funkcje

1. **Backup** — kopuje istniejące `rider-*` do `_rider_backup_<timestamp>`
2. **Baseline** — włącza podstawowe usługi systemowe (`ssh`, `getty`, `dhcpcd`)
3. **Linkowanie** — tworzy symlinki z `/etc/systemd/system` do `~/robot/systemd/*`
4. **Czyszczenie** — usuwa niezarządzane `rider-*` (nie w allowlist lub nie w repo)
5. **Drop-iny** — usuwa `.service.d` (repo trzyma pełne definicje)
6. **Reload** — `systemctl daemon-reload`
7. **Enable** — włącza `rider-minimal.target` i `rider-boot-prepare.service`
8. **Legacy mask** — maskuje przestarzałe usługi (np. `rider-dispatcher.service`)
9. **Weryfikacja** — wyświetla tabelę statusu wszystkich `rider-*`

### Whitelist

```bash
ALLOW_UNITS=(
  "rider-broker.service"
  "rider-api.service"
  "rider-vision.service"
  "rider-motion-bridge.service"
  "rider-boot-prepare.service"
  "rider-minimal.target"
  "rider-edge-preview.service"
  "rider-obstacle.service"
  "rider-cam-preview.service"
  "rider-ssd-preview.service"
  "jupyter.service"
  "rider-dev.target"
  "rider-web-bridge.service"
  "rider-voice.service"
  "wifi-unblock.service"
)
```

### Przykład output

```
[systemd_sync] Ustawiam domyślny target na multi-user.target
[systemd_sync] Backup rider-* do: /etc/systemd/system/_rider_backup_20250107-120000
[systemd_sync] Enable baseline: getty@tty1.service
[systemd_sync] Tworzę symlinki dla allowlisty -> /home/pi/robot/systemd/*
[systemd_sync] Czyszczę niezarządzane rider-* w /etc/systemd/system
[systemd_sync] systemctl daemon-reload
[systemd_sync] Enable rider unit: rider-minimal.target

== Weryfikacja rider-* ==
UNIT                             ENABLED    ACTIVE     TARGET
rider-api.service                enabled    active     /home/pi/robot/systemd/rider-api.service
rider-broker.service             enabled    active     /home/pi/robot/systemd/rider-broker.service
rider-minimal.target             enabled    inactive   /home/pi/robot/systemd/rider-minimal.target

[systemd_sync] DONE. Po sync: reboot jest wskazany.
```

### Workflow

#### 1. Dodanie nowej usługi

```bash
# 1. Utwórz definicję w repo
cat > systemd/rider-my-service.service << 'EOF'
[Unit]
Description=My Custom Service

[Service]
Type=simple
ExecStart=/home/pi/robot/apps/my_app.py

[Install]
WantedBy=multi-user.target
EOF

# 2. Dodaj do allowlist w systemd_sync.sh
# (edytuj plik: ALLOW_UNITS+=("rider-my-service.service"))

# 3. Synchronizuj
sudo ./scripts/systemd-sync.sh

# 4. Uruchom
./scripts/sys_control.sh rider-my-service.service start
```

#### 2. Usunięcie usługi

```bash
# 1. Usuń z allowlist w systemd_sync.sh
# 2. Usuń plik z systemd/
# 3. Synchronizuj
sudo ./scripts/systemd-sync.sh
# → usługa zostanie automatycznie wyłączona i usunięta z /etc
```

### Bezpieczeństwo

- **Nie nadpisuje** usług systemowych (tylko `rider-*`)
- **Backup** przed zmianami (można rollback)
- **Symlinki** zamiast kopiowania (łatwiejsze śledzenie zmian)
- **Idempotentny** — wielokrotne uruchomienie bezpieczne

### Diagnostyka

```bash
# Sprawdź co będzie zlinkowane
ls -la systemd/rider-*.service systemd/rider-*.target

# Sprawdź status wszystkich rider-*
systemctl list-units 'rider-*' --all

# Sprawdź symlinki
ls -la /etc/systemd/system/rider-*.service
```

---

## boot_prepare.sh

### Opis

Skrypt przygotowania systemu przy starcie — uruchamiany przez `rider-boot-prepare.service`.

⚠️ **Wymaga weryfikacji:** Szczegóły implementacji do uzupełnienia.

### Funkcje (prawdopodobne)

- Konfiguracja ALSA (ładowanie `asoundrc`)
- Inicjalizacja GPIO
- Sprawdzenie dostępności urządzeń (kamera, LCD)
- Pre-flight checks dla usług

### Użycie

```bash
# Ręczne uruchomienie (debug)
sudo ./scripts/sys_boot-prepare.sh

# Przez systemd (automatyczne przy starcie)
sudo systemctl start rider-boot-prepare.service
```

---

## Zobacz także

- [docs/CONFIG_POLICY.md](../CONFIG_POLICY.md) — standardy konfiguracji
- Katalog `systemd/` w repo — definicje usług

**Ostatnia aktualizacja:** 2025-01
