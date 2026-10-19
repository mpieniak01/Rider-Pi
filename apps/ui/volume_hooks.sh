#!/bin/sh
# usage: volume_hooks.sh dim|off|on
case "$1" in
  dim) /home/pi/robot/scripts/util_volume.py set ${UI_AUDIO_DIM_PCT:-20} ;;
  off) [ "${UI_AUDIO_OFF_MUTE:-1}" = "1" ] && /home/pi/robot/scripts/util_volume.py mute on ;;
  on)  /home/pi/robot/scripts/util_volume.py mute off ; /home/pi/robot/scripts/util_volume.py set ${UI_BRIGHT_LEVEL:-80} ;;
  *) printf 'Usage: %s dim|off|on\n' "$0" >&2; exit 2 ;;
esac
