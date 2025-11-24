#!/usr/bin/env bash
# robot/scripts/systemd-sync.sh
#
#
# Rider-Pi — repo-first systemd sync (ALLOWLIST)
# Utrzymuje tylko wskazane usługi jako symlinki do ~/robot/systemd/*
# Idempotentny — nie importuje z /etc do repo, tylko zarządza wg repo-katalogu.
#

set -euo pipefail

# -- Ustal ścieżkę katalogu repo dla użytkownika „pi” (można nadpisać zmienną środowiskową REPO_ROOT)
REPO_ROOT="${REPO_ROOT:-/home/pi/robot}"
REPO_DIR="${REPO_ROOT}/systemd"
LEGACY_DIR="${REPO_DIR}/legacy"
ETC_DIR="/etc/systemd/system"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${ETC_DIR}/_rider_backup_${STAMP}"

WITH_DEV=0

usage() {
  cat <<'EOF'
Usage: scripts/systemd-sync.sh [--with-dev]

Options:
  --with-dev   Link dodatkowe jednostki DEV/legacy (rider-face, preview). Przydatne
               gdy potrzebujesz trybu S11 lub narzędzi eksperymentalnych.
  -h, --help   Wyświetl pomoc.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-dev)
      WITH_DEV=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Nieznany argument: $1" >&2
      usage
      exit 2
      ;;
  esac
  shift
done

# ALLOWLIST: tylko te jednostki będą linkowane/enablowane — wszystkie inne „rider-*.service/target” zostaną usunięte
ALLOW_UNITS=(
  "rider-broker.service"
  "rider-api.service"
  "rider-vision.service"
  "rider-boot-splash.service"
  "rider-minimal.target"
  "camera-capture@.service"          # uniwersalna usługa capture (CAPTURE_MODE=%i)
  "frame-distributor.service"
  "rider-obstacle.service"           # obstacle ROI detector
  "jupyter.service"
  "rider-dev.target"
  "rider-web-bridge.service"
# "rider-voice.socket"
  "rider-voice.service"
  "rider-voice-web.service"
  "rider-choreographer.service"      # choreography/event orchestration
  "wifi-unblock.service"
  # -- Dodane nowe usługi:
  "rider-google-bridge.service"
  "rider-mapper.service"
  "rider-odometry.service"
  "rider-tracker.service"
  "rider-tracking-controller.service"
  "rider-navigator.service"
  "rider-vision-offload.service"
  "rider-tracker.target"
  "rider-obstacle.target"
  "rider-ai-provider.target"
  "rider-core.target"
  "rider-followme.target"
  "rider-recon.target"
  "rider-voice.target"
  "rider-mapbuild.target"
  "rider-navigate.target"
  "audio-input.target"
  "audio-output.target"
  "lcd-renderer.service"
  "sensor-reader.service"
  "motion-executor.service"
)

DEV_UNITS=(
  "rider-face.service"
  "rider-cam-preview.service"
  "rider-edge-preview.service"
  "rider-ssd-preview.service"
)

if [[ "$WITH_DEV" -eq 1 ]]; then
  ALLOW_UNITS+=("${DEV_UNITS[@]}")
fi

# Usługi/targety, które muszą być zawsze „enabled” (baseline)
BASE_ENABLE=( "getty@tty1.service" "ssh.service" "dhcpcd.service" )

# Funkcja: wymagaj uprawnień sudo jeśli nie jesteśmy rootem
need_sudo() { [[ "$EUID" -eq 0 ]] || sudo -v; }
# Funkcja: loguj komunikaty z prefiksem
log() { echo "[systemd_sync] $*"; }

# Funkcja: sprawdza, czy plik-jednostka istnieje (plik lub link) w katalogu REPO_DIR
unit_source_path() {
  local unit="$1"
  if [[ -e "${REPO_DIR}/$unit" ]]; then
    printf "%s/%s\n" "$REPO_DIR" "$unit"
    return 0
  fi
  if [[ "$WITH_DEV" -eq 1 && -e "${LEGACY_DIR}/$unit" ]]; then
    printf "%s/%s\n" "$LEGACY_DIR" "$unit"
    return 0
  fi
  return 1
}
file_in_repo() { unit_source_path "$1" >/dev/null; }
# Funkcja: zwraca pełną ścieżkę jednostki w systemd
etc_unit_path() { echo "${ETC_DIR}/$1"; }
# Funkcja: sprawdza, czy nazwa jednostki jest w ALLOW_UNITS
in_allow() {
  local x="$1"
  for a in "${ALLOW_UNITS[@]}"; do
    [[ "$a" == "$x" ]] && return 0
  done
  return 1
}

