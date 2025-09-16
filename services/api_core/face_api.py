# services/api_core/face_api.py
from typing import Dict, Any, Tuple
from types import SimpleNamespace
import os

ALLOWED = {"neutral", "happy", "sad", "blink"}
ROT_ALLOWED = {0, 90, 180, 270}


def _norm_expr(v: str) -> str:
    v = str(v or "neutral").lower().strip()
    return v if v in ALLOWED else "neutral"


def _norm_backend(p: Dict[str, Any]) -> str:
    """
    Akceptuje obie konwencje: 'backend' lub 'sink'.
    Dla ścieżki plikowej działają aliasy: file/image/png.
    """
    b = str(p.get("backend", p.get("sink", "png"))).lower().strip()
    if b in {"file", "image"}:
        b = "png"
    return b


def _make_cfg():
    """Spróbuj pobrać konfigurację twarzy z apps.ui.face.model; w razie czego {}."""
    try:
        from apps.ui.face import model as m
        for name in ("default_cfg", "make_cfg", "FaceConfig", "Config"):
            if hasattr(m, name):
                obj = getattr(m, name)
                try:
                    return obj() if callable(obj) else obj
                except Exception:
                    return obj
    except Exception:
        pass
    return {}


def _make_state(expr: str):
    """Spróbuj FaceState z modelu; w razie niepowodzenia — minimalny lookalike."""
    try:
        from apps.ui.face import model as m
        for name in ("FaceState", "State", "FaceCtx", "Face"):
            if hasattr(m, name):
                C = getattr(m, name)
                try:
                    try:
                        return C(expr=expr)
                    except TypeError:
                        return C(expr)
                except Exception:
                    continue
    except Exception:
        pass
    return SimpleNamespace(expr=expr, blink=False, pupil=0, tilt=0)


def _render_png_bytes(expr: str, size: int) -> bytes:
    """Użyj nowej architektury renderera do wygenerowania PNG (bytes)."""
    from apps.ui.face.renderer import FaceRenderer
    cfg = _make_cfg()
    state = _make_state(expr)
    r = FaceRenderer(cfg, size=size, guide=False, quality="fast")
    png = r.render_png_bytes(state)  # -> bytes
    if not isinstance(png, (bytes, bytearray)):
        raise RuntimeError("render_png_bytes did not return bytes")
    return png


def _rotate_png_bytes(png: bytes, rot: int) -> bytes:
    """Obróć PNG w pamięci (jeśli rot ∈ {90,180,270}); brak zmian dla 0."""
    if rot not in ROT_ALLOWED or rot == 0:
        return png
    try:
        from io import BytesIO
        from PIL import Image
        img = Image.open(BytesIO(png)).convert("RGB")
        img = img.rotate(360 - rot, expand=True)  # zgodnie z wcześniejszą konwencją
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        # Rotacja jest opcjonalna — lepiej zwrócić oryginał niż 500 na API.
        return png


def render_face(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Minimalny shim nowego API rysowania twarzy.

    Wejście (przykład):
      {"expr":"neutral","backend":"png","out":"/tmp/face_api.png","rotate":270,"size":240}

    Wyjście:
      - sukces: {"ok": true, "out": "..."}
      - błąd:   {"ok": false, "error": "...", "status": 503?}
    """
    try:
        b = _norm_backend(payload)
        ex = _norm_expr(payload.get("expr"))
        out = payload.get("out")
        size = int(payload.get("size", 240))
        rot = int(payload.get("rotate", payload.get("rotation", 0)))

        if b == "png":
            try:
                png = _render_png_bytes(ex, size)
                png = _rotate_png_bytes(png, rot)
            except Exception as e:
                return {"ok": False, "error": f"renderer-error: {e}"}

            if not out:
                return {"ok": False, "error": "missing 'out' for file backend"}

            try:
                os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
                with open(out, "wb") as f:
                    f.write(png)
                return {"ok": True, "out": out}
            except Exception as e:
                return {"ok": False, "error": f"save-error: {e}"}

        elif b in {"lcd", "raw"}:
            # Bez HW w tym shime – czytelny sygnał (503), przechwytywany w api_server.
            return {"ok": False, "error": "LCD backend not available on this host", "status": 503}

        else:
            return {"ok": False, "error": f"unknown backend: {b or 'none'}"}

    except Exception as e:
        return {"ok": False, "error": f"unexpected-error: {e}"}


# ---- Back-compat: legacy API (np. services/api_core/compat.py) ---------------
def draw_face(payload_or_expr=None, backend="png", out=None, **kwargs) -> Tuple[Dict[str, Any], int]:
    """
    Kompatybilność dla starego kodu wołającego face_api.draw_face(...).
    Przyjmuje:
      - dict payload, albo
      - stare wywołanie (expr, backend, out, **kwargs)
    Zwraca: (body: dict, status: int)
    """
    if isinstance(payload_or_expr, dict):
        payload = dict(payload_or_expr)
    else:
        payload = {"expr": payload_or_expr, "backend": backend, "out": out}
        if kwargs:
            payload.update(kwargs)

    res = render_face(payload)
    status = int(res.get("status", 200))
    return res, status

def draw_face(payload: Dict[str, Any]):
    """Legacy compat: keep /api/draw/face working. Returns (body, http_status)."""
    res = render_face(payload)
    status = 503 if (not res.get("ok") and res.get("status") == 503) else 200
    return res, status
