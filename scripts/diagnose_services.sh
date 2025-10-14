#!/usr/bin/env bash
# Rider-Pi: diagnoza i sterowanie usługami przez API (bez uśmiercania API)
# Użycie:
#   scripts/diagnose_services.sh                    # http://127.0.0.1:8080
#   scripts/diagnose_services.sh http://pi:8080     # inny host

set -euo pipefail

API_BASE="${1:-http://127.0.0.1:8080}"
CURL="curl -sS"             # bez -f -> nie zrywa potoku; błędy pokażemy czytelnie
JQ_BIN="${JQ_BIN:-jq}"

NAMES_ORDER=(broker web motion cam edge ssd obstacle api)  # api NA KOŃCU i TYLKO STATUS!

# --- kolory ---
if [[ -t 1 ]]; then C_OK=$'\e[32m'; C_ERR=$'\e[31m'; C_WARN=$'\e[33m'; C_DIM=$'\e[2m'; C_OFF=$'\e[0m';
else C_OK=""; C_ERR=""; C_WARN=""; C_DIM=""; C_OFF=""; fi

need() { command -v "$1" >/dev/null 2>&1 || { echo "${C_ERR}Brak: $1${C_OFF}"; exit 1; }; }
need curl; need "${JQ_BIN}"

echo "${C_DIM}API:${C_OFF} ${API_BASE}"

