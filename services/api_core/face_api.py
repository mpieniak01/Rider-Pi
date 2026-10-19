from __future__ import annotations

# services/api_core/face_api.py
import os
from types import SimpleNamespace
from typing import Any

from . import face_exports

ALLOWED = {"neutral", "happy", "sad", "blink"}
ROT_ALLOWED = {0, 90, 180, 270}


def _env_int(name: str, default: int | None = None) -> int | None:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        return default


def _norm_expr(v: str) -> str:
    v = str(v or "neutral").lower().strip()
    return v if v in ALLOWED else "neutral"


def _norm_backend(p: dict[str, Any]) -> str:
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
        from apps.ui.face import model as m  # type: ignore

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
        from apps.ui.face import model as m  # type: ignore

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
    # Prefer FaceRenderer
    try:
        from apps.ui.face.renderer import FaceRenderer  # type: ignore

        cfg = _make_cfg()
        state = _make_state(expr)
        r = FaceRenderer(cfg, size=size, guide=False, quality="fast")
        png = r.render_png_bytes(state)  # -> bytes
        if not isinstance(png, (bytes, bytearray)):
            raise RuntimeError("render_png_bytes did not return bytes")
        return png
    except Exception:
        # Fallback: FaceController → frame() / frame_image()
        try:
            from io import BytesIO

            from PIL import Image

            from apps.ui.face.controller import FaceController  # type: ignore

            fc = FaceController(size=size, fps=1, idle=True)
            fc.set_expr(expr)
            try:
                img = fc.frame_image().convert("RGB")
            except Exception:
                buf = BytesIO(fc.frame())
                img = Image.open(buf).convert("RGB")
            out = BytesIO()
            img.save(out, format="PNG")
            try:
                if hasattr(fc, "close"):
                    fc.close()
            except Exception:
                pass
            return out.getvalue()
        except Exception as e2:
            raise RuntimeError(f"fallback-controller-error: {e2}") from e2


def _rotate_png_bytes(png: bytes, rot: int) -> bytes:
    """Obróć PNG w pamięci (jeśli rot ∈ {90,180,270}); brak zmian dla 0."""
    if rot not in ROT_ALLOWED or rot == 0:
        return png
    try:
        from io import BytesIO

        from PIL import Image

        img = Image.open(BytesIO(png)).convert("RGB")
        # zgodnie z wcześniejszą konwencją: 270 oznacza obrót w prawo
        img = img.rotate(360 - rot, expand=True)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        # Rotacja jest opcjonalna — lepiej zwrócić oryginał niż 500 na API.
        return png


def _one_frame_pil(expr: str, size: int):
    """Wyrenderuj jedną klatkę jako PIL.Image (bezpośrednio, nie PNG)."""
    try:
        from apps.ui.face.renderer import FaceRenderer  # type: ignore

        cfg = _make_cfg()
        state = _make_state(expr)
        r = FaceRenderer(cfg, size=size, guide=False, quality="fast")
        return r.render_image(state=state)  # PIL.Image
    except Exception:
        from io import BytesIO

        from PIL import Image

        from apps.ui.face.controller import FaceController  # type: ignore

        fc = FaceController(size=size, fps=1, idle=True)
        fc.set_expr(expr)
        try:
            return fc.frame_image().convert("RGB")
        except Exception:
            buf = BytesIO(fc.frame())
            return Image.open(buf).convert("RGB")


def render_face(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Minimalny shim nowego API rysowania twarzy.

    Wejście (przykład):
      {"expr":"neutral","backend":"png","out":"/tmp/face_api.png","rotate":270,"size":240}

    Wyjście:
      - sukces: {"ok": true, "out": "..."} lub {"ok": true, "used": "..."} (dla LCD)
      - błąd:   {"ok": false, "error": "...", "status": 503?}
    """
    if not isinstance(payload, dict):
        return {"ok": False, "error": "invalid_face_preview", "status": 400}
    b = _norm_backend(payload)
    ex = _norm_expr(payload.get("expr"))
    if b == "png":
        try:
            size, rot = _png_options(payload)
            out = face_exports.target(payload.get("out"))
        except (ValueError, TypeError, OverflowError) as error:
            code = "invalid_face_output" if str(error) == "invalid_face_output" else "invalid_face_preview"
            return {"ok": False, "error": code, "status": 400}
        except OSError:
            return {"ok": False, "error": "face_export_unavailable", "status": 503}
        try:
            png = _rotate_png_bytes(_render_png_bytes(ex, size), rot)
        except Exception:
            return {"ok": False, "error": "face_renderer_unavailable", "status": 503}
        try:
            face_exports.save(out, png)
        except OSError:
            return {"ok": False, "error": "face_export_unavailable", "status": 503}
        return {"ok": True, "out": str(out)}
    if b in {"lcd", "raw"}:
        from services.api_core.face_runtime_api import play

        return play({"expr": ex, "sink": "lcd", "duration_s": payload.get("duration_s", 1)})
    return {"ok": False, "error": "unknown_face_backend", "status": 400}


def _png_options(payload):
    size = int(payload.get("size", 240))
    rot = int(payload.get("rotate", payload.get("rotation", _env_int("FACE_LCD_ROTATE", 0))))
    if not 16 <= size <= 1024 or rot not in ROT_ALLOWED:
        raise ValueError("invalid_face_preview")
    return size, rot


# ---- Public wrappers / kompatybilność ----------------------------------------


def render(**kwargs) -> dict[str, Any]:
    """
    Wrapper kompatybilności: pozwala wywołać face_api.render(backend=..., expr=..., ...)
    i otrzymać dict z rezultatem.
    """
    return render_face(dict(kwargs))


def draw_face(payload_or_expr=None, backend="png", out=None, **kwargs) -> tuple[dict[str, Any], int]:
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
    status = res.get("status", 200 if res.get("ok") else 400)
    return res, status


def png_response(payload):
    """Serve an in-memory HTTP preview without creating a file or LCD owner."""
    from flask import Response, jsonify, request

    if not isinstance(payload, dict):
        return jsonify(ok=False, error="invalid_face_preview"), 400
    if _norm_backend(payload) != "png" or "out" in payload or "image/png" not in request.headers.get("Accept", ""):
        return None
    try:
        size, rot = _png_options(payload)
        png = _rotate_png_bytes(_render_png_bytes(_norm_expr(payload.get("expr")), size), rot)
        return Response(png, mimetype="image/png", headers={"Cache-Control": "no-store"})
    except (ValueError, TypeError, OverflowError):
        return jsonify(ok=False, error="invalid_face_preview"), 400
    except RuntimeError:
        return jsonify(ok=False, error="face_renderer_unavailable"), 503
