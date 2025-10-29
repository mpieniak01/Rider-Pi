#!/usr/bin/env bash
#config/alsa/wm8960-mixer.sh
set -e
card=0
amixer -c $card sset 'Headphone' 80% unmute 2>/dev/null || true
amixer -c $card sset 'Speaker'   80% unmute 2>/dev/null || true
amixer -c $card sset 'PCM'       90% unmute 2>/dev/null || true
amixer -c $card sset 'ADC Capture Switch' on 2>/dev/null || true
amixer -c $card sset 'ADC Capture Volume' 160 2>/dev/null || true
amixer -c $card sset 'Mic Boost' 2 2>/dev/null || true
amixer -c $card sset 'Input PGA' 28 2>/dev/null || true
