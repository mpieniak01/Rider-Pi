#!/usr/bin/env bash
# Użycie:  . scripts/export_env.sh   (kropka + spacja)
set -a
[ -f .env ] && . ./.env
set +a
echo "[env] exported from .env (if present)"