# ---- helpers ----
wait_api() {
  local tries="${1:-10}"
  for ((i=1;i<=tries;i++)); do
    if ${CURL} -H 'Accept: application/json' "${API_BASE}/healthz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

have_status_route=""   # wykryjemy, czy istnieje GET /svc/<name>
detect_status_route() {
  if ${CURL} -H 'Accept: application/json' "${API_BASE}/svc/cam" | grep -q '{'; then
    have_status_route="yes"
  else
    have_status_route="no"
  fi
}

svc_list_json=""  # cache listy do fallbacku
load_svc_list() {
  svc_list_json="$(${CURL} -H 'Accept: application/json' "${API_BASE}/svc" 2>/dev/null || echo '')"
}

status_via_list() {
  local name="$1" unit active enabled sub
  unit="$(${JQ_BIN} -r --arg n "$name" '
    .services[] | select(.unit|test($n;"i") or .desc|test($n;"i")) | .unit' <<<"$svc_list_json" | head -n1)"
  [[ -z "$unit" ]] && return 1
  active="$(${JQ_BIN} -r --arg u "$unit" '.services[]|select(.unit==$u)|.active' <<<"$svc_list_json")"
  enabled="$(${JQ_BIN} -r --arg u "$unit" '.services[]|select(.unit==$u)|.enabled' <<<"$svc_list_json")"
  sub="$(${JQ_BIN} -r --arg u "$unit" '.services[]|select(.unit==$u)|.sub' <<<"$svc_list_json")"
  printf '{"unit":"%s","active":"%s","enabled":"%s","sub":"%s"}\n' "$unit" "$active" "$enabled" "$sub"
  return 0
}

svc_status() {
  local name="$1" out rc=0
  if [[ "$have_status_route" == "yes" ]]; then
    out="$(${CURL} -H 'Accept: application/json' "${API_BASE}/svc/${name}" 2>/dev/null || true)"
    [[ -n "$out" && "$out" != *"METHOD NOT ALLOWED"* ]] && { echo "$out"; return 0; }
  fi
  # fallback z listy
  [[ -z "$svc_list_json" ]] && load_svc_list
  status_via_list "$name"
}

svc_action() {
  local name="$1" action="$2"
  ${CURL} -X POST "${API_BASE}/svc/${name}" \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    --data "{\"action\":\"${action}\"}"
}

print_status() {
  local name="$1" json="$2"
  local active enabled sub
  active="$(echo "$json" | ${JQ_BIN} -r '.active // .status.active // empty')"
  enabled="$(echo "$json" | ${JQ_BIN} -r '.enabled // .status.enabled // empty')"
  sub="$(echo "$json"   | ${JQ_BIN} -r '.sub // .status.sub // empty')"
  printf "  - %-10s active=%-8s enabled=%-8s sub=%s\n" "${name}" "${active}" "${enabled}" "${sub}"
}

# ---- start ----
if ! wait_api 10; then
  echo "${C_ERR}API nie odpowiada na /healthz${C_OFF}"
  exit 1
fi

# wykryj routy i wczytaj listę (fallback)
detect_status_route
load_svc_list

pass=0; warn=0; fail=0

for name in "${NAMES_ORDER[@]}"; do
  echo "${C_DIM}==> ${name}${C_OFF}"

  # STATUS
  st_json="$(svc_status "$name" || true)"
  if [[ -n "$st_json" && "$st_json" == *"active"* ]]; then
    print_status "$name" "$st_json"
  else
    echo "  ${C_WARN}WARN:${C_OFF} status niedostępny (GET /svc/${name} i fallback z /svc)"
    ((warn++)) || true
  fi

  # Dla api: tylko status, bez akcji
  if [[ "$name" == "api" ]]; then
    echo "  ${C_WARN}SKIP:${C_OFF} akcje na 'api' pominięte (to bieżący serwer HTTP)"
    ((warn++)) || true
    echo
    continue
  fi

  # START
  out="$(svc_action "$name" "start" 2>/dev/null || true)"
  ok="$(echo "$out" | ${JQ_BIN} -r '.ok // empty' 2>/dev/null || true)"
  if [[ "$ok" == "true" ]]; then
    echo "  ${C_OK}OK:${C_OFF} start"
    ((pass++)) || true
  else
    echo "  ${C_ERR}FAIL:${C_OFF} start"
    [[ -n "$out" ]] && echo "$out" | ${JQ_BIN} -C '.results? // .' | sed 's/^/    /'
    ((fail++)) || true
  fi
  wait_api 10 || echo "  ${C_WARN}WARN:${C_OFF} /healthz nie wrócił po starcie"

  # RESTART
  out="$(svc_action "$name" "restart" 2>/dev/null || true)"
  ok="$(echo "$out" | ${JQ_BIN} -r '.ok // empty' 2>/dev/null || true)"
  if [[ "$ok" == "true" ]]; then
    echo "  ${C_OK}OK:${C_OFF} restart"
    ((pass++)) || true
  else
    echo "  ${C_ERR}FAIL:${C_OFF} restart"
    [[ -n "$out" ]] && echo "$out" | ${JQ_BIN} -C '.results? // .' | sed 's/^/    /'
    ((fail++)) || true
  fi
  wait_api 10 || echo "  ${C_WARN}WARN:${C_OFF} /healthz nie wrócił po restarcie"

  # STOP (nie zatrzymujemy core’ów)
  case "$name" in
    broker|web)
      echo "  ${C_WARN}SKIP:${C_OFF} stop (${name} to usługa bazowa)"
      ((warn++)) || true
      ;;
    *)
      out="$(svc_action "$name" "stop" 2>/dev/null || true)"
      ok="$(echo "$out" | ${JQ_BIN} -r '.ok // empty' 2>/dev/null || true)"
      if [[ "$ok" == "true" ]]; then
        echo "  ${C_OK}OK:${C_OFF} stop"
        ((pass++)) || true
      else
        echo "  ${C_ERR}FAIL:${C_OFF} stop"
        [[ -n "$out" ]] && echo "$out" | ${JQ_BIN} -C '.results? // .' | sed 's/^/    /'
        ((fail++)) || true
      fi
      ;;
  esac

  # STATUS po operacjach
  st_json="$(svc_status "$name" || true)"
  [[ -n "$st_json" ]] && print_status "$name" "$st_json"
  echo
done

echo "=== PODSUMOWANIE ==="
echo "  ${C_OK}OK:${C_OFF}    $pass"
echo "  ${C_WARN}WARN:${C_OFF}  $warn"
echo "  ${C_ERR}FAIL:${C_OFF}  $fail"
(( fail > 0 )) && exit 1 || exit 0
