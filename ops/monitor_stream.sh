#!/usr/bin/env bash
set -euo pipefail
journalctl -u rider-web-bridge.service -u rider-motion-bridge.service -f -o short-iso |
awk '
  function color(c,s){ return sprintf("\033[%sm%s\033[0m",c,s) }
  / \[web\] /    { print color("36", $0); next }      # cyjan
  / \[bridge\] / { print color("33", $0); next }      # żółty
  { print $0 }
'
