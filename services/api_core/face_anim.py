# services/api_core/face_anim.py
from __future__ import annotations

import os
import threading
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from apps.ui.face.renderer import FaceRenderer

# Ścieżki artefaktów (testy czyszczą OUT_LATEST oraz OUT_LEGACY)
OUT_LATEST = os.environ.get("FACE_LATEST_PATH", "/tmp/face_latest.png")
OUT_LEGACY = os.environ.get("FACE_LEGACY_PATH", "/tmp/face_runtime.png")


def _env_sink_kind() -> str:
    return (os.environ.get("FACE_SINK", "file") or "file").strip().lower()


DEFAULT_SINK = _env_sink_kind()

ALLOWED = {"neutral", "happy", "sad", "blink"}
SINKS = {"file", "lcd", "null"}


def _norm_expr(v: str) -> str:
    v = str(v or "neutral").strip().lower()
    return v if v in ALLOWED else "neutral"


# ====================== SINKI (bez wczesnego LCD/SPI) ========================


class FaceSink:
    """Interfejs prezentacji klatek."""

    def present(self, img: Image.Image) -> None:
        raise NotImplementedError

    def present_png(self, data: bytes) -> None:
        """Opcjonalne: prezentacja z PNG bytes; jeśli nieobsługiwane, fallback w animatorze."""
        raise NotImplementedError


class NullSink(FaceSink):
    def present(self, img: Image.Image) -> None:
        pass

    def present_png(self, data: bytes) -> None:
        pass


class FileSink(FaceSink):
    """Zapisuje ostatnią klatkę do pliku PNG (OUT_LATEST)."""

    def __init__(self, path: str = OUT_LATEST):
        self.path = path
        Path(os.path.dirname(self.path) or "/tmp").mkdir(parents=True, exist_ok=True)

    def present(self, img: Image.Image) -> None:
        img.save(self.path, "PNG")

    def present_png(self, data: bytes) -> None:
        with open(self.path, "wb") as f:
            f.write(data)


class LcdNotAvailable(Exception):
    pass


def _resolve_sink_kind() -> str:
    """Return the sink kind based on the latest state or environment."""
    kind = str(STATE.get("sink") or "").strip().lower()
    if kind in SINKS:
        return kind
    env_kind = _env_sink_kind()
    return env_kind if env_kind in SINKS else "file"


def _make_sink() -> FaceSink:
    """Wybór sinka wg STATE['sink'] lub domyślnego środowiska."""
    kind = _resolve_sink_kind()
    if kind == "file":
        return FileSink(OUT_LATEST)
    elif kind == "lcd":
        # Lazy import + bezpieczny fallback (brak LCD nie wywala importu modułu przy starcie)
        try:
            from apps.hw.sink_lcd import SinkLCD  # type: ignore

            return SinkLCD()
        except Exception as e:  # brak HW/drivera
            raise LcdNotAvailable(f"LCD sink not available: {e}") from e
    else:
        return NullSink()


def _apply_requested_sink(payload: dict[str, Any]) -> None:
    sink_raw = payload.get("sink")
    if sink_raw is None:
        return
    kind = str(sink_raw).strip().lower()
    if kind in SINKS:
        STATE["sink"] = kind


# ====================== GLOBALNY STAN ANIMACJI ===============================

STATE: dict[str, Any] = {
    "playing": False,
    "running": False,
    "expr": "neutral",
    "fps": 20,
    "started_ts": None,
    "last_ts": None,
    "frame_count": 0,
    "_last_payload": None,
    "error": None,
    "sink": DEFAULT_SINK,
}

# ====================== ANIMATOR (wątek w tle) ===============================


class _Animator:
    def __init__(self) -> None:
        self._thr: threading.Thread | None = None
        self._stop = threading.Event()
        self._renderer: FaceRenderer | None = None
        self._sink: FaceSink = NullSink()

    def start(self) -> None:
        if self._thr and self._thr.is_alive():
            return
        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, name="face-anim", daemon=True)
        self._thr.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # Renderer – bez konfiguracji LCD, wyłącznie PNG bytes
        try:
            self._renderer = FaceRenderer(cfg={}, size=240, guide=False, quality="fast")
        except Exception:
            self._renderer = None

        # Sink – wybór wg ENV; LCD zamieniamy na NullSink jeśli niedostępny
        try:
            self._sink = _make_sink()
        except LcdNotAvailable:
            self._sink = NullSink()

        STATE["running"] = True
        STATE["started_ts"] = time.time()
        STATE["frame_count"] = 0
        last_tick = time.time()

        while not self._stop.is_set() and STATE.get("playing", False):
            fps = max(1, min(60, int(STATE.get("fps", 20) or 20)))
            expr = _norm_expr(STATE.get("expr"))
            face_state = SimpleNamespace(expr=expr, blink=False, pupil=0, tilt=0)

            try:
                if self._renderer:
                    # Źródłem prawdy jest PNG (FaceRenderer nie ma render_image)
                    png = self._renderer.render_png_bytes(face_state)

                    # Preferuj ścieżkę bezstratną, jeśli sink to obsłuży:
                    try:
                        self._sink.present_png(png)
                    except Exception:
                        # Fallback: dekoduj PNG -> PIL.Image i przekaż
                        img = Image.open(BytesIO(png)).convert("RGB")
                        self._sink.present(img)

                    # Jeśli sink jest "pusty", zachowaj ostatnią klatkę dla debug/DoD
                    if isinstance(self._sink, NullSink):
                        try:
                            with open(OUT_LATEST, "wb") as f:
                                f.write(png)
                        except Exception:
                            pass

            except Exception:
                # nie zabijaj pętli – odnotuj i jedź dalej
                STATE["error"] = "render"

            STATE["frame_count"] = int(STATE.get("frame_count", 0)) + 1
            STATE["last_ts"] = time.time()

            # utrzymaj zadany FPS
            dt = 1.0 / fps
            time.sleep(max(0.0, dt - (STATE["last_ts"] - last_tick)))
            last_tick = time.time()

        STATE["running"] = False


_anim = _Animator()

# ====================== FUNKCJE DLA API (czyste dicty) =======================


def play(payload: dict[str, Any]) -> dict[str, Any]:
    expr = _norm_expr(payload.get("expr"))
    fps = max(1, min(60, int(payload.get("fps", STATE.get("fps", 20) or 20))))
    _apply_requested_sink(payload)
    STATE.update(
        {
            "expr": expr,
            "fps": fps,
            "playing": True,
            "error": None,
            "_last_payload": dict(payload),
        }
    )
    _anim.start()
    return {"ok": True, "state": STATE}


def stop(_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    STATE["playing"] = False
    _anim.stop()
    # szybkie domknięcie pętli
    t0 = time.time()
    while STATE.get("running") and (time.time() - t0) < 0.5:
        time.sleep(0.01)
    return {"ok": True, "state": STATE}


def get_state() -> dict[str, Any]:
    return {"ok": True, "state": STATE}
