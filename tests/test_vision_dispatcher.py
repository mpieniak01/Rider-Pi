from __future__ import annotations

import importlib
import time


def test_presence_hysteresis(monkeypatch):
    disp = importlib.import_module("apps.vision.dispatcher")
    monkeypatch.setattr(disp, "P_ON_N", 2)
    monkeypatch.setattr(disp, "P_OFF_TT", 0.3)
    monkeypatch.setattr(disp, "MIN_SCORE", 0.5)
    monkeypatch.setattr(disp, "STATE", disp.PresenceState())
    published = []

    def fake_pub(topic, payload):
        published.append((topic, payload))

    monkeypatch.setattr(disp, "pub", fake_pub)

    # 1) pojedynczy pozytyw — nie powinno jeszcze włączyć present
    evt = disp.normalize_event("vision.person", {"present": True, "score": 0.8})
    disp.update_presence(evt)
    assert disp.STATE.present is False

    # 2) drugi pozytyw — powinniśmy wejść w present=True i mieć vision.state
    disp.update_presence(evt)
    assert disp.STATE.present is True
    assert any(t == "vision.state" and p.get("present") is True for t, p in published)

    # 3) brak pozytywów -> po TTL stan gaśnie
    time.sleep(0.35)
    disp.update_presence({"present": False, "score": 0.0, "kind": "person", "bbox": None})
    assert disp.STATE.present is False
    assert any(t == "vision.state" and p.get("present") is False for t, p in published)
