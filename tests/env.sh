#!/usr/bin/env bash
# Wspólne helpery dla testów Rider-Pi Web Bridge
set -euo pipefail

# HOST:PORT (argument > zmienna > domyślnie 127.0.0.1:8081)
HOSTPORT="${1:-${HOSTPORT:-127.0.0.1:8081}}"
BASE_URL="http://${HOSTPORT}"

CURL_BIN="${CURL_BIN:-curl}"
CURL="${CURL_BIN} -sS --fail --connect-timeout 2 --max-time 5"

json() { jq -c . 2>/dev/null || cat; }

http_code() {
  # $1 = method, $2 = url, $3 = optional data
  local m="$1" u="$2" d="${3:-}"
  if [[ -n "$d" ]]; then
    ${CURL} -o /dev/null -w "%{http_code}" -X "${m}" -H "Content-Type: application/json" -d "${d}" "${u}" || echo "000"
  else
    ${CURL} -o /dev/null -w "%{http_code}" -X "${m}" "${u}" || echo "000"
  fi
}

req_get()   { ${CURL} -X GET    "${BASE_URL}$1"; }
req_post()  { ${CURL} -X POST   -H "Content-Type: application/json" -d "$2" "${BASE_URL}$1"; }

supports_post_move() {
  # Wyślij minimalny, bardzo krótki ruch (deadman i tak zabezpieczy)
  local payload='{"vx":0,"vy":0,"yaw":0,"duration":0.05}'
  local code; code="$(http_code POST "${BASE_URL}/api/move" "${payload}")"
  [[ "${code}" == "200" ]]
}

move_get() {
  # $1 dir, $2 v (0..1), $3 t (s), $4 w (0..1, opcjonalne dla skrętu)
  local dir="${1:-forward}" v="${2:-0.22}" t="${3:-0.25}" w="${4:-0.18}"
  req_get "/api/move?dir=${dir}&v=${v}&w=${w}&t=${t}"
}

move_post() {
  # $1 vx, $2 vy, $3 yaw, $4 duration
  local vx="${1:-0.22}" vy="${2:-0}" yaw="${3:-0}" dur="${4:-0.25}"
  local payload
  payload=$(jq -nc --argjson vx "${vx}" --argjson vy "${vy}" --argjson yaw "${yaw}" --argjson d "${dur}" \
    '{vx:$vx,vy:$vy,yaw:$yaw,duration:$d}') || payload='{"vx":0.22,"vy":0,"yaw":0,"duration":0.25}'
  req_post "/api/move" "${payload}"
}

stop_get()  { req_get  "/api/stop"; }
stop_post() { req_post "/api/stop" "{}"; }

health()    { req_get "/healthz" || true; }
