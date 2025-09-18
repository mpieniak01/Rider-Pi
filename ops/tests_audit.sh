#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_DIR="$ROOT/tests"
OUT_DIR="$TEST_DIR"
REPORT_CSV="$OUT_DIR/_audit_report.csv"
SUGG_DEL="$OUT_DIR/_suggested_delete.txt"
SUGG_MIG="$OUT_DIR/_suggested_migrate.txt"
PY_AUDITOR="$OUT_DIR/_audit_import.py"

# kolorki
red() { printf "\e[31m%s\e[0m\n" "$*"; }
grn() { printf "\e[32m%s\e[0m\n" "$*"; }
ylw() { printf "\e[33m%s\e[0m\n" "$*"; }

if [[ ! -d "$TEST_DIR" ]]; then
  red "Brak katalogu tests/ → $TEST_DIR"
  exit 1
fi

# nagłówek raportu
echo "path,is_pytest,imports_apps,imports__apps,uses_legacy_endpoints,exec_shebang,syntax_ok,import_ok,suggest" > "$REPORT_CSV"
: > "$SUGG_DEL"
: > "$SUGG_MIG"

# proste detektory
detect_pytest() {
  # test_* albo class Test*, lub 'pytest'
  grep -E -q '(^|\s)(def\s+test_|class\s+Test|pytest\.)' "$1" 2>/dev/null
}

detect_imports_apps() {
  grep -E -q 'from\s+apps\.|import\s+apps(\W|$)' "$1" 2>/dev/null
}

detect_imports__apps() {
  grep -E -q 'from\s+_apps\.|import\s+_apps(\W|$)' "$1" 2>/dev/null
}

detect_legacy_endpoints() {
  # stary kontrakt ruchu wg notatek: GET /api/move|/api/stop oraz stare ścieżki
  grep -E -q '/api/(move|stop)\b|/face_lcd|/st77|/lcd_presenter' "$1" 2>/dev/null
}

has_shebang_exec() {
  head -1 "$1" 2>/dev/null | grep -q '^#!/'
}

syntax_ok() {
  python3 -m pyflakes "$1" >/dev/null 2>&1 || python3 -m py_compile "$1" >/dev/null 2>&1
}

import_ok() {
  python3 "$PY_AUDITOR" "$1" >/dev/null 2>&1
}

# upewnij się, że helper istnieje
if [[ ! -f "$PY_AUDITOR" ]]; then
  cat > "$PY_AUDITOR" <<'PY'
import importlib.util, sys, ast, os
path = sys.argv[1]
spec = importlib.util.spec_from_file_location(os.path.basename(path).replace('.py',''), path)
if spec is None or spec.loader is None:
    sys.exit(1)
with open(path, 'rb') as f:
    ast.parse(f.read(), filename=path)
sys.exit(0)
PY
fi

shopt -s nullglob
files=("$TEST_DIR"/*.py "$TEST_DIR"/*/*.py "$TEST_DIR"/*/*/*.py)
if (( ${#files[@]} == 0 )); then
  ylw "Brak plików .py w tests/"
fi

for f in "${files[@]}"; do
  rel="${f#$ROOT/}"
  is_pytest="no"; detect_pytest "$f" && is_pytest="yes"
  imp_apps="no";  detect_imports_apps "$f" && imp_apps="yes"
  imp__apps="no"; detect_imports__apps "$f" && imp__apps="yes"
  legacy="no";    detect_legacy_endpoints "$f" && legacy="yes"
  sheb="no";      has_shebang_exec "$f" && sheb="yes"

  syn="ok"; syntax_ok "$f" || syn="fail"
  imp="ok"; import_ok "$f" || imp="fail"

  suggest="keep"
  if [[ "$imp__apps" == "yes" || "$legacy" == "yes" ]]; then
    if [[ "$is_pytest" == "yes" ]]; then
      suggest="migrate"
      echo "$rel  — importuje _apps/legacy → MIGRACJA" >> "$SUGG_MIG"
    else
      suggest="delete"
      echo "$rel  — legacy / nie-pytest → USUNIĘCIE" >> "$SUGG_DEL"
    fi
  elif [[ "$syn" == "fail" || "$imp" == "fail" ]]; then
    suggest="migrate"
    echo "$rel  — błędy składni/importu → NAPRAWA/MIGRACJA" >> "$SUGG_MIG"
  fi

  echo "$rel,$is_pytest,$imp_apps,$imp__apps,$legacy,$sheb,$syn,$imp,$suggest" >> "$REPORT_CSV"
done

grn "Raport: $REPORT_CSV"
ylw "Kandydaci do usunięcia: $SUGG_DEL"
ylw "Kandydaci do migracji:  $SUGG_MIG"