# 0) Przygotowanie katalogu repo i uprawnień
mkdir -p "$REPO_DIR"
need_sudo

log "Ustawiam domyślny target na multi-user.target"
sudo systemctl set-default multi-user.target
if [[ "$WITH_DEV" -eq 1 ]]; then
  log "Tryb --with-dev: dodatkowe jednostki DEV z legacy zostaną podlinkowane"
fi

# 1) Backup istniejących rider-*.service/.target w /etc
log "Backup rider-* do: $BACKUP_DIR"
sudo mkdir -p "$BACKUP_DIR"
sudo find "$ETC_DIR" -maxdepth 1 \( -type f -o -type l \) -regextype posix-extended \
     -regex '.*/rider-.*\.(service|target)' -print0 \
     | sudo xargs -0 -I{} cp -a "{}" "$BACKUP_DIR" || true

# 2) Włącz baseline-usługi
for u in "${BASE_ENABLE[@]}"; do
  log "Enable baseline: $u"
  sudo systemctl enable "$u" || true
done

# 3) Tworzenie symlinków dla jednostek z allow-listy, jeśli istnieją w repo
log "Tworzę symlinki dla allow-listy -> ${REPO_DIR}/*${WITH_DEV:+ (+legacy)}"
for u in "${ALLOW_UNITS[@]}"; do
  src_path="$(unit_source_path "$u" || true)"
  if [[ -n "${src_path:-}" ]]; then
    dst="$(etc_unit_path "$u")"
    if [[ -e "$dst" && ! -L "$dst" ]]; then
      sudo rm -f "$dst"
    fi
    sudo ln -sfn "$src_path" "$dst"
  else
    log "POMIJAM (brak pliku w repo): $u"
  fi
done

# 4) Usuwanie niezarządzanych rider-* jednostek, których nie ma na allow-liście lub nie ma pliku w repo
log "Czyszczę niezarządzane rider-* w /etc/systemd/system"
while IFS= read -r -d '' etcu; do
  bn="$(basename "$etcu")"
  if ! in_allow "$bn" || ! file_in_repo "$bn"; then
    log "Usuwam niezarządzane: $bn"
    sudo systemctl disable --now "$bn" 2>/dev/null || true
    sudo rm -f "$etcu"
    sudo rm -f "/etc/systemd/system/multi-user.target.wants/$bn" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/graphical.target.wants/$bn" 2>/dev/null || true
  fi
done < <(find "$ETC_DIR" -maxdepth 1 \( -type f -o -type l \) -regextype posix-extended \
           -regex '.*/rider-.*\.(service|target)' -print0)

# 5) Usuwanie drop-in katalogów rider-*.service.d (repo przechowuje pełne definicje)
log "Usuwam drop-iny rider-*.service.d (jeśli były)"
sudo find "$ETC_DIR" -maxdepth 1 -type d -name 'rider-*.service.d' -exec rm -rf {} + 2>/dev/null || true

# 6) Reload systemd i włączanie specyficznych jednostek
log "systemctl daemon-reload"
sudo systemctl daemon-reload
for u in "${ALLOW_UNITS[@]}"; do
  case "$u" in
    rider-minimal.target|rider-boot-splash.service)
      log "Enable rider unit: $u"
      sudo systemctl enable "$u" || true
      ;;
    *)
      : ;;  # inne jednostki startowane są ręcznie lub poprzez Wants/
  esac
done

# 7) Maskowanie przestarzałej jednostki „legacy”
for u in rider-dispatcher.service; do
  log "Wyłączam legacy (jeśli istnieje): $u"
  sudo systemctl disable --now "$u" 2>/dev/null || true
  sudo systemctl mask "$u" 2>/dev/null || true
done

# 8) Weryfikacja stanu jednostek rider-*
echo
echo "== Weryfikacja rider-* =="
printf "%-32s %-10s %-10s %s\n" UNIT ENABLED ACTIVE TARGET
while IFS= read -r -d '' u; do
  bn="$(basename "$u")"
  enabled="$(systemctl is-enabled "$bn" 2>/dev/null || echo 'n/a')"
  active="$(systemctl is-active  "$bn" 2>/dev/null || echo 'n/a')"
  target="$(readlink -f "$u" || echo '-')"
  printf "%-32s %-10s %-10s %s\n" "$bn" "$enabled" "$active" "$target"
done < <(find "$ETC_DIR" -maxdepth 1 \( -type f -o -type l \) -regextype posix-extended \
            -regex '.*/rider-.*\.(service|target)' -print0)

echo
log "DONE. Po sync: reboot jest wskazany."
