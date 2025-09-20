# tests/test_face_anim_api.py
import os
import sys
import time

import pytest

from services.api_core import face_anim as fa

# Import same Flask app as serwer – import NIE uruchamia main()
from services.api_server import app


@pytest.fixture(autouse=True)
def _clean_anim():
    """Zatrzymuj pętlę przed/po teście i porządkuj stan oraz pliki."""
    # stop na wypadek "wiszącej" animacji
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
        }
    )

    # usuń artefakty
    for p in (fa.OUT_LATEST, fa.OUT_LEGACY, "/tmp/face_api_test.png", "/tmp/face_api_legacy_test.png"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass

    yield

    # ensure stop na końcu
    try:
        fa.stop({})
    except Exception:
        pass


def _client():
    return app.test_client()


def _poll_until(fn, timeout=0.6, step=0.03):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True
        time.sleep(step)
    return False


def test_play_state_stop_flow():
    c = _client()

    # start
    rv = c.post("/face/play", json={"expr": "happy", "fps": 20})
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert data["state"]["playing"] is True

    time.sleep(0.25)

    # sprawdź state
    rv = c.get("/face/state")
    assert rv.status_code == 200
    st = rv.get_json()["state"]
    assert st["playing"] is True
    assert st["last_ts"] is not None
    assert int(st["frame_count"]) >= 1

    # stop
    rv = c.post("/face/stop", json={})
    assert rv.status_code == 200
    assert rv.get_json()["ok"] is True

    # DoD: stopuje się < ~0.5 s
    ok = _poll_until(lambda: _client().get("/face/state").get_json()["state"]["playing"] is False, timeout=0.6)
    assert ok, "playing nie przeszło na False w 0.6 s"


def test_face_latest_png_written():
    c = _client()

    assert not os.path.exists(fa.OUT_LATEST)
    rv = c.post("/face/play", json={"expr": "neutral", "fps": 15})
    assert rv.status_code == 200

    time.sleep(0.35)  # pozwól wyrenderować kilka klatek

    assert os.path.exists(fa.OUT_LATEST), "brak /tmp/face_latest.png"
    assert os.path.getsize(fa.OUT_LATEST) > 1000, "plik jest zbyt mały (<1 KB?)"

    # stop
    c.post("/face/stop", json={})


def test_snapshot_png_backend_ok():
    c = _client()
    out = "/tmp/face_api_test.png"
    try:
        os.remove(out)
    except FileNotFoundError:
        pass

    rv = c.post(
        "/face/render",
        json={"expr": "neutral", "backend": "png", "out": out, "rotate": 270, "size": 240},
    )
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert data["out"] == out
    assert os.path.exists(out)
    assert os.path.getsize(out) > 1000


def test_legacy_draw_face_ok():
    c = _client()
    out = "/tmp/face_api_legacy_test.png"
    try:
        os.remove(out)
    except FileNotFoundError:
        pass

    rv = c.post("/api/draw/face", json={"expr": "neutral", "backend": "png", "out": out})
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["ok"] is True
    assert os.path.exists(out)
    assert os.path.getsize(out) > 1000


def test_global_cors_header_present():
    c = _client()
    rv = c.get("/face/ping")
    # after_request w api_server powinien dodać nagłówki
    assert rv.headers.get("Access-Control-Allow-Origin") == "*"
    assert "GET" in rv.headers.get("Access-Control-Allow-Methods", "")


def test_no_lcd_spi_imports():
    # Best-effort: w trakcie animacji w sys.modules nie powinno być sterowników LCD/SPI
    c = _client()
    c.post("/face/play", json={"expr": "neutral", "fps": 15})
    time.sleep(0.2)

    forbidden = [k for k in sys.modules.keys() if k.startswith("apps.hw") or "sink_lcd" in k or "spi" in k]
    # dozwolone: puste — nie chcemy HW w tej fazie
    assert not forbidden, f"wygląda na importy HW: {forbidden[:5]}"

    c.post("/face/stop", json={})
