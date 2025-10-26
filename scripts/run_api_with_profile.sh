#!/bin/bash
set -euo pipefail
set -a
[ -r "$HOME/.bash_profile" ] && . "$HOME/.bash_profile"
set +a
cd /home/pi/robot
exec /usr/bin/python3 -u -m services.api_server
