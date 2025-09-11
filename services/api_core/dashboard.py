#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from flask import Response, send_file
from . import compat as C

def dashboard():
    if not os.path.isfile(C.VIEW_HTML):
        return Response(
            "<h1>Rider-Pi API</h1><p>Brak web/view.html – użyj <a href='/state'>/state</a>, "
            "<a href='/sysinfo'>/sysinfo</a>, <a href='/healthz'>/healthz</a>.</p>",
            mimetype="text/html"
        ), 200
    return send_file(C.VIEW_HTML)

def control_page():
    if not os.path.isfile(C.CONTROL_HTML):
        return Response("<h1>control.html missing</h1>", mimetype="text/html"), 404
    return send_file(C.CONTROL_HTML)
