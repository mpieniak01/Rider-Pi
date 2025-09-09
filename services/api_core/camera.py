#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, mimetypes
from flask import Response, make_response, send_file, abort
from . import compat as C

# --- konfiguracja i pomocnicze ---
_EXTS = (".jpg", ".png", ".bmp")
_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".bmp": "image/bmp",
}
SNAP_MAX_AGE_S = int(os.getenv("SNAP_MAX_AGE_S", "20"))  # po ilu sekundach uznać klatkę za przeterminowaną

# Upewnij się, że porównujemy ścieżki absolutne
_SNAP_DIR_ABS = os.path.abspath(C.SNAP_DIR)

def _resolve_snap(name: str):
    """
    Zwróć (full_path, ext, mimetype) dla 'raw' lub 'proc',
    próbując kolejno .jpg, .png, .bmp. Gdy brak – None.
    """
    for ext in _EXTS:
        full = os.path.join(_SNAP_DIR_ABS, f"{name}{ext}")
        if os.path.isfile(full):
            mime = _MIME.get(ext, mimetypes.guess_type(full)[0] or "application/octet-stream")
            return full, ext, mime
    return None

def _fresh(path: str) -> bool:
    """Czy plik jest świeższy niż próg SNAP_MAX_AGE_S?"""
    try:
        return (time.time() - os.path.getmtime(path)) <= SNAP_MAX_AGE_S
    except Exception:
        return False

def _nocache_file_response(path: str, mime: str | None = None):
    """Zwróć plik z nagłówkami twardo wyłączającymi cache."""
    resp = make_response(send_file(path, mimetype=mime, conditional=False))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp

# --- endpoints ---
def camera_raw():
    r = _resolve_snap("raw")
    if not r:
        return Response('{"error":"no_raw"}', mimetype="application/json", status=404)
    full, _ext, mime = r
    if not _fresh(full):
        return Response('{"error":"stale_raw"}', mimetype="application/json", status=404)
    return _nocache_file_response(full, mime)

def camera_proc():
    r = _resolve_snap("proc")
    if not r:
        return Response('{"error":"no_proc"}', mimetype="application/json", status=404)
    full, _ext, mime = r
    if not _fresh(full):
        return Response('{"error":"stale_proc"}', mimetype="application/json", status=404)
    return _nocache_file_response(full, mime)

def camera_last():
    # alias do RAW, z silniejszymi nagłówkami anti-cache
    r = _resolve_snap("raw")
    if not r:
        return Response('{"error":"no_raw"}', mimetype="application/json", status=404)
    full, _ext, mime = r
    return _nocache_file_response(full, mime)

def camera_placeholder():
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360">
  <rect width="100%" height="100%" fill="#111"/>
  <text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle"
        font-family="monospace" font-size="20" fill="#ccc">
    Brak podglądu (vision wyłączone)
  </text>
  <text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle"
        font-family="monospace" font-size="12" fill="#777">
    /camera/raw i /camera/proc zwrócą 404 gdy klatka jest przeterminowana
  </text>
</svg>
""".strip()
    resp = make_response(svg)
    resp.headers["Content-Type"] = "image/svg+xml"
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

def snapshots_static(fname: str):
    """
    Serwuje dowolny plik ze SNAP_DIR po nazwie (np. raw.png, proc.bmp).
    Chroni przed traversalem ścieżek i dobiera mimetype po rozszerzeniu.
    """
    safe = os.path.abspath(os.path.join(_SNAP_DIR_ABS, fname))
    # musi leżeć wewnątrz katalogu snapshots
    if not (safe.startswith(_SNAP_DIR_ABS + os.sep)):
        return abort(403)
    if not os.path.isfile(safe):
        return abort(404)
    mime = _MIME.get(os.path.splitext(safe)[1].lower(), mimetypes.guess_type(safe)[0] or "application/octet-stream")
    return _nocache_file_response(safe, mime)


