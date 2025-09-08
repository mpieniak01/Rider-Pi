#!/usr/bin/env bash
# tests/api_compare.sh — porównanie starego vs nowego API (kanonizacja JSON)
set -euo pipefail

BASE_OLD="${BASE_OLD:-http://127.0.0.1:8080}"
BASE_NEW="${BASE_NEW:-http://127.0.0.1:8090}"
OUT_DIR="tests/out"
CURL="curl -fsS"
JQ_BIN="${JQ:-jq}"

# wykryj jq (wymagane do kanonizacji)
if ! command -v "$JQ_BIN" >/dev/null 2>&1; then
  echo "[ERR] Wymagany jest jq (zainstaluj lub ustaw JQ=/sciezka/do/jq)" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"

# uniwersalny 'walk' i kanonizacja: liczby->0, stringi->"X"
JQ_WALK='def walk(f):
  def w: . as $in
    | if type == "object" then
        reduce keys[] as $key ({}; . + { ($key): ($in[$key] | w) }) | f
      elif type == "array" then map( w ) | f
      else f
      end;
  w;
'
JQ_CANON="$JQ_WALK walk(if type==\"number\" then 0 elif type==\"string\" then \"X\" else . end)"

# zestaw par endpointów: OLD -> NEW
declare -a PAIRS=(
  "/healthz /healthz"
  "/livez /livez"
  "/readyz /readyz"
  "/version /api/version"
  "/bus/health /api/bus/health"
  "/status /api/status"
  "/metrics /api/metrics"
  "/devices /api/devices"
  "/flags /api/flags"
  "/last_frame /api/last_frame"
)

fetch_and_canon() {
  local url="$1" outfile="$2"
  if ! $CURL "$url" -o "$outfile.raw" 2>"$outfile.err"; then
    echo "[WARN] $url: request failed (zapisano log błędu)."
    echo '{}' > "$outfile.json"
    echo '{}' > "$outfile.canon.json"
    return 1
  fi
  # spróbuj zdekodować jako JSON; jeśli to nie JSON (np. text/plain), zamień na pusty obiekt
  if ! cat "$outfile.raw" | "$JQ_BIN" . > "$outfile.json" 2>/dev/null; then
    echo '{}' > "$outfile.json"
  fi
  cat "$outfile.json" | "$JQ_BIN" "$JQ_CANON" > "$outfile.canon.json"
}

compare_pair() {
  local old_path="$1" new_path="$2"
  local old_url="${BASE_OLD}${old_path}"
  local new_url="${BASE_NEW}${new_path}"
  local base_old_sanit="${old_path//\//_}"
  local base_new_sanit="${new_path//\//_}"
  local out_old="$OUT_DIR/${base_old_sanit}__old"
  local out_new="$OUT_DIR/${base_new_sanit}__new"

  fetch_and_canon "$old_url" "$out_old" || true
  fetch_and_canon "$new_url" "$out_new" || true

  # posortuj klucze, żeby diff był stabilny
  "$JQ_BIN" -S . "$out_old.canon.json" > "$out_old.sorted.json"
  "$JQ_BIN" -S . "$out_new.canon.json" > "$out_new.sorted.json"

  if diff -u "$out_old.sorted.json" "$out_new.sorted.json" > "$OUT_DIR/${base_old_sanit}__vs__${base_new_sanit}.diff.txt"; then
    echo "PASS  $old_path  ==  $new_path"
  else
    echo "DIFF  $old_path  !=  $new_path    ->  $OUT_DIR/${base_old_sanit}__vs__${base_new_sanit}.diff.txt"
  fi
}

echo "[i] Porównuję BASE_OLD=$BASE_OLD  vs  BASE_NEW=$BASE_NEW"
for pair in "${PAIRS[@]}"; do
  read -r p_old p_new <<<"$pair"
  compare_pair "$p_old" "$p_new"
done
echo "[i] Wyniki/snapshoty: $OUT_DIR"
