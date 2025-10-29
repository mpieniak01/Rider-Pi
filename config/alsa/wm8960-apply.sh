#!/usr/bin/env bash
#config/alsa/wm8960-apply.sh
# Skrypt konfiguracyjny ALSA dla kodeka WM8960
# Ustawia routing i poziomy głośności
set -euo pipefail

# --- znajdź kontrolę miksera dla wm8960 ---
detect_ctl() {
  # 1) spróbuj po nazwie karty (najczytelniej)
  if amixer -c wm8960soundcard scontrols >/dev/null 2>&1; then
    echo "hw:wm8960soundcard"
    return 0
  fi
  # 2) spróbuj po numerze z /proc/asound/cards
  local num
  num="$(awk -F'[][: ]+' '/wm8960-soundcard/ {print $2; exit}' /proc/asound/cards 2>/dev/null || true)"
  if [[ -n "${num:-}" ]] && [[ -e "/dev/snd/controlC${num}" ]]; then
    echo "hw:${num}"
    return 0
  fi
  # 3) ostatnia próba: przejrzyj wszystkie controlC*
  for c in /dev/snd/controlC*; do
    [[ -e "$c" ]] || continue
    local idx="${c##*controlC}"
    if amixer -D "hw:${idx}" scontrols 2>/dev/null | grep -qi wm8960; then
      echo "hw:${idx}"
      return 0
    fi
  done
  return 1
}

CTL="$(detect_ctl || true)"
if [[ -z "${CTL:-}" ]]; then
  echo "[wm8960-apply] Brak dostępnego miksera WM8960 (CTL). Urządzenia ALSA nieaktywne." >&2
  exit 1
fi

echo "[wm8960-apply] Używam CTL=${CTL}"
sleep 0.5

# --- routing DAC → MIX → SPEAKER ---
amixer -D "${CTL}" sset 'Left Output Mixer PCM' on
amixer -D "${CTL}" sset 'Right Output Mixer PCM' on
amixer -D "${CTL}" sset 'Mono Output Mixer Left' on
amixer -D "${CTL}" sset 'Mono Output Mixer Right' on
amixer -D "${CTL}" sset 'Left Output Mixer Boost Bypass' on || true
amixer -D "${CTL}" sset 'Right Output Mixer Boost Bypass' on || true
amixer -D "${CTL}" sset 'Speaker AC' on || true 2>/dev/null
amixer -D "${CTL}" sset 'Speaker DC' off || true 2>/dev/null

# --- „złote” poziomy (dogadane wcześniej) ---
amixer -D "${CTL}" sset 'Speaker' 118
amixer -D "${CTL}" sset 'Playback' 245
amixer -D "${CTL}" sset 'PCM Playback -6dB' off
amixer -D "${CTL}" sset 'Headphone' 0% || true

# --- bez zbędnych filtrów ---
amixer -D "${CTL}" sset '3D' off || true
amixer -D "${CTL}" sset 'DAC Deemphasis' 0 || true 2>/dev/null
amixer -D "${CTL}" sset 'ADC High Pass Filter' off || true
