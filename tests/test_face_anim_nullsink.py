# tests/test_face_anim_nullsink.py
import os
import time
import importlib
import pytest

import services.api_core.face_anim as fa


@pytest.fixture(autouse=True)
def _clean_anim(monkeypatch):
    """Zatrzymuj pętlę i czyść artefakty przed/po teście."""
    # stop na wypadek wiszącej pętli
    try:
        fa.stop({})
    except Exception:
        pass

    # reset stanu
    fa.STATE.update(
        {
            "playing": False,
            "running": False,
            "expr": "neutral",
            "fps": 20,
            "started_ts": None,
            "last_ts": None,
            "frame_count": 0,
            "error": None,
            "_last_payload": None,
        }
    )

    # usuń pliki
    for p in (getattr(fa, "OUT_LATEST", "/tmp/face_latest.png"),
              getattr(fa, "OUT_LEGACY", "/tmp/face_runtime.png")):
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    yield

    # po teście — spróbuj jeszcze raz zatrzymać pętlę
    try:
        fa.stop({})
    except Exception:
        pass


def test_out_legacy_constant_exists():
    """Sanity: stała OUT_LEGACY musi istnieć (testy z niej korzystają)."""
    assert hasattr(fa, "OUT_LEGACY"), "OUT_LEGACY missing in face_anim.py"
    assert isinstance(fa.OUT_LEGACY, str) and len(fa.OUT_LEGACY) > 0


def test_null_sink_mirrors_latest_png(monkeypatch):
    """
    Przy FACE_SINK=null animator powinien nadal zapisać ostatnią klatkę do OUT_LATEST
    (mirror do PNG) — bez crashy i bez zależności od LCD/SPI.
    """
    monkeypatch.setenv("FACE_SINK", "null")

    # start animacji
    res = fa.play({"expr": "happy", "fps": 15})
    assert res.get("ok") is True
    assert fa.STATE["playing"] is True

    # poczekaj na kilka klatek
    time.sleep(1.2)

    # stop animacji
    fa.stop({})
    assert fa.STATE["playing"] is False

    # sprawdź mirror do OUT_LATEST
    out_latest = getattr(fa, "OUT_LATEST", "/tmp/face_latest.png")
    assert os.path.exists(out_latest), f"brak pliku {out_latest}"
    assert os.path.getsize(out_latest) > 1000, "plik OUT_LATEST jest podejrzanie mały (<1KB)"
