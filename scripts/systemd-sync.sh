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
ETC_DIR="/etc/systemd/system"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${ETC_DIR}/_rider_backup_${STAMP}"

# ALLOWLIST: tylko te jednostki będą linkowane/enablowane — wszystkie inne „rider-*.service/target” zostaną usunięte
ALLOW_UNITS=(
  "rider-broker.service"
  "rider-api.service"
  "rider-vision.service"
  "rider-motion-bridge.service"
  "rider-boot-prepare.service"
  "rider-minimal.target"
  "rider-edge-preview.service"       # edge preview (Canny)
  "rider-obstacle.service"           # obstacle ROI detector
  "rider-cam-preview.service"        # raw preview (no LCD when DISABLE_LCD=1)
  "rider-ssd-preview.service"        # linkujemy, bez enable — start wg Wants/ lub ręcznie
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
  "rider-post-splash.service"
  "rider-mapper.service"
  "rider-odometry.service"
  "rider-tracker.service"
  "rider-tracking-controller.service"
)

# Usługi/targety, które muszą być zawsze „enabled” (baseline)
BASE_ENABLE=( "getty@tty1.service" "ssh.service" "dhcpcd.service" )

# Funkcja: wymagaj uprawnień sudo jeśli nie jesteśmy rootem
need_sudo() { [[ "$EUID" -eq 0 ]] || sudo -v; }
# Funkcja: loguj komunikaty z prefiksem
log() { echo "[systemd_sync] $*"; }

# Funkcja: sprawdza, czy plik-jednostka istnieje (plik lub link) w katalogu REPO_DIR
file_in_repo() { [[ -e "${REPO_DIR}/$1" ]]; }
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
log "Tworzę symlinki dla allow-listy -> ${REPO_DIR}/*"
for u in "${ALLOW_UNITS[@]}"; do
  if file_in_repo "$u"; then
    dst="$(etc_unit_path "$u")"
    if [[ -e "$dst" && ! -L "$dst" ]]; then
      sudo rm -f "$dst"
    fi
    sudo ln -sfn "${REPO_DIR}/$u" "$dst"
  else
    log "POMIJAM (brak w repo): $u"
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
    rider-minimal.target|rider-boot-prepare.service)
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
