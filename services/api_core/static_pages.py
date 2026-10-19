"""Static operator page handlers; importing them never starts services."""

import os

from flask import Response, abort, make_response, send_from_directory

HTML_CONTENT_TYPE = "text/html; charset=utf-8"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_WEB_DIR = os.path.abspath(os.getenv("WEB_DIR") or os.path.join(os.path.dirname(BASE_DIR), "web"))


def _no_cache(resp: Response) -> Response:
    """Wspólne nagłówki anti-cache dla statyków."""
    try:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    except Exception:
        pass
    return resp


def serve_web(fname: str):
    """Serwuje pliki z katalogu web/ (wyłącznie pliki, brak tras katalogowych)."""
    if not fname or ".." in fname or fname.startswith(("/", "\\")):
        abort(404)
    resp = send_from_directory(STATIC_WEB_DIR, fname)
    return _no_cache(resp)


def serve_home():
    """Krótka trasa /home → web/home.html (bez katalogów, bez redirectów)."""
    return _no_cache(send_from_directory(STATIC_WEB_DIR, "home.html"))


def serve_chat():
    """Krótka trasa /chat → web/chat.html bez 30x."""
    chat_path = os.path.join(STATIC_WEB_DIR, "chat.html")
    if not os.path.isfile(chat_path):
        abort(404)
    # czytaj surowo, ustaw content-type i anti-cache
    with open(chat_path, "rb") as f:
        data = f.read()
    resp = make_response(data, 200)
    resp.headers["Content-Type"] = HTML_CONTENT_TYPE
    return _no_cache(resp)


def serve_navigation():
    """Krótka trasa /navigation → web/navigation.html"""
    nav_path = os.path.join(STATIC_WEB_DIR, "navigation.html")
    if not os.path.isfile(nav_path):
        abort(404)
    # czytaj surowo, ustaw content-type i anti-cache
    with open(nav_path, "rb") as f:
        data = f.read()
    resp = make_response(data, 200)
    resp.headers["Content-Type"] = HTML_CONTENT_TYPE
    return _no_cache(resp)


def serve_google_home():
    """Krótka trasa /google_home → web/google_home.html"""
    gh_path = os.path.join(STATIC_WEB_DIR, "google_home.html")
    if not os.path.isfile(gh_path):
        abort(404)
    with open(gh_path, "rb") as f:
        data = f.read()
    resp = make_response(data, 200)
    resp.headers["Content-Type"] = HTML_CONTENT_TYPE
    return _no_cache(resp)
