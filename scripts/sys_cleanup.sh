#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

# === Ustawienia ===
DRY_RUN=1
if [[ "${1:-}" == "--apply" ]]; then DRY_RUN=0; fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
QUAR_DIR="services/_quarantine_${STAMP}"
mkdir -p "$QUAR_DIR"

echo "== services cleanup =="
echo "Repo: $ROOT"
echo "Kwarantanna: $QUAR_DIR"
echo "Tryb: $([[ $DRY_RUN -eq 1 ]] && echo DRY-RUN || echo APPLY)"
echo

# helper: git-aware move
mv_git() {
  local src="$1" dst="$2"
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "[DRY] mv '$src' '$dst/'"
    return 0
  fi
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1 && git ls-files --error-unmatch "$src" >/dev/null 2>&1; then
    git mv -f "$src" "$dst"/
  else
    mv -f "$src" "$dst"/
  fi
}

# === Lista celów do przeniesienia ===
declare -a TARGETS=(
  # legacy alternatywny serwer
  "services/_status_api.py"

  # backupy / checkpointy api_server
  "services/api_server.py.bak"
  "services/api_server.py.bak.*"
  "services/api_server.py.bak-*"
  "services/.ipynb_checkpoints/api_server*.py*"

  # backup chat_glue
  "services/api_core/chat_glue.py.bak*"

  # globalne ipynb checkpointy
  "services/.ipynb_checkpoints/*"
  "services/api_core/.ipynb_checkpoints/*"
)

echo "== Kandydaci do przeniesienia =="
COUNT=0
for pat in "${TARGETS[@]}"; do
  for f in $pat; do
    [[ -e "$f" ]] || continue
    printf " - %s\n" "$f"
    ((COUNT++)) || true
  done
done
[[ $COUNT -eq 0 ]] && echo "(brak plików do przeniesienia)"

echo
if [[ $DRY_RUN -eq 1 ]]; then
  echo "== DRY-RUN: nic nie zmieniam. Uruchom z --apply aby wykonać =="
else
  echo "== APPLY: przenoszę pliki do $QUAR_DIR =="
  for pat in "${TARGETS[@]}"; do
    for f in $pat; do
      [[ -e "$f" ]] || continue
      mv_git "$f" "$QUAR_DIR"
    done
  done
  echo "✔ przeniesiono."
fi

echo
echo "== Szybki audyt po sprzątaniu =="
echo "-- HTTP serwery w kodzie (Flask/routes) --"
grep -RIn --line-number --color \
  -e "Flask" -e "@app.route" -e "add_url_rule" \
  services | grep -v ".ipynb_checkpoints" || true

echo
echo "-- Entry-pointy systemd (exec + pliki) --"
systemctl show -p ExecStart -p FragmentPath rider-api.service 2>/dev/null | sed 's/; /\n/g' || true
systemctl show -p ExecStart -p FragmentPath rider-web-bridge.service 2>/dev/null | sed 's/; /\n/g' || true
systemctl show -p ExecStart -p FragmentPath rider-broker.service 2>/dev/null | sed 's/; /\n/g' || true

echo
echo "-- Porty nasłuchu (8080/8081/5555/5556) --"
ss -ltnp | awk 'NR==1 || $4 ~ /:8080$|:8081$|:5555$|:5556$/'
