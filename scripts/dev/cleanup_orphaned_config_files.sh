#!/bin/bash
#
# !!! UWAGA: URUCHOMIĆ RĘCZNIE (FAZA 4) !!!
#
# Ten skrypt usuwa osierocone pliki konfiguracyjne po pełnej migracji
# na system .toml (zakończenie Fazy 3).
# Uruchom ten skrypt tylko po pomyślnych testach manualnych
# i wdrożeniu Fazy 3.
#
set -euo pipefail
BASE_DIR=$(realpath "$(dirname "$0")/../..")
cd "$BASE_DIR"

echo "== Skrypt Czyszczący (Faza 4) =="
echo ""
echo "UWAGA: Ten skrypt usunie osierocone pliki z poprzedniego systemu konfiguracji."
echo "Upewnij się, że:"
echo "  1. Faza 3 została w pełni wdrożona i przetestowana"
echo "  2. Wszystkie usługi działają poprawnie z konfiguracją .toml"
echo "  3. Masz aktualną kopię zapasową systemu"
echo ""
read -p "Czy chcesz kontynuować? (tak/nie): " -r
if [[ ! $REPLY =~ ^(tak|TAK|t|T)$ ]]; then
  echo "Anulowano."
  exit 0
fi

# Pliki do usunięcia:
FILES_TO_REMOVE=(
  "scripts/util_export-env.sh"
  "systemd/robot.env"
)

echo ""
echo "Usuwanie osieroconych plików:"
for f in "${FILES_TO_REMOVE[@]}"; do
  if [ -f "$f" ]; then
    echo "  Usuwanie: $f"
    rm -f "$f"
  else
    echo "  Plik już usunięty (OK): $f"
  fi
done

echo ""
echo "Czyszczenie zakończone."
echo "Uruchom 'git status', aby zobaczyć zmiany i zatwierdzić usunięcie plików."
