#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from flask import Response, send_from_directory, make_response, send_file, abort
from . import compat as C

def camera_raw():
    if not os.path.isfile(C.RAW_PATH):
        return Response('{"error":"no_raw"}', mimetype="application/json", status=404)
    return send_from_directory(C.SNAP_DIR, "raw.jpg", cache_timeout=0)

def camera_proc():
    if not os.path.isfile(C.PROC_PATH):
        return Response('{"error":"no_proc"}', mimetype="application/json", status=404)
    return send_from_directory(C.SNAP_DIR, "proc.jpg", cache_timeout=0)

def camera_last():
    if not os.path.isfile(C.RAW_PATH):
        return Response('{"error":"no_raw"}', mimetype="application/json", status=404)
    resp = make_response(send_file(C.RAW_PATH, mimetype="image/jpeg"))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"; resp.headers["Expires"] = "0"
    return resp

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
    /camera/last zwróci 404, gdy brak klatki
  </text>
</svg>
""".strip()
    resp = make_response(svg)
    resp.headers["Content-Type"] = "image/svg+xml"
    resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp

def snapshots_static(fname: str):
    safe = os.path.abspath(os.path.join(C.SNAP_DIR, fname))
    if not safe.startswith(C.SNAP_DIR): return abort(403)
    if not os.path.isfile(safe): return abort(404)
    return send_from_directory(C.SNAP_DIR, fname, cache_timeout=0)
