#!/usr/bin/env bash
# Rider-Pi — repo-first systemd sync (ALLOWLIST)
# Utrzymuje tylko wskazane unity jako symlinki do ~/robot/systemd/*
# Idempotentny, bez reimportu z /etc do repo.

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/robot}"
REPO_DIR="${REPO_ROOT}/systemd"
ETC_DIR="/etc/systemd/system"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="${ETC_DIR}/_rider_backup_${STAMP}"

# ALLOWLIST: tylko to linkujemy/enablujemy
ALLOW_UNITS=(
  "rider-broker.service"
  "rider-api.service"
  "rider-vision.service"
  "rider-motion-bridge.service"
  "rider-boot-prepare.service"
  "rider-minimal.target"
  "rider-edge-preview.service"   # edge preview (Canny)
  "rider-obstacle.service"       # obstacle ROI detector
  "rider-cam-preview.service"     # raw preview (no LCD when DISABLE_LCD=1)
  "rider-ssd-preview.service"   # linkujemy, bez enable — start wg Wants/ lub ręcznie
  "jupyter.service"
  "rider-dev.target"
)

BASE_ENABLE=( "getty@tty1.service" "ssh.service" "dhcpcd.service" )

need_sudo() { [[ "$EUID" -eq 0 ]] || sudo -v; }
log() { echo "[systemd_sync] $*"; }

file_in_repo() { [[ -f "${REPO_DIR}/$1" ]]; }
etc_unit_path() { echo "${ETC_DIR}/$1"; }
in_allow() {
  local x="$1"
  for a in "${ALLOW_UNITS[@]}"; do [[ "$a" == "$x" ]] && return 0; done
  return 1
}

# 0) sanity
mkdir -p "$REPO_DIR"
need_sudo

log "Ustawiam domyślny target na multi-user.target"
sudo systemctl set-default multi-user.target

# 1) Backup rider-* (*.service/*.target), bez katalogów *.service.d
log "Backup rider-* do: $BACKUP_DIR"
sudo mkdir -p "$BACKUP_DIR"
# poprawne grupowanie warunków 'find'
sudo find "$ETC_DIR" -maxdepth 1 \( -type f -o -type l \) -regextype posix-extended \
  -regex '.*/rider-.*\.(service|target)' -print0 \
  | sudo xargs -0 -I{} cp -a "{}" "$BACKUP_DIR" || true

# 2) Baseline dostępności
for u in "${BASE_ENABLE[@]}"; do
  log "Enable baseline: $u"
  sudo systemctl enable "$u" || true
done

# 3) Linkuj TYLKO allowlistę, jeśli plik istnieje w repo
log "Tworzę symlinki dla allowlisty -> ${REPO_DIR}/*"
for u in "${ALLOW_UNITS[@]}"; do
  if file_in_repo "$u"; then
    dst="$(etc_unit_path "$u")"
    # jeżeli istnieje zwykły plik → usuń i zastąp linkiem
    if [[ -e "$dst" && ! -L "$dst" ]]; then sudo rm -f "$dst"; fi
    sudo ln -sfn "${REPO_DIR}/$u" "$dst"
  else
    log "POMIJAM (brak w repo): $u"
  fi
done

# 4) Usuń z /etc/systemd/system wszystkie rider-* których NIE ma w allowliście lub nie istnieją w repo
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

# 5) Usuń drop-iny rider-*.service.d (repo trzyma pełne definicje)
log "Usuwam drop-iny rider-*.service.d (jeśli były)"
sudo find "$ETC_DIR" -maxdepth 1 -type d -name 'rider-*.service.d' -exec rm -rf {} + 2>/dev/null || true

# 6) Reload + enable tam gdzie trzeba
log "systemctl daemon-reload"
sudo systemctl daemon-reload

for u in "${ALLOW_UNITS[@]}"; do
  case "$u" in
    rider-minimal.target|rider-boot-prepare.service)
      log "Enable rider unit: $u"
      sudo systemctl enable "$u" || true
      ;;
    *)
      : ;;  # reszta startuje wg Wants/ ręcznie
  esac
done

# 7) Legacy mask (jeśli krąży)
for u in rider-dispatcher.service; do
  log "Wyłączam legacy (jeśli istnieje): $u"
  sudo systemctl disable --now "$u" 2>/dev/null || true
  sudo systemctl mask "$u" 2>/dev/null || true
done

# 8) Weryfikacja
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
