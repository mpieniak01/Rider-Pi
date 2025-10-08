#!/usr/bin/env bash
set -euo pipefail

# 0) Zaczytaj zmienne z profilu (login/non-login shell)
#    Nie dotykamy Twoich plików; tylko je source'ujemy jeśli istnieją.
if [ -f "$HOME/.bash_profile" ]; then
  # shellcheck disable=SC1090
  . "$HOME/.bash_profile"
elif [ -f "$HOME/.profile" ]; then
  # shellcheck disable=SC1090
  . "$HOME/.profile"
fi

# 1) Bazowy klucz bierzemy ZAWSZE z OPENAI_API_KEY z profilu
BASE_KEY="${OPENAI_API_KEY:-}"
if [[ -z "$BASE_KEY" ]]; then
  echo "❌ Brak OPENAI_API_KEY w ~/.bash_profile (lub ~/.profile)."
  echo "   Dodaj tam: export OPENAI_API_KEY='sk-proj-…' (lub 'sk-…') i otwórz nową sesję."
  exit 1
fi

# 2) ALSA aliasy (jeśli używasz pliku z repo)
export ALSA_CONFIG_PATH="${ALSA_CONFIG_PATH:-$PWD/config/alsa/asoundrc.wm8960}"

# 3) Pobierz ephemeral do Realtime
RESP="$(curl -sS https://api.openai.com/v1/realtime/sessions \
  -H "Authorization: Bearer $BASE_KEY" \
  -H "Content-Type: application/json" \
  -H "OpenAI-Beta: realtime=v1" \
  -d '{"model":"gpt-4o-realtime-preview-2024-12-17","voice":"alloy"}')"

EPH="$(printf '%s' "$RESP" | jq -r '.client_secret.value')"
if [[ -z "$EPH" || "$EPH" == "null" || "${EPH:0:3}" != "ek_" ]]; then
  echo "❌ Nie udało się pobrać ephemerala. Odpowiedź API:"
  printf '%s\n' "$RESP" | jq .
  exit 1
fi
echo "ℹ️ Realtime session OK (ephemeral ek_****)."

# 4) Start PTT stream – BEZ ‘exec’ (terminal zostaje)
OPENAI_API_KEY="$EPH" \
VOICE_WS_LOG=${VOICE_WS_LOG:-1} \
VOICE_WS_DUMP=${VOICE_WS_DUMP:-1} \
python -m apps.voice.main --config voice_streaming.toml --lang pl ptt --mode stream
