#!/usr/bin/env bash
set -e
pkill -f 'apps/camera/preview_.*\.py' 2>/dev/null || true
pkill -f 'apps/camera/ssd_.*\.py' 2>/dev/null || true
sudo fuser -kv /dev/video0 2>/dev/null || true
