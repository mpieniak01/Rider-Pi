from typing import Dict, Any
from types import SimpleNamespace

ALLOWED = {"neutral","happy","sad","blink"}

def _norm_expr(v: str) -> str:
    v = str(v or "neutral").lower().strip()
    return v if v in ALLOWED else "neutral"

def _norm_backend(p: Dict[str, Any]) -> str:
    # akceptuj obie konwencje: backend / sink
    return str(p.get("backend", p.get("sink", "png"))).lower().strip()

def _make_cfg():
    # spróbuj modelu, w razie czego pusty dict
    try:
        from apps.ui.face import model as m
        # preferuj fabryki/konfiguracje jeśli są
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
    # spróbuj FaceState z modelu; jeśli brak — minimalny obiekt
    try:
        from apps.ui.face import model as m
        for name in ("FaceState","State","FaceCtx","Face"):
            if hasattr(m, name):
                C = getattr(m, name)
                try:
                    # próby różnych konstruktorów
                    try:
                        return C(expr=expr)
                    except TypeError:
                        return C(expr)
                except Exception:
                    continue
    except Exception:
        pass
    # Minimalny „lookalike” — wystarcza do rysunku neutral/happy/sad/blink
    return SimpleNamespace(expr=expr, blink=False, pupil=0, tilt=0)

def _render_png_bytes(expr: str, size: int, rotate: int) -> bytes:
    # Użyj nowej architektury
    from apps.ui.face.renderer import FaceRenderer
    cfg = _make_cfg()
    state = _make_state(expr)
    # FaceRenderer(cfg, size=..., guide=False, quality="fast")
    r = FaceRenderer(cfg, size=size, guide=False, quality="fast")
    png = r.render_png_bytes(state)  # -> bytes
    if not isinstance(png, (bytes, bytearray)):
        raise RuntimeError("render_png_bytes did not return bytes")
    return png

def render_face(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    JSON przykład:
      {"expr":"neutral","backend":"png","out":"/tmp/face_api.png","rotate":270,"size":240}
    Zwraca: {"ok": true, "out": "..."} albo {"ok": false, "error": "...", "status": 503}
    """
    try:
        b  = _norm_backend(payload)
        ex = _norm_expr(payload.get("expr"))
        out = payload.get("out")
        size = int(payload.get("size", 240))
        rot  = int(payload.get("rotate", 0))

        if b in {"png","file","image"}:
            try:
                png = _render_png_bytes(ex, size, rot)
            except Exception as e:
                return {"ok": False, "error": f"renderer-error: {e}"}
            if not out:
                return {"ok": False, "error": "missing 'out' for file backend"}
            try:
                with open(out, "wb") as f:
                    f.write(png)
                return {"ok": True, "out": out}
            except Exception as e:
                return {"ok": False, "error": f"save-error: {e}"}

        elif b in {"lcd","raw"}:
            # Bez HW w tym shime — czytelny sygnał dla serwera (503)
            return {"ok": False, "error": "LCD backend not available on this host", "status": 503}

        else:
            return {"ok": False, "error": f"unknown backend: {b or 'none'}"}

    except Exception as e:
        return {"ok": False, "error": f"unexpected-error: {e}"}
