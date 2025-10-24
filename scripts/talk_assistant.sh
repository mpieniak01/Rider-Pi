#!/usr/bin/env bash
set -euo pipefail

say_wav() {
  local msg="$1"
  curl -s -X POST 'http://127.0.0.1:8092/api/tts' \
    -H 'Content-Type: application/json' \
    -d "{\"text\":\"$msg\",\"backend\":\"piper\",\"voice\":\"pl_PL-gosia-medium.onnx\"}" \
    -o /tmp/out.wav
  aplay /tmp/out.wav >/dev/null 2>&1 || true
}

while true; do
  echo "[REC] Mów (3 s)…"
  arecord -D plughw:0,0 -f S16_LE -r 16000 -c 1 /tmp/in.wav -d 3 >/dev/null
  TXT=$(curl -s -X POST 'http://127.0.0.1:8092/api/asr' \
    -H 'Content-Type: audio/wav' --data-binary @/tmp/in.wav | jq -r '.text')
  echo "[ASR] >> $TXT"

  [ -z "$TXT" ] || [ "$TXT" = "null" ] && continue

  # normalizacja
  L=$(echo "$TXT" | tr '[:upper:]' '[:lower:]')

  if echo "$L" | grep -q "która jest godzina"; then
    say_wav "Jest $(date +'%H:%M')."
  elif echo "$L" | grep -qE 'powtórz|echo'; then
    say_wav "Powtarzam: $TXT"
  elif echo "$L" | grep -qE 'stop|koniec|zakończ'; then
    say_wav "Kończę pętlę nasłuchu."
    break
  else
    # domyślna odpowiedź
    say_wav "Usłyszałem: $TXT"
  fi
done
