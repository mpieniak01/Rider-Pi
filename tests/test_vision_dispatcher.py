# tests/test_vision_dispatcher.py
import importlib, os, time, types

# ustaw progi, żeby test był szybki
os.environ["VISION_ON_CONSECUTIVE"] = "2"
os.environ["VISION_OFF_TTL_SEC"] = "0.3"
os.environ["VISION_MIN_SCORE"] = "0.5"

disp = importlib.import_module("apps.vision.dispatcher")

# przechwyć pub()
published = []
def fake_pub(topic, payload):
    published.append((topic, payload))
disp.pub = fake_pub  # monkeypatch

def test_presence_hysteresis():
    # reset stanu
    disp.STATE.present = False
    disp.STATE.consecutive_pos = 0
    disp.STATE.confidence = 0.0
    published.clear()

    # 1) pojedynczy pozytyw — nie powinno jeszcze włączyć present
    evt = disp.normalize_event("vision.person", {"present": True, "score": 0.8})
    disp.update_presence(evt)
    assert disp.STATE.present is False

    # 2) drugi pozytyw — powinniśmy wejść w present=True i mieć vision.state
    disp.update_presence(evt)
    assert disp.STATE.present is True
    assert any(t=="vision.state" and p.get("present") is True for t,p in published)

    # 3) brak pozytywów -> po TTL stan gaśnie
    time.sleep(0.35)
    disp.update_presence({"present": False, "score": 0.0, "kind": "person", "bbox": None})
    assert disp.STATE.present is False
    assert any(t=="vision.state" and p.get("present") is False for t,p in published)
