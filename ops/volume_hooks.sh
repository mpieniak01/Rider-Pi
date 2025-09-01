#!/bin/sh
# usage: volume_hooks.sh dim|off|on
case "$1" in
  dim) /home/pi/robot/tools/volume.py set ${UI_AUDIO_DIM_PCT:-20} ;;
  off) [ "${UI_AUDIO_OFF_MUTE:-1}" = "1" ] && /home/pi/robot/tools/volume.py mute on ;;
  on)  /home/pi/robot/tools/volume.py mute off ; /home/pi/robot/tools/volume.py set ${UI_XGO_BRIGHT:-80} ;;
esac