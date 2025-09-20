# services/api_core/face_api.py
import os
from types import SimpleNamespace
from typing import Any

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
    try:
        b = _norm_backend(payload)
        ex = _norm_expr(payload.get("expr"))
        out = payload.get("out")
        size = int(payload.get("size", 240))

        # normalizacja rotacji: payload → ENV → 0
        rot = int(payload.get("rotate", payload.get("rotation", _env_int("FACE_LCD_ROTATE", 0))))

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
            # Jednorazowy push na LCD — użyj narzędzia newface_lcd_direct jeśli dostępne.
            # Parametry pomocnicze (opcjonalne)
            spi_hz = payload.get("spi_hz", _env_int("FACE_LCD_SPI_HZ"))
            bl_pin = int(payload.get("bl_pin", _env_int("FACE_LCD_BL_PIN", 13)))
            force = payload.get("force")  # np. "rgb565_3", "pil", "raw", itp.

            try:
                # PIL klatka (bez wstępnego obracania — zrobi to LCDDirect)
                img = _one_frame_pil(ex, size)

                # Importujemy local tool do LCD:
                from tools import newface_lcd_direct as nfd  # type: ignore

                lcd = nfd.LCDDirect(rotate=rot, size=size, spi_hz=spi_hz, bl_pin=bl_pin, force=force)
                used = lcd.push(img)
                # sprzątanie, jeśli sterownik ma metody kończące — robione wewnątrz toola
                return {"ok": True, "used": used}
            except Exception as e:
                # Na hostach bez LCD/drivera zwracamy 503 (przechwytywane wyżej)
                return {"ok": False, "error": f"lcd-error: {e}", "status": 503}

        else:
            return {"ok": False, "error": f"unknown backend: {b or 'none'}"}

    except Exception as e:
        return {"ok": False, "error": f"unexpected-error: {e}"}


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
    status = 503 if (not res.get("ok") and res.get("status") == 503) else 200
    return res, status
