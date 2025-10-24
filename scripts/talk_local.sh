#!/usr/bin/env bash
set -euo pipefail
DUR="${1:-3}"  # długość nagrania w sekundach

echo "[REC] Mów przez $DUR s…"
arecord -D plughw:0,0 -f S16_LE -r 16000 -c 1 /tmp/in.wav -d "$DUR" >/dev/null

echo "[ASR] Rozpoznaję…"
TXT=$(curl -s -X POST 'http://127.0.0.1:8092/api/asr' \
  -H 'Content-Type: audio/wav' --data-binary @/tmp/in.wav | jq -r '.text')

echo "[ASR] >> $TXT"

if [ -n "$TXT" ] && [ "$TXT" != "null" ]; then
  echo "[TTS] Odpowiadam…"
  curl -s -X POST 'http://127.0.0.1:8092/api/tts' \
    -H 'Content-Type: application/json' \
    -d "{\"text\":\"$TXT\",\"backend\":\"piper\",\"voice\":\"pl_PL-gosia-medium.onnx\"}" \
    -o /tmp/out.wav
  aplay /tmp/out.wav
else
  echo "[TTS] Cisza (nic nie rozpoznano)."
fi
